from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    phone = Column(String(20), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    role = Column(String(30), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    phone_verified_at = Column(DateTime(timezone=True), nullable=True)
    email_verification_token_hash = Column(String(256), nullable=True)
    phone_verification_code_hash = Column(String(256), nullable=True)
    verification_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    password_reset_token_hash = Column(String(256), nullable=True)
    password_reset_expires_at = Column(DateTime(timezone=True), nullable=True)
    two_factor_secret_hash = Column(String(256), nullable=True)
    two_factor_recovery_codes_jsonb = Column(JSONB, nullable=True)
    two_factor_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'pos', 'restaurant', 'waiter', 'cashier', 'chef', 'manager', 'delivery')",
            name="check_role_valid",
        ),
        CheckConstraint(
            "(is_deleted = false AND deleted_at IS NULL) OR (is_deleted = true AND deleted_at IS NOT NULL)",
            name="check_user_deleted_consistency",
        ),
    )
