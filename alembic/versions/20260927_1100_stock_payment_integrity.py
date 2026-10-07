"""Stock and payment integrity.

* ``boissons.composant_id`` / ``stock_par_vente``: a drink can be backed by a stock
  component (a bottle, a keg portion), so beverages are tracked in the same stock as
  dishes instead of being invisible to inventory.
* ``ros_payment_transactions.received_by``: who took the payment. The cash-shift
  closing used to add up the cash of EVERY cashier of the restaurant.
* ``stock_composants``: ``reservee <= quantite`` is now enforced by the database.
  It is added NOT VALID so existing rows are never rejected; every new write is
  checked.

Revision ID: 20260927_1100
Revises: 20260927_1000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260927_1100"
down_revision = "20260927_1000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "boissons",
        sa.Column(
            "composant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("composants.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "boissons",
        sa.Column(
            "stock_par_vente",
            sa.Numeric(12, 3),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "check_boisson_stock_par_vente_positive", "boissons", "stock_par_vente > 0"
    )
    op.create_index("idx_boisson_composant", "boissons", ["composant_id"])

    op.add_column(
        "ros_payment_transactions",
        sa.Column(
            "received_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_ros_pay_cash_operator",
        "ros_payment_transactions",
        ["restaurant_id", "received_by", "created_at"],
    )

    op.execute(
        "ALTER TABLE stock_composants "
        "ADD CONSTRAINT check_stock_reservee_within_quantite "
        "CHECK (reservee <= quantite) NOT VALID"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE stock_composants "
        "DROP CONSTRAINT IF EXISTS check_stock_reservee_within_quantite"
    )
    op.drop_index("idx_ros_pay_cash_operator", table_name="ros_payment_transactions")
    op.drop_column("ros_payment_transactions", "received_by")
    op.drop_index("idx_boisson_composant", table_name="boissons")
    op.drop_constraint(
        "check_boisson_stock_par_vente_positive", "boissons", type_="check"
    )
    op.drop_column("boissons", "stock_par_vente")
    op.drop_column("boissons", "composant_id")
