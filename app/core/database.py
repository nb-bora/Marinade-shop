from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import settings

Base = declarative_base()


def set_db_context(db: Session, name: str, value: str | None) -> None:
    """Set a transaction-local PostgreSQL setting used by the RLS policies."""
    db.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": name, "value": value or ""},
    )


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
