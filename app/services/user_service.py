from typing import Optional, List
from sqlalchemy.orm import Session
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate
from app.models.user import User
from app.utils.logging import get_logger
import uuid
import re

logger = get_logger(__name__)


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
        if not validate_email(user_data.email):
            logger.warning(f"Invalid email format: {user_data.email}")
            raise ValueError("Invalid email format")

        if self.user_repo.email_exists(user_data.email):
            logger.warning(f"Email already registered: {user_data.email}")
            raise ValueError("Email already registered")
        if self.user_repo.phone_exists(user_data.phone):
            logger.warning(f"Phone number already registered: {user_data.phone}")
            raise ValueError("Phone number already registered")

        user_dict = user_data.model_dump()
        # Password hashing should be handled by auth service
        user = self.user_repo.create(user_dict)
        logger.info(f"User created successfully: {user.id}")
        return user

    def update_user(self, user_id: uuid.UUID, user_data: UserUpdate) -> Optional[User]:
        user = self.user_repo.get(str(user_id))
        if not user:
            logger.warning(f"User not found for update: {user_id}")
            return None

        update_dict = user_data.model_dump(exclude_unset=True)

        # Check email uniqueness if being updated
        if "email" in update_dict:
            if not validate_email(update_dict["email"]):
                logger.warning(f"Invalid email format during update: {update_dict['email']}")
                raise ValueError("Invalid email format")
            if update_dict["email"] != user.email:
                if self.user_repo.email_exists(update_dict["email"]):
                    logger.warning(f"Email already registered: {update_dict['email']}")
                    raise ValueError("Email already registered")

        # Check phone uniqueness if being updated
        if "phone" in update_dict and update_dict["phone"] != user.phone:
            if self.user_repo.phone_exists(update_dict["phone"]):
                logger.warning(f"Phone number already registered: {update_dict['phone']}")
                raise ValueError("Phone number already registered")

        updated_user = self.user_repo.update(user, update_dict)
        logger.info(f"User updated successfully: {user_id}")
        return updated_user

    def delete_user(self, user_id: uuid.UUID) -> bool:
        user = self.user_repo.delete(str(user_id))
        return user is not None
