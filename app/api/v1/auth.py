from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services.auth_service import AuthService
from app.schemas.user import UserCreate, UserLogin, UserResponse
from app.schemas.transaction import TokenResponse
from app.api.dependencies import get_current_user
from app.utils.exceptions import ValidationError, ConflictError, AuthenticationError
import uuid

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    auth_service = AuthService(db)
    try:
        user = auth_service.register_user(user_data)
        return user
    except (ValidationError, ConflictError):
        raise  # Let the exception handler handle this


@router.post("/login", response_model=TokenResponse)
def login(login_data: UserLogin, db: Session = Depends(get_db)):
    auth_service = AuthService(db)
    try:
        user = auth_service.authenticate_user(login_data)
    except AuthenticationError:
        raise  # Let the exception handler handle this

    access_token = auth_service.create_access_token({"sub": str(user.id)})
    refresh_token = auth_service.create_refresh_token(user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(refresh_token: str, db: Session = Depends(get_db)):
    auth_service = AuthService(db)
    access_token = auth_service.refresh_access_token(refresh_token)

    if not access_token:
        raise AuthenticationError("Invalid or expired refresh token")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token
    )


@router.post("/logout")
def logout(current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    auth_service = AuthService(db)
    auth_service.logout_user(current_user.id)
    return {"message": "Successfully logged out"}
