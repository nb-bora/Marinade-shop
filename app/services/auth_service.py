from typing import Optional
from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.repositories.user_repository import UserRepository
from app.repositories.transaction_repository import RefreshTokenRepository
from app.schemas.user import UserCreate, UserLogin
from app.models.user import User
from app.core.config import settings
from app.utils.logging import get_logger
from app.utils.exceptions import AuthenticationError, ValidationError, ConflictError
import uuid
import secrets
import re

logger = get_logger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def validate_email(email: str) -> bool:
    # Basic email validation with additional checks
    if not email or '@' not in email:
        return False

    # Check for consecutive dots
    if '..' in email:
        return False

    # Check for dot at beginning or end of local part
    local_part = email.split('@')[0]
    if local_part.startswith('.') or local_part.endswith('.'):
        return False

    # Basic regex pattern
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(pattern, email) is not None


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)
        self.refresh_token_repo = RefreshTokenRepository(db)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        return pwd_context.hash(password)

    def create_access_token(self, data: dict) -> str:
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        return encoded_jwt

    def create_refresh_token(self, user_id: uuid.UUID) -> str:
        refresh_token = secrets.token_urlsafe(32)
        token_hash = self.get_password_hash(refresh_token)
        expires_at = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        self.refresh_token_repo.create({
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at
        })

        return refresh_token

    def register_user(self, user_data: UserCreate) -> User:
        if not validate_email(user_data.email):
            logger.warning(f"Invalid email format during registration: {user_data.email}")
            raise ValidationError("Invalid email format")

        if self.user_repo.email_exists(user_data.email):
            logger.warning(f"Email already registered: {user_data.email}")
            raise ConflictError("Email already registered")
        if self.user_repo.phone_exists(user_data.phone):
            logger.warning(f"Phone number already registered: {user_data.phone}")
            raise ConflictError("Phone number already registered")

        user_dict = user_data.model_dump()
        user_dict["password_hash"] = self.get_password_hash(user_dict.pop("password"))

        user = self.user_repo.create(user_dict)
        logger.info(f"User registered successfully: {user.id}")
        return user

    def authenticate_user(self, login_data: UserLogin) -> Optional[User]:
        if not validate_email(login_data.email):
            raise ValidationError("Invalid email format")

        user = self.user_repo.get_by_email(login_data.email)
        if not user:
            raise AuthenticationError("Invalid credentials")
        if not self.verify_password(login_data.password, user.password_hash):
            raise AuthenticationError("Invalid credentials")
        return user

    def refresh_access_token(self, refresh_token: str) -> Optional[str]:
        token_hash = self.get_password_hash(refresh_token)
        refresh_token_obj = self.refresh_token_repo.get_by_token_hash(token_hash)

        if not refresh_token_obj:
            return None

        if refresh_token_obj.expires_at < datetime.utcnow():
            return None

        access_token = self.create_access_token({"sub": str(refresh_token_obj.user_id)})
        return access_token

    def logout_user(self, user_id: uuid.UUID) -> bool:
        self.refresh_token_repo.delete_by_user_id(user_id)
        return True
