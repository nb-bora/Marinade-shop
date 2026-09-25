from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, db: Session):
        super().__init__(User, db)

    def get_by_email(self, email: str) -> Optional[User]:
        return self.db.query(User).filter(User.email == email).first()

    def get_by_phone(self, phone: str) -> Optional[User]:
        return self.db.query(User).filter(User.phone == phone).first()

    def get_by_role(self, role: str, skip: int = 0, limit: int = 100) -> List[User]:
        return (
            self.db.query(User)
            .filter(User.role == role)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def email_exists(self, email: str) -> bool:
        return self.db.query(User).filter(User.email == email).first() is not None

    def phone_exists(self, phone: str) -> bool:
        return self.db.query(User).filter(User.phone == phone).first() is not None

    def save_reset_token(
        self, user_id: str, token_hash: str, expires_at: datetime
    ) -> Optional[User]:
        user = self.get(user_id)
        if user:
            user.password_reset_token_hash = token_hash
            user.password_reset_expires_at = expires_at
            self.db.flush()
            self.db.refresh(user)
        return user

    def get_by_reset_token_hash(self, token_hash: str) -> Optional[User]:
        return (
            self.db.query(User)
            .filter(User.password_reset_token_hash == token_hash)
            .first()
        )

    def clear_reset_token(self, user_id: str) -> Optional[User]:
        user = self.get(user_id)
        if user:
            user.password_reset_token_hash = None
            user.password_reset_expires_at = None
            self.db.flush()
            self.db.refresh(user)
        return user

    def save_verification_token(
        self, user_id: str, token_hash: str, expires_at: datetime
    ) -> Optional[User]:
        user = self.get(user_id)
        if user:
            user.email_verification_token_hash = token_hash
            user.verification_token_expires_at = expires_at
            self.db.flush()
            self.db.refresh(user)
        return user

    def get_by_email_verified(
        self, verified: bool = True, skip: int = 0, limit: int = 100
    ) -> List[User]:
        query = self.db.query(User)
        if verified:
            query = query.filter(User.email_verified_at.isnot(None))
        else:
            query = query.filter(User.email_verified_at.is_(None))
        return query.offset(skip).limit(limit).all()

    def set_phone_verified(
        self, user_id: str, verified_at: Optional[datetime] = None
    ) -> Optional[User]:
        user = self.get(user_id)
        if user:
            user.phone_verified_at = verified_at or datetime.utcnow()
            self.db.flush()
            self.db.refresh(user)
        return user

    def save_2fa_secret(self, user_id: str, secret_hash: str) -> Optional[User]:
        user = self.get(user_id)
        if user:
            user.two_factor_secret_hash = secret_hash
            self.db.flush()
            self.db.refresh(user)
        return user

    def get_2fa_secret(self, user_id: str) -> Optional[str]:
        user = self.get(user_id)
        return user.two_factor_secret_hash if user else None

    def save_2fa_recovery_codes(
        self, user_id: str, recovery_codes: list
    ) -> Optional[User]:
        user = self.get(user_id)
        if user:
            user.two_factor_recovery_codes_jsonb = recovery_codes
            self.db.flush()
            self.db.refresh(user)
        return user

    def confirm_2fa_enabled(
        self, user_id: str, confirmed_at: Optional[datetime] = None
    ) -> Optional[User]:
        user = self.get(user_id)
        if user:
            user.two_factor_confirmed_at = confirmed_at or datetime.utcnow()
            self.db.flush()
            self.db.refresh(user)
        return user

    def disable_2fa(self, user_id: str) -> Optional[User]:
        user = self.get(user_id)
        if user:
            user.two_factor_secret_hash = None
            user.two_factor_recovery_codes_jsonb = None
            user.two_factor_confirmed_at = None
            self.db.flush()
            self.db.refresh(user)
        return user

    def get_by_email_verification_token_hash(self, token_hash: str) -> Optional[User]:
        return (
            self.db.query(User)
            .filter(User.email_verification_token_hash == token_hash)
            .first()
        )

    def save_phone_verification_code(
        self, user_id: str, code_hash: str, expires_at: datetime
    ) -> Optional[User]:
        user = self.get(user_id)
        if user:
            user.phone_verification_code_hash = code_hash
            user.verification_token_expires_at = expires_at
            self.db.flush()
            self.db.refresh(user)
        return user

    def clear_email_verification_token(self, user_id: str) -> Optional[User]:
        user = self.get(user_id)
        if user:
            user.email_verification_token_hash = None
            user.verification_token_expires_at = None
            self.db.flush()
            self.db.refresh(user)
        return user

    def clear_phone_verification_code(self, user_id: str) -> Optional[User]:
        user = self.get(user_id)
        if user:
            user.phone_verification_code_hash = None
            user.verification_token_expires_at = None
            self.db.flush()
            self.db.refresh(user)
        return user

    def get_2fa_recovery_codes(self, user_id: str) -> Optional[list]:
        user = self.get(user_id)
        return user.two_factor_recovery_codes_jsonb if user else None

    def set_email_verified(
        self, user_id: str, verified_at: Optional[datetime] = None
    ) -> Optional[User]:
        user = self.get(user_id)
        if user:
            user.email_verified_at = verified_at or datetime.utcnow()
            self.db.flush()
            self.db.refresh(user)
        return user
