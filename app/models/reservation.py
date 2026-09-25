import uuid
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    ForeignKey,
    Index,
    CheckConstraint,
    UniqueConstraint,
    Text,
    Numeric,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.core.database import Base
from app.utils.enums import ReservationStatus


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ros_customers.id", ondelete="SET NULL"),
        nullable=True,
    )
    table_id = Column(
        UUID(as_uuid=True), ForeignKey("tables.id", ondelete="SET NULL"), nullable=True
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("service_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    customer_name = Column(String(255), nullable=False)
    customer_phone = Column(String(50), nullable=True)
    customer_email = Column(String(255), nullable=True)

    status = Column(String(30), default=ReservationStatus.PENDING.value, nullable=False)
    party_size = Column(Integer, nullable=False)
    reservation_date = Column(DateTime(timezone=True), nullable=False)
    duration_minutes = Column(Integer, default=90, nullable=False)

    notes = Column(Text, nullable=True)
    source = Column(String(30), default="POS", nullable=False)
    reminder_sent = Column(Boolean, default=False, nullable=False)
    arrival_notes = Column(String(255), nullable=True)
    preferences_jsonb = Column(JSONB, nullable=True)

    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    checked_in_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancel_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_reservation_restaurant", "restaurant_id"),
        Index("idx_reservation_table", "table_id"),
        Index("idx_reservation_status", "status"),
        Index("idx_reservation_date", "restaurant_id", "reservation_date"),
        Index("idx_reservation_customer", "customer_phone", "customer_email"),
        CheckConstraint("party_size > 0", name="check_reservation_party_size_positive"),
        CheckConstraint(
            "duration_minutes > 0", name="check_reservation_duration_positive"
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'checked_in', 'completed', 'cancelled', 'no_show')",
            name="check_reservation_status_valid",
        ),
    )


class ReservationGuest(Base):
    __tablename__ = "reservation_guests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reservation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reservations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=True)
    age_category = Column(String(20), nullable=True)
    is_vegetarian = Column(Boolean, default=False, nullable=False)
    allergenes = Column(JSONB, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_reservation_guest_reservation", "reservation_id"),)


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_name = Column(String(255), nullable=False)
    customer_phone = Column(String(50), nullable=True)
    customer_email = Column(String(255), nullable=True)
    party_size = Column(Integer, nullable=False)
    requested_table_id = Column(
        UUID(as_uuid=True), ForeignKey("tables.id", ondelete="SET NULL"), nullable=True
    )
    assigned_table_id = Column(
        UUID(as_uuid=True), ForeignKey("tables.id", ondelete="SET NULL"), nullable=True
    )
    position = Column(Integer, nullable=False)
    estimated_wait_minutes = Column(Integer, nullable=True)
    status = Column(String(30), default="WAITING", nullable=False)
    source = Column(String(30), default="POS", nullable=False)
    notes = Column(Text, nullable=True)
    preferences_jsonb = Column(JSONB, nullable=True)
    joined_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    seated_at = Column(DateTime(timezone=True), nullable=True)
    expired_at = Column(DateTime(timezone=True), nullable=True)
    removed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_waitlist_restaurant", "restaurant_id"),
        Index("idx_waitlist_status_position", "restaurant_id", "status", "position"),
        Index("idx_waitlist_customer", "customer_phone"),
        CheckConstraint("party_size > 0", name="check_waitlist_party_size_positive"),
        CheckConstraint("position > 0", name="check_waitlist_position_positive"),
        CheckConstraint(
            "status IN ('WAITING', 'SEATED', 'EXPIRED', 'REMOVED', 'CANCELLED')",
            name="check_waitlist_status_valid",
        ),
    )
