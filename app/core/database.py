from functools import lru_cache

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import settings

Base = declarative_base()

_RLS_KEY = "rls_context"
_ACCESS_KEY = "tenant_access"


def set_db_contexts(db: Session, values: dict[str, str | None]) -> None:
    """Set several transaction-local PostgreSQL settings in ONE round trip.

    The RLS policies read these settings. The values are also remembered on the
    session so later code can tell what is already active without asking the
    database (see ``get_db_context``).
    """
    items = list(values.items())
    clauses = ", ".join(f"set_config(:n{i}, :v{i}, true)" for i in range(len(items)))
    params: dict[str, str] = {}
    for index, (name, value) in enumerate(items):
        params[f"n{index}"] = name
        params[f"v{index}"] = value or ""
    db.execute(text(f"SELECT {clauses}"), params)
    db.info.setdefault(_RLS_KEY, {}).update({n: v or "" for n, v in items})


def set_db_context(db: Session, name: str, value: str | None) -> None:
    """Set a transaction-local PostgreSQL setting used by the RLS policies."""
    set_db_contexts(db, {name: value})


def get_db_context(db: Session, name: str) -> str:
    """Value this session last set for ``name`` in the CURRENT transaction."""
    return db.info.get(_RLS_KEY, {}).get(name, "")


@event.listens_for(Session, "after_transaction_end")
def _forget_transaction_state(session: Session, transaction) -> None:
    # set_config(..., true) lasts one transaction: once it ends, the database has
    # forgotten the context, so everything remembered about it must go too.
    if transaction.parent is None:
        session.info.pop(_RLS_KEY, None)
        session.info.pop(_ACCESS_KEY, None)


def database_role_bypasses_rls(db: Session) -> bool | None:
    """True when the connected role ignores RLS (superuser or BYPASSRLS).

    Returns None when the role cannot be inspected. Table owners also bypass RLS
    unless the table uses FORCE ROW LEVEL SECURITY, which the migrations enable.
    """
    row = db.execute(
        text(
            "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
    ).first()
    return None if row is None else bool(row[0])


@lru_cache(maxsize=1)
def get_engine():
    return create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=10,
        max_overflow=20,
        connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT_SECONDS},
    )


@lru_cache(maxsize=1)
def get_session_local():
    return sessionmaker(
        bind=get_engine(),
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


def get_db() -> Session:
    db = get_session_local()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
