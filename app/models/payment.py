from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class PaymentConfiguration(Base):
    __tablename__ = "payment_configurations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(30), nullable=False, default="easytransact")
    service_code = Column(String(50), nullable=False, default="DEPOSIT")
    webhook_url = Column(String(500), nullable=True)
    success_url = Column(String(500), nullable=True)
    failure_url = Column(String(500), nullable=True)
    vendor_reference_prefix = Column(String(30), nullable=False, default="MRD")
    provider_account_ref = Column(String(255), nullable=True)
    credential_env_key = Column(String(255), nullable=False, server_default="EASYTRANSACT_API_TOKEN")
    webhook_secret_env_key = Column(String(255), nullable=False, server_default="EASYTRANSACT_WEBHOOK_SECRET")
    webhook_token_hash = Column(String(64), unique=True, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("restaurant_id", "provider", name="uq_restaurant_payment_provider"),
        CheckConstraint("service_code <> ''", name="check_payment_service_code"),
    )


class PaymentIntent(Base):
    __tablename__ = "payment_intents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="RESTRICT"), nullable=False)
    commande_id = Column(UUID(as_uuid=True), ForeignKey("commandes.id", ondelete="RESTRICT"), nullable=True)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=True)
    provider = Column(String(30), nullable=False, default="easytransact")
    vendor_reference = Column(String(100), nullable=False)
    provider_transaction_id = Column(String(255), nullable=True)
    idempotency_key = Column(String(120), nullable=False)
    amount_fcfa = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default="XAF")
    status = Column(String(30), nullable=False, default="initiated")
    checkout_url = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    metadata_jsonb = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("vendor_reference", name="uq_payment_vendor_reference"),
        UniqueConstraint("restaurant_id", "idempotency_key", name="uq_payment_tenant_idempotency"),
        CheckConstraint("amount_fcfa > 0", name="check_payment_amount_positive"),
        CheckConstraint("status IN ('initiated', 'pending', 'processing', 'success', 'failed', 'timeout', 'reversed', 'refunded', 'expired', 'manual_review')", name="check_payment_status"),
        Index("idx_payment_intent_restaurant_status", "restaurant_id", "status"),
        Index("idx_payment_intent_commande", "commande_id"),
    )


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_intent_id = Column(UUID(as_uuid=True), ForeignKey("payment_intents.id", ondelete="CASCADE"), nullable=False)
    provider_event_id = Column(String(255), nullable=False)
    provider_status = Column(String(30), nullable=False)
    raw_payload = Column(JSONB, nullable=True)
    signature = Column(String(512), nullable=True)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("provider_event_id", name="uq_payment_event_provider_id"),
        Index("idx_payment_event_intent", "payment_intent_id", "received_at"),
    )


class PaymentLedgerEntry(Base):
    __tablename__ = "payment_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_intent_id = Column(UUID(as_uuid=True), ForeignKey("payment_intents.id", ondelete="RESTRICT"), nullable=False)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="RESTRICT"), nullable=False)
    entry_type = Column(String(30), nullable=False)
    amount_fcfa = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default="XAF")
    idempotency_key = Column(String(120), nullable=False)
    reference = Column(String(255), nullable=True)
    metadata_jsonb = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_payment_ledger_idempotency"),
        CheckConstraint("entry_type IN ('authorization', 'capture', 'reversal', 'refund', 'fee', 'manual_adjustment')", name="check_payment_ledger_entry_type"),
        CheckConstraint("amount_fcfa <> 0", name="check_payment_ledger_amount_nonzero"),
        Index("idx_payment_ledger_restaurant_created", "restaurant_id", "created_at"),
    )
