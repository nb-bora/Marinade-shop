import os
import sys

# Set environment variables before any imports
os.environ["SKIP_DB_INIT"] = "true"
os.environ["DEBUG"] = "false"

# Set a simple ALLOW_ORIGINS value to avoid parsing issues
os.environ["ALLOW_ORIGINS"] = "http://localhost:8000"
os.environ["ALLOW_METHODS"] = "GET,POST,PUT,DELETE"
os.environ["ALLOW_HEADERS"] = "Content-Type,Authorization"

# Set database configuration
os.environ["DB_HOST"] = "localhost"
os.environ["DB_PORT"] = "5432"
os.environ["DB_NAME"] = "marinade"
os.environ["DB_USER"] = "postgres"
os.environ["DB_PASSWORD"] = "postgres"


def test_app_imports():
    """Test that the app can be imported without errors"""
    from app.main import app
    assert app is not None
    assert app.title == "Marinade API"


def test_app_routes():
    """Test that the app has the expected routes"""
    from app.main import app
    routes = [route.path for route in app.routes]
    assert "/" in routes
    assert "/health" in routes
    # Check that API routes are present
    api_routes = [route for route in routes if route.startswith("/v1")]
    assert len(api_routes) > 0, "No API routes found"


def test_email_validation():
    """Test email validation function"""
    from app.services.user_service import validate_email

    # Valid emails
    assert validate_email("test@example.com") == True
    assert validate_email("user.name@domain.co.uk") == True
    assert validate_email("user+tag@example.org") == True
    assert validate_email("user%test@example.com") == True

    # Invalid emails
    assert validate_email("invalid") == False
    assert validate_email("invalid@") == False
    assert validate_email("@example.com") == False
    assert validate_email("invalid..email@example.com") == False
    assert validate_email("user@.com") == False
    assert validate_email(".user@example.com") == False
    assert validate_email("user.@example.com") == False


def test_config_loading():
    """Test that configuration loads correctly"""
    from app.core.config import settings

    assert settings.APP_NAME == "Marinade API"
    assert settings.APP_VERSION == "1.0.0"
    assert settings.DATABASE_URL is not None
    assert settings.SECRET_KEY is not None

    # Test segmented database configuration
    assert settings.DB_HOST == "localhost"
    assert settings.DB_PORT == 5432
    assert settings.DB_NAME == "marinade"
    assert settings.DB_USER == "postgres"
    assert settings.DB_PASSWORD == "postgres"

    # Test that DATABASE_URL is built correctly
    expected_url = "postgresql://postgres:postgres@localhost:5432/marinade"
    assert settings.DATABASE_URL == expected_url


def test_exception_hierarchy():
    """Test that custom exceptions are properly defined"""
    from app.utils.exceptions import (
        MarinadeException,
        AuthenticationError,
        AuthorizationError,
        ValidationError,
        NotFoundError,
        ConflictError,
        BusinessLogicError,
        DatabaseError
    )

    # Test exception creation
    exc = MarinadeException("Test message")
    assert exc.message == "Test message"
    assert exc.details is None

    exc_with_details = MarinadeException("Test", details={"key": "value"})
    assert exc_with_details.details == {"key": "value"}

    # Test inheritance
    assert issubclass(AuthenticationError, MarinadeException)
    assert issubclass(AuthorizationError, MarinadeException)
    assert issubclass(ValidationError, MarinadeException)
    assert issubclass(NotFoundError, MarinadeException)
    assert issubclass(ConflictError, MarinadeException)
    assert issubclass(BusinessLogicError, MarinadeException)
    assert issubclass(DatabaseError, MarinadeException)


def test_schemas_validation():
    """Test that Pydantic schemas validate correctly"""
    from app.schemas.user import UserCreate, UserUpdate, UserLogin
    from pydantic import ValidationError as PydanticValidationError

    # Valid user creation
    valid_user = UserCreate(
        email="test@example.com",
        phone="1234567890",
        first_name="John",
        last_name="Doe",
        password="SecurePass123",
        role="admin"
    )
    assert valid_user.email == "test@example.com"

    # Invalid email
    try:
        UserCreate(
            email="invalid",
            phone="1234567890",
            first_name="John",
            last_name="Doe",
            password="SecurePass123",
            role="admin"
        )
        assert False, "Should have raised validation error"
    except PydanticValidationError:
        pass

    # Invalid email (double dots)
    try:
        UserCreate(
            email="invalid..email@example.com",
            phone="1234567890",
            first_name="John",
            last_name="Doe",
            password="SecurePass123",
            role="admin"
        )
        assert False, "Should have raised validation error"
    except PydanticValidationError:
        pass

    # Invalid email (dot at beginning)
    try:
        UserCreate(
            email=".user@example.com",
            phone="1234567890",
            first_name="John",
            last_name="Doe",
            password="SecurePass123",
            role="admin"
        )
        assert False, "Should have raised validation error"
    except PydanticValidationError:
        pass

    # Invalid email (dot at end)
    try:
        UserCreate(
            email="user.@example.com",
            phone="1234567890",
            first_name="John",
            last_name="Doe",
            password="SecurePass123",
            role="admin"
        )
        assert False, "Should have raised validation error"
    except PydanticValidationError:
        pass

    # Invalid role
    try:
        UserCreate(
            email="test@example.com",
            phone="1234567890",
            first_name="John",
            last_name="Doe",
            password="SecurePass123",
            role="invalid_role"
        )
        assert False, "Should have raised validation error"
    except PydanticValidationError:
        pass

    # Valid user update (all fields optional)
    valid_update = UserUpdate()
    assert valid_update.email is None

    # Valid partial update
    partial_update = UserUpdate(first_name="Jane")
    assert partial_update.first_name == "Jane"
    assert partial_update.email is None


def test_subscription_schemas():
    """Test subscription schemas validation"""
    from app.schemas.subscription import SubscriptionTierCreate, SubscriptionCreate
    from pydantic import ValidationError as PydanticValidationError
    import uuid

    # Valid tier creation
    valid_tier = SubscriptionTierCreate(
        name="Basic",
        daily_limit_fcfa=10000,
        monthly_price_fcfa=50000,
        annual_price_fcfa=500000
    )
    assert valid_tier.name == "Basic"

    # Invalid (negative values)
    try:
        SubscriptionTierCreate(
            name="Basic",
            daily_limit_fcfa=-1000,
            monthly_price_fcfa=50000,
            annual_price_fcfa=500000
        )
        assert False, "Should have raised validation error"
    except PydanticValidationError:
        pass

    # Valid subscription creation
    valid_subscription = SubscriptionCreate(
        user_id=uuid.uuid4(),
        tier_id=1,
        status="active",
        start_date="2024-01-01"
    )
    assert valid_subscription.status == "active"

    # Invalid status
    try:
        SubscriptionCreate(
            user_id=uuid.uuid4(),
            tier_id=1,
            status="invalid_status",
            start_date="2024-01-01"
        )
        assert False, "Should have raised validation error"
    except PydanticValidationError:
        pass
