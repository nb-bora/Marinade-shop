from typing import Optional, List
import re
import uuid

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate
from app.utils.logging import get_logger

logger = get_logger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def validate_email(email: str) -> bool:
    if not email or "@" not in email or ".." in email:
        return False
    local = email.split("@", 1)[0]
    if local.startswith(".") or local.endswith("."):
        return False
    return re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email) is not None


class UserService:
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)

    def get_user(self, user_id: uuid.UUID) -> Optional[User]:
        return self.user_repo.get(str(user_id))

    def get_user_by_email(self, email: str) -> Optional[User]:
        return self.user_repo.get_by_email(email)

    def get_all_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        return self.user_repo.get_all(skip, limit)

    def get_users_by_role(self, role: str, skip: int = 0, limit: int = 100) -> List[User]:
        return self.user_repo.get_by_role(role, skip, limit)

    def create_user(self, user_data: UserCreate) -> User:
        if self.user_repo.email_exists(user_data.email):
            raise ValueError("Email already registered")
        if self.user_repo.phone_exists(user_data.phone):
            raise ValueError("Phone number already registered")
        values = user_data.model_dump()
        values["password_hash"] = pwd_context.hash(values.pop("password"))
        return self.user_repo.create(values)

    def update_user(self, user_id: uuid.UUID, user_data: UserUpdate) -> Optional[User]:
        user = self.user_repo.get(str(user_id))
        if not user:
            return None
        values = user_data.model_dump(exclude_unset=True)
        if "email" in values and values["email"] != user.email and self.user_repo.email_exists(values["email"]):
            raise ValueError("Email already registered")
        if "phone" in values and values["phone"] != user.phone and self.user_repo.phone_exists(values["phone"]):
            raise ValueError("Phone number already registered")
        return self.user_repo.update(user, values)

    def delete_user(self, user_id: uuid.UUID) -> bool:
        return self.user_repo.delete(str(user_id)) is not None
