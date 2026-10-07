"""Per-restaurant payment references and a fast transaction history.

* ``payment_configurations.vendor_reference_prefix`` was ``MRD`` for EVERY restaurant
  (and chosen by the client), so a restaurant's transactions could not be told apart
  on the gateway side. Each configuration now gets a platform-unique prefix. Existing
  payments keep the reference they already sent to the gateway.
* ``payment_intents``: fees, completion time and failure reason, as reported by the
  gateway, so the restaurant sees what it actually received and why a payment failed.
* Indexes that make "my transactions, newest first" a single index descent whatever
  the number of restaurants or transactions (keyset pagination, O(log n + page)).

Revision ID: 20260928_1000
Revises: 20260927_1100
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_1000"
down_revision = "20260927_1100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Les tables de paiement ont une RLS FORCEE : sans contexte, meme le proprietaire
    # du schema ne voit aucune ligne et l'UPDATE ci-dessous ne ferait rien.
    op.execute("SELECT set_config('app.is_platform_admin', 'true', true)")

    op.execute(
        "UPDATE payment_configurations "
        "SET vendor_reference_prefix = 'MRD-' || upper(substr(md5(id::text || restaurant_id::text), 1, 8))"
    )
    op.execute("ALTER TABLE payment_configurations ALTER COLUMN vendor_reference_prefix DROP DEFAULT")
    op.create_index(
        "uq_payment_configuration_reference_prefix",
        "payment_configurations",
        ["vendor_reference_prefix"],
        unique=True,
    )
    op.create_check_constraint(
        "check_payment_reference_prefix",
        "payment_configurations",
        "vendor_reference_prefix ~ '^[A-Z0-9][A-Z0-9-]{2,29}$'",
    )

    op.add_column("payment_intents", sa.Column("fees_fcfa", sa.Numeric(14, 2), nullable=True))
    op.add_column("payment_intents", sa.Column("fees_inclusive", sa.Boolean(), nullable=True))
    op.add_column("payment_intents", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payment_intents", sa.Column("failure_reason", sa.Text(), nullable=True))

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_intent_restaurant_created "
        "ON payment_intents (restaurant_id, created_at DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_intent_restaurant_status_created "
        "ON payment_intents (restaurant_id, status, created_at DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_intent_restaurant_reference "
        "ON payment_intents (restaurant_id, vendor_reference)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_payment_intent_restaurant_reference")
    op.execute("DROP INDEX IF EXISTS idx_payment_intent_restaurant_status_created")
    op.execute("DROP INDEX IF EXISTS idx_payment_intent_restaurant_created")
    for column in ("failure_reason", "completed_at", "fees_inclusive", "fees_fcfa"):
        op.drop_column("payment_intents", column)
    op.drop_constraint("check_payment_reference_prefix", "payment_configurations", type_="check")
    op.drop_index("uq_payment_configuration_reference_prefix", table_name="payment_configurations")
    op.execute("ALTER TABLE payment_configurations ALTER COLUMN vendor_reference_prefix SET DEFAULT 'MRD'")
