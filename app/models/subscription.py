from sqlalchemy import Column, Integer, String, DateTime, Date, Boolean, CheckConstraint, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base
import uuid


class SubscriptionTier(Base):
    __tablename__ = "subscription_tiers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    daily_limit_fcfa = Column(Integer, nullable=False)
    monthly_price_fcfa = Column(Integer, nullable=False)
    annual_price_fcfa = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    tier_id = Column(Integer, ForeignKey("subscription_tiers.id"), nullable=False)
    status = Column(String(20), nullable=False)  # Validation: 'pending', 'active', 'suspended', 'cancelled', 'expired'
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="check_end_date_after_start"),
        Index("idx_active_subscription_per_user", "user_id", unique=True, postgresql_where=(status == "active")),
    )


class DailyBalance(Base):
    __tablename__ = "daily_balances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=False)
    balance_date = Column(Date, nullable=False)
    initial_balance_fcfa = Column(Integer, nullable=False)
    used_balance_fcfa = Column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("initial_balance_fcfa > 0", name="check_initial_balance_positive"),
        CheckConstraint("used_balance_fcfa >= 0", name="check_used_balance_non_negative"),
        CheckConstraint("used_balance_fcfa <= initial_balance_fcfa", name="check_used_balance_within_limit"),
        Index("uq_subscription_balance", "subscription_id", "balance_date", unique=True),
    )