"""Composite indexes for the hot, tenant-scoped queries.

Every restaurant-scoped query filters on ``restaurant_id`` (the RLS policy and the
application both do). A single-column index on a low-selectivity column such as
``status`` or ``station`` cannot serve that: the planner had to combine two indexes
and read tens of thousands of unrelated rows. These composite indexes start with
``restaurant_id`` so each lookup is one index descent (O(log n)) followed by only the
rows that match.

Also fills three gaps found by the audit:
  * ``daily_balances.restaurant_id`` had no index at all;
  * ``ros_invoices.order_id`` (invoice of an order) had no index;
  * the payment lookup used by reporting.

Revision ID: 20260927_1000
Revises: 20260926_1000
"""

from alembic import op

revision = "20260927_1000"
down_revision = "20260926_1000"
branch_labels = None
depends_on = None

INDEXES = (
    # name, table, columns
    ("idx_daily_balance_restaurant_date", "daily_balances", "restaurant_id, balance_date"),
    ("idx_prod_ticket_queue", "production_tickets", "restaurant_id, station, status, created_at"),
    ("idx_service_session_open", "service_sessions", "restaurant_id, status, opened_at"),
    ("idx_ros_order_restaurant_created", "ros_orders", "restaurant_id, created_at"),
    ("idx_ros_invoice_order", "ros_invoices", "order_id"),
    ("idx_ros_invoice_restaurant_status", "ros_invoices", "restaurant_id, status"),
    ("idx_ros_pay_restaurant_status", "ros_payment_transactions", "restaurant_id, status, payment_method"),
    ("idx_cash_shift_open", "ros_cash_shifts", "restaurant_id, operator_user_id, status"),
    ("idx_commande_restaurant_created", "commandes", "restaurant_id, created_at"),
    ("idx_commande_restaurant_statut", "commandes", "restaurant_id, statut"),
    ("idx_reservation_restaurant_status", "reservations", "restaurant_id, status, reservation_date"),
    ("idx_stock_mouvement_composant_date", "stock_mouvements", "composant_id, created_at"),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")


def downgrade() -> None:
    for name, _table, _columns in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
