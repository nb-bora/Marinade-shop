import os
import sys

# L'environnement de test est épinglé dans tests/conftest.py, avant tout import
# applicatif. Ne pas le redéfinir ici : app.core.config expose un singleton
# ``settings`` évalué au premier import, donc une variable définie dans ce
# module arriverait trop tard pour avoir le moindre effet.


def test_app_imports():
    from app.main import app

    assert app is not None
    assert app.title == "Marinade API"


def test_app_routes():
    from app.main import app

    routes = [route.path for route in app.routes]
    assert "" in routes
    assert "/health" in routes
    assert len([route for route in routes if route.startswith("/v1")]) > 0


def test_email_validation():
    from app.services.user_service import validate_email

    assert validate_email("test@example.com") is True
    assert validate_email("user.name@domain.co.uk") is True
    assert validate_email("user+tag@example.org") is True
    assert validate_email("user%test@example.com") is True
    assert validate_email("invalid") is False
    assert validate_email("invalid@") is False
    assert validate_email("@example.com") is False
    assert validate_email("invalid..email@example.com") is False
    assert validate_email("user@.com") is False
    assert validate_email(".user@example.com") is False
    assert validate_email("user.@example.com") is False


def test_config_loading():
    from app.core.config import settings

    assert settings.APP_NAME == "Marinade API"
    assert settings.APP_VERSION == "1.0.0"
    assert settings.DATABASE_URL.startswith("postgresql://")
    assert settings.SECRET_KEY is not None


def test_database_url_is_built_from_parts():
    """DATABASE_URL doit être dérivé des variables, pas figé dans un test."""
    from app.core.config import Settings

    settings = Settings(
        DB_HOST="db.example.test",
        DB_PORT=6543,
        DB_NAME="marinade_test",
        DB_USER="marinade_rw",
        DB_PASSWORD="p@ss word",
        DB_SSLMODE="require",
    )
    assert settings.DATABASE_URL == (
        "postgresql://marinade_rw:p%40ss+word@db.example.test:6543/marinade_test?sslmode=require"
    )


def test_cors_lists_are_parsed():
    from app.core.config import Settings

    settings = Settings(
        ALLOW_ORIGINS="http://a.test, http://b.test",
        ALLOW_METHODS="get,post",
        ALLOW_HEADERS="Authorization, X-Tenant-ID",
    )
    assert settings.cors_origins == ["http://a.test", "http://b.test"]
    assert settings.cors_methods == ["GET", "POST"]
    assert settings.cors_headers == ["Authorization", "X-Tenant-ID"]


def test_test_environment_never_targets_developer_database():
    """Invariant du conftest : la suite ne doit viser aucune base de développement."""
    from app.core.config import settings

    assert settings.SKIP_DB_INIT is True
    assert settings.ENVIRONMENT == "test"
    assert settings.DEBUG is False
    assert settings.ALLOW_LEGACY_PAYMENT_SIMULATION is False


def test_dotenv_is_not_loaded_during_tests(monkeypatch):
    """Le .env du développeur ne doit pas s'infiltrer dans la configuration."""
    from app.core.config import Settings, settings

    assert Settings.model_config["env_file"] is None, (
        "conftest.py doit désactiver env_file pour rendre la suite déterministe"
    )
    # Une nouvelle instance ne doit donc pas non plus lire le fichier.
    fresh = Settings()
    assert fresh.DB_USER != "fairfairehq"
    assert fresh.SECRET_KEY == "test-secret-key-at-least-32-characters-long"
    assert settings is not None


def test_exception_hierarchy():
    from app.utils.exceptions import (
        MarinadeException,
        AuthenticationError,
        AuthorizationError,
        ValidationError,
        NotFoundError,
        ConflictError,
        BusinessLogicError,
        DatabaseError,
    )

    exc = MarinadeException("Test message")
    assert exc.message == "Test message"
    assert exc.details is None
    for exception_type in (
        AuthenticationError,
        AuthorizationError,
        ValidationError,
        NotFoundError,
        ConflictError,
        BusinessLogicError,
        DatabaseError,
    ):
        assert issubclass(exception_type, MarinadeException)
