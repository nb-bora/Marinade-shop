"""add configurable menu combinations

Revision ID: 20260916_1000
Revises: 20260915_1400
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260916_1000"
down_revision = "20260915_1400"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "composants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nom", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column(
            "prix_supplement",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column("devise", sa.String(length=3), nullable=False, server_default="XAF"),
        sa.Column("disponible", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attributs_jsonb", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "prix_supplement >= 0", name="check_composant_supplement_positive"
        ),
    )
    op.create_index("idx_composant_restaurant", "composants", ["restaurant_id"])
    op.create_index("idx_composant_type", "composants", ["restaurant_id", "type"])
    op.create_index(
        "idx_composant_disponible", "composants", ["restaurant_id", "disponible"]
    )

    op.create_table(
        "combinaisons",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("menu_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("nom", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("prix", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("devise", sa.String(length=3), nullable=False, server_default="XAF"),
        sa.Column("disponible", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["menu_id"], ["menus.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("prix > 0", name="check_combinaison_prix_positive"),
    )
    op.create_index("idx_combinaison_restaurant", "combinaisons", ["restaurant_id"])
    op.create_index("idx_combinaison_menu", "combinaisons", ["menu_id"])
    op.create_index(
        "idx_combinaison_disponible", "combinaisons", ["restaurant_id", "disponible"]
    )

    op.create_table(
        "combinaison_composants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("combinaison_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("composant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("obligatoire", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["combinaison_id"], ["combinaisons.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["composant_id"], ["composants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_combinaison_composant_combinaison",
        "combinaison_composants",
        ["combinaison_id"],
    )
    op.create_index(
        "idx_combinaison_composant_composant",
        "combinaison_composants",
        ["composant_id"],
    )

    op.add_column(
        "commande_items",
        sa.Column("combinaison_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "commande_items",
        sa.Column(
            "supplements_total",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "commande_items", sa.Column("details_jsonb", postgresql.JSONB(), nullable=True)
    )
    op.create_foreign_key(
        "fk_commande_item_combinaison",
        "commande_items",
        "combinaisons",
        ["combinaison_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_item_combinaison", "commande_items", ["combinaison_id"])
    op.create_check_constraint(
        "check_item_supplements_positive", "commande_items", "supplements_total >= 0"
    )


def downgrade():
    op.drop_constraint(
        "check_item_supplements_positive", "commande_items", type_="check"
    )
    op.drop_index("idx_item_combinaison", table_name="commande_items")
    op.drop_constraint(
        "fk_commande_item_combinaison", "commande_items", type_="foreignkey"
    )
    op.drop_column("commande_items", "details_jsonb")
    op.drop_column("commande_items", "supplements_total")
    op.drop_column("commande_items", "combinaison_id")
    op.drop_table("combinaison_composants")
    op.drop_table("combinaisons")
    op.drop_table("composants")
