from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.schemas.transaction import TokenResponse
from app.schemas.user import UserCreate, UserLogin, UserResponse
from app.services.auth_service import AuthService
from app.utils.exceptions import AuthenticationError, ConflictError, ValidationError

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED, tags=["authentication"])
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    return AuthService(db).register_user(user_data)


@router.post("/login", response_model=TokenResponse, tags=["authentication"])
def login(login_data: UserLogin, db: Session = Depends(get_db)):
    service = AuthService(db)
    user = service.authenticate_user(login_data)
    return TokenResponse(
        access_token=service.create_access_token({"sub": str(user.id)}),
        refresh_token=service.create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenResponse, tags=["authentication"])
def refresh(refresh_token: str, db: Session = Depends(get_db)):
    rotated = AuthService(db).rotate_refresh_token(refresh_token)
    if not rotated:
        raise AuthenticationError("Invalid or expired refresh token")
    access_token, new_refresh_token = rotated
    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", tags=["authentication"])
def logout(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    AuthService(db).logout_user(current_user.id)
    return {"message": "Successfully logged out"}
