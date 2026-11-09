"""Recherche de références de paiement correcte sous toute collation PostgreSQL.

La recherche par préfixe borne ``vendor_reference`` par un intervalle d'octets. Avec une
collation locale (en_US.utf8, par défaut sur la plupart des PostgreSQL gérés) cet intervalle
excluait des lignes valides. La requête compare désormais en collation "C" ; cet index la sert.

Revision ID: 20261111_0900
Revises: 20261110_0900
"""

from alembic import op

revision = "20261111_0900"
down_revision = "20261110_0900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_intent_restaurant_reference_c "
        'ON payment_intents (restaurant_id, (vendor_reference COLLATE "C"))'
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_payment_intent_restaurant_reference_c")
