from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
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
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def marinade_exception_handler(request: Request, exc: MarinadeException):
    """Handler for custom Marinade exceptions"""
    logger.error(f"Marinade exception: {exc.message}", extra={"details": exc.details})

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    if isinstance(exc, AuthenticationError):
        status_code = status.HTTP_401_UNAUTHORIZED
    elif isinstance(exc, AuthorizationError):
        status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, ValidationError):
        status_code = status.HTTP_400_BAD_REQUEST
    elif isinstance(exc, NotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, ConflictError):
        status_code = status.HTTP_409_CONFLICT
    elif isinstance(exc, BusinessLogicError):
        status_code = status.HTTP_400_BAD_REQUEST
    elif isinstance(exc, DatabaseError):
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    return JSONResponse(
        status_code=status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "details": exc.details
        }
    )


async def general_exception_handler(request: Request, exc: Exception):
    """Handler for general exceptions"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred"
        }
    )
