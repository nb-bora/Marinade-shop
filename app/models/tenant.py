from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class RestaurantMember(Base):
    __tablename__ = "restaurant_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role = Column(String(30), nullable=False, default="staff")
    staff_role = Column(String(30), nullable=True)
    permissions_jsonb = Column(JSONB, nullable=True)
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
        UniqueConstraint("restaurant_id", "user_id", name="uq_restaurant_member"),
        CheckConstraint(
            "role IN ('owner', 'manager', 'cashier', 'kitchen', 'staff', 'waiter', 'chef', 'sous_chef', 'delivery', 'bartender', 'host')",
            name="check_restaurant_member_role",
        ),
        CheckConstraint(
            "staff_role IS NULL OR staff_role IN ('waiter', 'cashier', 'chef', 'sous_chef', 'manager', 'delivery', 'bartender', 'host')",
            name="check_restaurant_member_staff_role",
        ),
        Index("idx_restaurant_member_user", "user_id"),
        Index("idx_restaurant_member_staff_role", "restaurant_id", "staff_role"),
    )
