"""add component stock and recipe quantities

Revision ID: 20260916_1200
Revises: 20260916_1000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260916_1200"
down_revision = "20260916_1000"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("composants", sa.Column("stock_unite", sa.String(length=20), nullable=False, server_default="portion"))
    op.add_column("combinaison_composants", sa.Column("quantite", sa.Numeric(precision=10, scale=3), nullable=False, server_default="1"))
    op.create_check_constraint(
        "check_combinaison_composant_quantite_positive",
        "combinaison_composants",
        "quantite > 0",
    )
    op.create_unique_constraint(
        "uq_combinaison_composant",
        "combinaison_composants",
        ["combinaison_id", "composant_id"],
    )

    op.create_table(
        "stock_composants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("composant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantite", sa.Numeric(precision=12, scale=3), nullable=False, server_default="0"),
        sa.Column("reservee", sa.Numeric(precision=12, scale=3), nullable=False, server_default="0"),
        sa.Column("seuil_alerte", sa.Numeric(precision=12, scale=3), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["composant_id"], ["composants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("composant_id"),
        sa.CheckConstraint("quantite >= 0", name="check_stock_quantite_positive"),
        sa.CheckConstraint("reservee >= 0", name="check_stock_reservee_positive"),
        sa.CheckConstraint("seuil_alerte >= 0", name="check_stock_seuil_positive"),
    )
    op.create_index("idx_stock_composant", "stock_composants", ["composant_id"])
    op.execute(
        "INSERT INTO stock_composants (id, composant_id) "
        "SELECT gen_random_uuid(), id FROM composants"
    )

    op.create_table(
        "stock_mouvements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("composant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("quantite", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("reference_type", sa.String(length=30), nullable=True),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["composant_id"], ["composants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("quantite > 0", name="check_stock_mouvement_quantite_positive"),
    )
    op.create_index("idx_stock_mouvement_composant", "stock_mouvements", ["composant_id"])
    op.create_index("idx_stock_mouvement_date", "stock_mouvements", ["created_at"])


def downgrade():
    op.drop_index("idx_stock_mouvement_date", table_name="stock_mouvements")
    op.drop_index("idx_stock_mouvement_composant", table_name="stock_mouvements")
    op.drop_table("stock_mouvements")
    op.drop_index("idx_stock_composant", table_name="stock_composants")
    op.drop_table("stock_composants")
    op.drop_constraint("uq_combinaison_composant", "combinaison_composants", type_="unique")
    op.drop_constraint("check_combinaison_composant_quantite_positive", "combinaison_composants", type_="check")
    op.drop_column("combinaison_composants", "quantite")
    op.drop_column("composants", "stock_unite")