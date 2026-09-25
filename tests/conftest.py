"""Shared, non-destructive test infrastructure.

Integration tests must use TEST_DATABASE_URL explicitly. They never create,
drop, migrate, or truncate a database and each test is rolled back. This is
intentional: the default local/production database must never become a test
fixture by accident.
"""
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# These must be set before pytest imports application modules. Do not point
# application settings at a developer database for tests.
TEST_ENV = {
    "SKIP_DB_INIT": "true",
    "DEBUG": "false",
    "ENVIRONMENT": "test",
    "ALLOW_ORIGINS": "http://localhost:8000",
    "ALLOW_METHODS": "GET,POST,PUT,PATCH,DELETE",
    "ALLOW_HEADERS": "Content-Type,Authorization,X-Tenant-ID,X-Signature",
    "SECRET_KEY": "test-secret-key-at-least-32-characters-long",
    "ALLOW_LEGACY_PAYMENT_SIMULATION": "false",
    "EASYTRANSACT_API_BASE_URL": "https://api.easytransact.test",
    "EASYTRANSACT_API_TOKEN": "test-api-token",
    "EASYTRANSACT_WEBHOOK_SECRET": "test-webhook-secret",
}
for _key, _value in TEST_ENV.items():
    os.environ[_key] = _value

# ``Settings`` declare ``env_file=".env"``. Sans correction, le .env du
# developpeur s'infiltre dans le singleton ``settings`` et la suite depend de la
# machine (les identifiants reels y ont ete observes). On desactive donc le
# chargement du fichier, puis on reconstruit le singleton : les variables
# d'environnement ci-dessus restent la seule source de configuration.
from app.core.config import Settings as _Settings  # noqa: E402
import app.core.config as _config  # noqa: E402

_Settings.model_config["env_file"] = None
_config._settings = _Settings()




def _set_rls_context(db: Session, *, user_id, tenant_id, is_platform_admin: bool) -> None:
    """Set transaction-local PostgreSQL variables used by the FORCE RLS policies."""
    db.execute(
        text("SELECT set_config('app.current_user_id', :user_id, true)"),
        {"user_id": str(user_id or "")},
    )
    db.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id or "")},
    )
    db.execute(
        text("SELECT set_config('app.is_platform_admin', :is_admin, true)"),
        {"is_admin": "true" if is_platform_admin else "false"},
    )


@pytest.fixture
def postgres_test_session():
    """Yield a real migrated PostgreSQL session scoped to one rolled-back transaction.

    There is intentionally no automatic fallback to DATABASE_URL: production
    safety outranks having tests appear green when a test database is absent.
    """
    database_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL/RLS integration tests.")

    # Imports intentionally occur after the test environment is pinned.
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.core.config import settings
    from app.models.user import User
    from app.schemas.restaurant import RestaurantCreate
    from app.services.restaurant_service import RestaurantService

    # Only an explicitly supplied test URL is ever used. This guard also makes
    # accidental reuse of DATABASE_URL impossible even if settings is imported.
    assert database_url != settings.DATABASE_URL, (
        "TEST_DATABASE_URL must be a separate database from the application database"
    )

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    connection = engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection, expire_on_commit=False)
    try:
        current_revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        expected_revision = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()
        if current_revision != expected_revision:
            pytest.skip(
                "PostgreSQL integration tests require Alembic head: "
                f"found={current_revision!r}, expected={expected_revision!r}."
            )

        # Seed an owner as the platform migration/admin role. A normal tenant
        # context is installed before the fixture is returned, so service code
        # is exercised under the same FORCE RLS policy as production traffic.
        _set_rls_context(db, user_id=None, tenant_id=None, is_platform_admin=True)
        owner = User(
            email=f"test-owner-{os.getpid()}-{id(db)}@example.invalid",
            phone=f"+2376{os.getpid() % 10_000_000:07d}",
            password_hash="not-used-in-integration-tests",
            first_name="Test",
            last_name="Owner",
            role="restaurant",
        )
        db.add(owner)
        db.flush()
        restaurant = RestaurantService(db).create_restaurant(
            restaurant_data=RestaurantCreate(
                name="Restaurant test isolé",
                currency="XAF",
                city="Douala",
                country="Cameroun",
            ),
            user_id=owner.id,
        )
        db.flush()
        _set_rls_context(db, user_id=owner.id, tenant_id=restaurant.id, is_platform_admin=False)

        yield {"db": db, "owner": owner, "restaurant": restaurant}
    finally:
        db.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
