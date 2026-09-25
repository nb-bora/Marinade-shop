import uuid
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Numeric,
    Text,
    Boolean,
    ForeignKey,
    Index,
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.core.database import Base
from app.utils.ros_enums import (
    CustomerType,
    SessionStatus,
    FulfillmentType,
    OrderChannel,
    RosOrderStatus,
    ProductionStation,
    TicketStatus,
    InvoiceStatus,
    RosPaymentMethod,
    CashShiftStatus,
)


class RosCustomer(Base):
    __tablename__ = "ros_customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_type = Column(String(20), default=CustomerType.GUEST.value, nullable=False)
    name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    preferences_jsonb = Column(JSONB, nullable=True)
    loyalty_points = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_ros_customer_restaurant", "restaurant_id"),
        Index("idx_ros_customer_type", "customer_type"),
    )


class ServiceSession(Base):
    __tablename__ = "service_sessions"

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
    table_context = Column(
        String(100), nullable=True
    )  # ex: 'Terrasse Gauche', 'Comptoir Bar', NULL
    status = Column(String(30), default=SessionStatus.OPEN.value, nullable=False)
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_service_session_restaurant", "restaurant_id"),
        Index("idx_service_session_status", "status"),
        Index("idx_service_session_table", "table_id"),
    )


class RosOrder(Base):
    __tablename__ = "ros_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("service_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    customer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ros_customers.id", ondelete="SET NULL"),
        nullable=True,
    )
    fulfillment_type = Column(
        String(30), default=FulfillmentType.DINE_IN.value, nullable=False
    )
    order_channel = Column(String(30), default=OrderChannel.POS.value, nullable=False)
    status = Column(String(30), default=RosOrderStatus.DRAFT.value, nullable=False)
    total_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    idempotency_key = Column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_ros_order_restaurant", "restaurant_id"),
        Index("idx_ros_order_session", "session_id"),
        Index("idx_ros_order_status", "status"),
        Index("idx_ros_order_idempotency", "idempotency_key", unique=True),
        CheckConstraint("total_amount >= 0", name="check_ros_order_total_positive"),
    )


class RosOrderItem(Base):
    __tablename__ = "ros_order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ros_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id = Column(UUID(as_uuid=True), nullable=True)
    product_name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    tax_rate = Column(Numeric(5, 2), default=19.25, nullable=False)
    destination_station = Column(
        String(30), default=ProductionStation.KITCHEN.value, nullable=False
    )
    notes = Column(Text, nullable=True)
    details_jsonb = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_ros_item_order", "order_id"),
        CheckConstraint("quantity > 0", name="check_ros_item_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="check_ros_item_price_positive"),
    )


class ProductionTicket(Base):
    __tablename__ = "production_tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ros_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    station = Column(
        String(30), default=ProductionStation.KITCHEN.value, nullable=False
    )
    status = Column(String(30), default=TicketStatus.QUEUED.value, nullable=False)
    items_jsonb = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    ready_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_prod_ticket_restaurant", "restaurant_id"),
        Index("idx_prod_ticket_order", "order_id"),
        Index("idx_prod_ticket_station", "station", "status"),
    )


class RosInvoice(Base):
    __tablename__ = "ros_invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("service_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ros_orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    invoice_number = Column(String(100), unique=True, nullable=False)
    subtotal = Column(Numeric(12, 2), nullable=False)
    tax_amount = Column(Numeric(12, 2), nullable=False)
    service_charge = Column(Numeric(12, 2), default=0.00, nullable=False)
    discount_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    total_amount = Column(Numeric(12, 2), nullable=False)
    amount_paid = Column(Numeric(12, 2), default=0.00, nullable=False)
    status = Column(String(30), default=InvoiceStatus.ISSUED.value, nullable=False)
    fiscal_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def amount_due(self):
        return (self.total_amount or Decimal("0.00")) - (
            self.amount_paid or Decimal("0.00")
        )

    __table_args__ = (
        Index("idx_ros_invoice_restaurant", "restaurant_id"),
        Index("idx_ros_invoice_session", "session_id"),
        Index("idx_ros_invoice_number", "invoice_number", unique=True),
        Index("idx_ros_invoice_status", "status"),
        CheckConstraint("total_amount >= 0", name="check_ros_invoice_total_positive"),
    )


class RosPaymentTransaction(Base):
    __tablename__ = "ros_payment_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    invoice_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ros_invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    payment_method = Column(String(30), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(30), default="SUCCEEDED", nullable=False)
    external_reference = Column(String(255), nullable=True)
    idempotency_key = Column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_ros_pay_restaurant", "restaurant_id"),
        Index("idx_ros_pay_invoice", "invoice_id"),
        Index("idx_ros_pay_idempotency", "idempotency_key", unique=True),
        CheckConstraint("amount > 0", name="check_ros_pay_amount_positive"),
    )


class RosCashShift(Base):
    __tablename__ = "ros_cash_shifts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    operator_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    opening_balance = Column(Numeric(12, 2), nullable=False)
    closing_balance_expected = Column(Numeric(12, 2), nullable=True)
    closing_balance_counted = Column(Numeric(12, 2), nullable=True)
    variance = Column(Numeric(12, 2), nullable=True)
    status = Column(String(20), default=CashShiftStatus.OPEN.value, nullable=False)
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_cash_shift_restaurant", "restaurant_id"),
        Index("idx_cash_shift_operator", "operator_user_id"),
        Index("idx_cash_shift_status", "status"),
        CheckConstraint(
            "opening_balance >= 0", name="check_cash_shift_opening_positive"
        ),
    )


class RosAuditLog(Base):
    __tablename__ = "ros_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action = Column(String(100), nullable=False)
    entity_name = Column(String(100), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    before_state = Column(JSONB, nullable=True)
    after_state = Column(JSONB, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_ros_audit_restaurant", "restaurant_id"),
        Index("idx_ros_audit_entity", "entity_name", "entity_id"),
    )
