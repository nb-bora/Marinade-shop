import os
import sys

os.environ["SKIP_DB_INIT"] = "true"
os.environ["DEBUG"] = "false"
os.environ["ALLOW_ORIGINS"] = "http://localhost:8000"
os.environ["ALLOW_METHODS"] = "GET,POST,PUT,DELETE"
os.environ["ALLOW_HEADERS"] = "Content-Type,Authorization,X-Tenant-ID"
os.environ["DB_HOST"] = "localhost"
os.environ["DB_PORT"] = "5432"
os.environ["DB_NAME"] = "marinade"
os.environ["DB_USER"] = "postgres"
os.environ["DB_PASSWORD"] = "postgres"
os.environ["DB_SSLMODE"] = "disable"


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
    assert settings.DB_HOST == "localhost"
    assert settings.DB_PORT == 5432
    assert settings.DB_NAME == "marinade"
    assert settings.DB_USER == "postgres"
    assert settings.DB_PASSWORD == "postgres"
    assert settings.DATABASE_URL.endswith("?sslmode=disable")


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
    for exception_type in (AuthenticationError, AuthorizationError, ValidationError, NotFoundError, ConflictError, BusinessLogicError, DatabaseError):
        assert issubclass(exception_type, MarinadeException)

