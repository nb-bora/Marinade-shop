"""Add ROS Engine Tables (Customers, Sessions, Orders, Invoices, Payments, Shifts, Tickets, Audit)

Revision ID: 20260925_1600
Revises: 20260924_1200
Create Date: 2026-09-25 16:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260925_1600"
down_revision = "20260924_1200"
branch_labels = None
depends_on = None


def upgrade():
    # 1. ROS CUSTOMERS
    op.create_table(
        "ros_customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_type",
            sa.String(length=20),
            nullable=False,
            server_default="GUEST",
        ),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column(
            "preferences_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("loyalty_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("idx_ros_customer_restaurant", "ros_customers", ["restaurant_id"])
    op.create_index("idx_ros_customer_type", "ros_customers", ["customer_type"])

    # 2. SERVICE SESSIONS
    op.create_table(
        "service_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ros_customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "table_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tables.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("table_context", sa.String(length=100), nullable=True),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default="OPEN"
        ),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_service_session_restaurant", "service_sessions", ["restaurant_id"]
    )
    op.create_index("idx_service_session_status", "service_sessions", ["status"])
    op.create_index("idx_service_session_table", "service_sessions", ["table_id"])

    # 3. ROS ORDERS
    op.create_table(
        "ros_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("service_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ros_customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "fulfillment_type",
            sa.String(length=30),
            nullable=False,
            server_default="DINE_IN",
        ),
        sa.Column(
            "order_channel", sa.String(length=30), nullable=False, server_default="POS"
        ),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default="DRAFT"
        ),
        sa.Column(
            "total_amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column(
            "idempotency_key",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("idx_ros_order_restaurant", "ros_orders", ["restaurant_id"])
    op.create_index("idx_ros_order_session", "ros_orders", ["session_id"])
    op.create_index("idx_ros_order_status", "ros_orders", ["status"])

    # 4. ROS ORDER ITEMS
    op.create_table(
        "ros_order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ros_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "tax_rate",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default="19.25",
        ),
        sa.Column(
            "destination_station",
            sa.String(length=30),
            nullable=False,
            server_default="KITCHEN",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "details_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("idx_ros_item_order", "ros_order_items", ["order_id"])

    # 5. PRODUCTION TICKETS
    op.create_table(
        "production_tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ros_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "station", sa.String(length=30), nullable=False, server_default="KITCHEN"
        ),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default="QUEUED"
        ),
        sa.Column(
            "items_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_prod_ticket_restaurant", "production_tickets", ["restaurant_id"]
    )
    op.create_index("idx_prod_ticket_order", "production_tickets", ["order_id"])
    op.create_index(
        "idx_prod_ticket_station", "production_tickets", ["station", "status"]
    )

    # 6. ROS INVOICES
    op.create_table(
        "ros_invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("service_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ros_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("invoice_number", sa.String(length=100), nullable=False, unique=True),
        sa.Column("subtotal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "service_charge",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column(
            "discount_amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "amount_paid",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default="ISSUED"
        ),
        sa.Column("fiscal_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("idx_ros_invoice_restaurant", "ros_invoices", ["restaurant_id"])
    op.create_index("idx_ros_invoice_session", "ros_invoices", ["session_id"])
    op.create_index("idx_ros_invoice_number", "ros_invoices", ["invoice_number"])
    op.create_index("idx_ros_invoice_status", "ros_invoices", ["status"])

    # 7. ROS PAYMENT TRANSACTIONS
    op.create_table(
        "ros_payment_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ros_invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default="SUCCEEDED"
        ),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column(
            "idempotency_key",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index(
        "idx_ros_pay_restaurant", "ros_payment_transactions", ["restaurant_id"]
    )
    op.create_index("idx_ros_pay_invoice", "ros_payment_transactions", ["invoice_id"])

    # 8. ROS CASH SHIFTS
    op.create_table(
        "ros_cash_shifts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "operator_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("opening_balance", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "closing_balance_expected", sa.Numeric(precision=12, scale=2), nullable=True
        ),
        sa.Column(
            "closing_balance_counted", sa.Numeric(precision=12, scale=2), nullable=True
        ),
        sa.Column("variance", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="OPEN"
        ),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_cash_shift_restaurant", "ros_cash_shifts", ["restaurant_id"])
    op.create_index("idx_cash_shift_operator", "ros_cash_shifts", ["operator_user_id"])
    op.create_index("idx_cash_shift_status", "ros_cash_shifts", ["status"])

    # 9. ROS AUDIT LOGS
    op.create_table(
        "ros_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_name", sa.String(length=100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("idx_ros_audit_restaurant", "ros_audit_logs", ["restaurant_id"])
    op.create_index(
        "idx_ros_audit_entity", "ros_audit_logs", ["entity_name", "entity_id"]
    )


def downgrade():
    op.drop_table("ros_audit_logs")
    op.drop_table("ros_cash_shifts")
    op.drop_table("ros_payment_transactions")
    op.drop_table("ros_invoices")
    op.drop_table("production_tickets")
    op.drop_table("ros_order_items")
    op.drop_table("ros_orders")
    op.drop_table("service_sessions")
    op.drop_table("ros_customers")
