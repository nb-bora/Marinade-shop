"""Row level security for the ROS engine, reservations, recipes and refunds.

Migration 20260924_1200 isolated the catalogue, stock, orders and payments by
restaurant. Every table added afterwards (ROS engine, reservations, waitlist,
plat BOM, refunds) was left without a policy, so a connected user of one
restaurant could read and write another restaurant's data at the database level.
This migration closes that gap with the same predicates and FORCE ROW LEVEL
SECURITY, so the policies also bind the table owner.

Revision ID: 20260926_1000
Revises: 20260925_1700

Important: row level security only protects data when the application connects
with a role that is NOT a superuser, does NOT have BYPASSRLS and is NOT the owner
of these tables. Run migrations with MIGRATION_DATABASE_URL (owner role) and the
application with a dedicated role; the application refuses to start in production
otherwise.
"""

from alembic import op

revision = "20260926_1000"
down_revision = "20260925_1700"
branch_labels = None
depends_on = None

ADMIN = "app_is_platform_admin()"
TENANT = "app_current_tenant_id()"

# Tables carrying their own restaurant_id.
DIRECT = (
    "ros_customers",
    "service_sessions",
    "ros_orders",
    "production_tickets",
    "ros_invoices",
    "ros_payment_transactions",
    "ros_cash_shifts",
    "ros_audit_logs",
    "reservations",
    "waitlist_entries",
)

# Child tables: tenant resolved through their parent.
CHILD = {
    "ros_order_items": (
        "EXISTS (SELECT 1 FROM ros_orders p WHERE p.id = ros_order_items.order_id "
        f"AND p.restaurant_id = {TENANT})"
    ),
    "reservation_guests": (
        "EXISTS (SELECT 1 FROM reservations p WHERE p.id = reservation_guests.reservation_id "
        f"AND p.restaurant_id = {TENANT})"
    ),
    "plat_composants": (
        "EXISTS (SELECT 1 FROM plats p WHERE p.id = plat_composants.plat_id "
        f"AND p.restaurant_id = {TENANT})"
    ),
    "commande_refunds": (
        "EXISTS (SELECT 1 FROM commandes p WHERE p.id = commande_refunds.commande_id "
        f"AND p.restaurant_id = {TENANT})"
    ),
}


def _enable(table: str, predicate: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"FOR ALL USING ({predicate}) WITH CHECK ({predicate})"
    )


def _disable(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    for table in DIRECT:
        _enable(table, f"({ADMIN} OR restaurant_id = {TENANT})")
    for table, predicate in CHILD.items():
        _enable(table, f"({ADMIN} OR {predicate})")


def downgrade() -> None:
    for table in (*DIRECT, *CHILD):
        _disable(table)
