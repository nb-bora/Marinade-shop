from datetime import datetime, timedelta, timezone
from typing import Optional
import hashlib
import secrets
import uuid

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User
from app.repositories.transaction_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserLogin
from app.utils.exceptions import AuthenticationError, ConflictError, ValidationError
from app.utils.logging import get_logger

logger = get_logger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def validate_email(email: str) -> bool:
    if not email or "@" not in email or ".." in email:
        return False
    local_part = email.split("@", 1)[0]
    if local_part.startswith(".") or local_part.endswith("."):
        return False
    return re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email) is not None


# Kept local to avoid importing re at module initialization in older tooling.
import re


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
        now = datetime.now(timezone.utc)
        claims = {**data, "type": "access", "iat": now, "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)}
        return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    @staticmethod
    def _hash_refresh_token(token: str) -> str:
        # Bcrypt salts every hash, so it cannot be used to look up a token by
        # digest. Refresh tokens are high-entropy random values; a keyed digest
        # is deterministic and safe for indexed lookup.
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_refresh_token(self, user_id: uuid.UUID) -> str:
        token = secrets.token_urlsafe(48)
        self.refresh_token_repo.create({
            "user_id": user_id,
            "token_hash": self._hash_refresh_token(token),
            "expires_at": datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        })
        return token

    def register_user(self, user_data: UserCreate) -> User:
        if not validate_email(user_data.email):
            raise ValidationError("Invalid email format")
        if self.user_repo.email_exists(user_data.email):
            raise ConflictError("Email already registered")
        if self.user_repo.phone_exists(user_data.phone):
            raise ConflictError("Phone number already registered")

        values = user_data.model_dump()
        values["role"] = "restaurant"
        values["password_hash"] = self.get_password_hash(values.pop("password"))
        return self.user_repo.create(values)

    def authenticate_user(self, login_data: UserLogin) -> User:
        if not validate_email(login_data.email):
            raise AuthenticationError("Invalid credentials")
        user = self.user_repo.get_by_email(login_data.email)
        if not user or not user.is_active or not self.verify_password(login_data.password, user.password_hash):
            raise AuthenticationError("Invalid credentials")
        return user

    def refresh_access_token(self, refresh_token: str) -> Optional[str]:
        token_obj = self.refresh_token_repo.get_by_token_hash(self._hash_refresh_token(refresh_token))
        if not token_obj:
            return None
        expires_at = token_obj.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return None
        user = self.user_repo.get(token_obj.user_id)
        if not user or not user.is_active:
            return None
        return self.create_access_token({"sub": str(user.id)})

    def rotate_refresh_token(self, refresh_token: str) -> Optional[tuple[str, str]]:
        token_obj = self.refresh_token_repo.get_by_token_hash(self._hash_refresh_token(refresh_token))
        if not token_obj:
            return None
        expires_at = token_obj.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return None
        user = self.user_repo.get(token_obj.user_id)
        if not user or not user.is_active:
            return None
        new_refresh = self.create_refresh_token(user.id)
        self.refresh_token_repo.delete(token_obj.id)
        return self.create_access_token({"sub": str(user.id)}), new_refresh

    def logout_user(self, user_id: uuid.UUID) -> bool:
        self.refresh_token_repo.delete_by_user_id(user_id)
        return True
