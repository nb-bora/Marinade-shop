"""Suppression logique des réservations (DELETE ne détruit plus la ligne).

Ajoute ``reservations.deleted_at`` : une réservation « supprimée » reste en base
(historique, no-show, statistiques de fréquentation) mais n'apparaît plus dans l'API
et ne bloque plus sa table. Colonne nullable, sans réécriture de table.

Revision ID: 20261008_0900
Revises: 20260928_1200
"""

from alembic import op
import sqlalchemy as sa

revision = "20261008_0900"
down_revision = "20260928_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reservations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reservations", "deleted_at")
