from typing import Optional, Any


class MarinadeException(Exception):
    """Base exception for Marinade application"""

    def __init__(self, message: str, details: Optional[Any] = None):
        self.message = message
        self.details = details
        super().__init__(self.message)


class AuthenticationError(MarinadeException):
    """Authentication related errors"""

    pass


class AuthorizationError(MarinadeException):
    """Authorization related errors"""

    pass


class ValidationError(MarinadeException):
    """Validation errors"""

    pass


class NotFoundError(MarinadeException):
    """Resource not found errors"""

    pass


class ConflictError(MarinadeException):
    """Resource conflict errors (duplicates, etc.)"""

    pass


class BusinessLogicError(MarinadeException):
    """Business logic errors"""

    pass


class DatabaseError(MarinadeException):
    """Database related errors"""

    pass
