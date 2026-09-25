from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class MobileOperatorPrefix(Base):
    __tablename__ = "mobile_operator_prefixes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    country_code = Column(
        String(4), nullable=False, default="+237", server_default="+237"
    )
    operator_code = Column(String(30), nullable=False)
    operator_name = Column(String(100), nullable=False)
    national_prefix = Column(String(4), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
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
        UniqueConstraint(
            "country_code", "national_prefix", name="uq_mobile_operator_prefix"
        ),
        CheckConstraint(
            "national_prefix ~ '^[0-9]{2,4}$'", name="check_mobile_prefix_digits"
        ),
        Index(
            "idx_mobile_operator_prefix_lookup",
            "country_code",
            "national_prefix",
            "is_active",
        ),
    )
