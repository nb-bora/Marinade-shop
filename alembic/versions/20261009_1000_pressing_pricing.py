"""Tarification d'un pressing : tarifs, articles, combinaisons et leurs lignes.

Quatre tables, toutes avec ``restaurant_id`` et la même politique de RLS (forcée, contexte
évalué une seule fois par requête) que les autres tables du projet. Les unicités de nom sont
par restaurant et insensibles à la casse. La ligne de tarif d'un restaurant n'est PAS
insérée ici : le service la crée à la première lecture (500 FCFA/kg, arrondi 1000 g
supérieur).

Revision ID: 20261009_1000
Revises: 20261008_0900
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261009_1000"
down_revision = "20261008_0900"
branch_labels = None
depends_on = None

PREDICATE = (
    "((SELECT app_is_platform_admin()) OR restaurant_id = (SELECT app_current_tenant_id()))"
)
TABLES = (
    "pressing_tarifs",
    "pressing_articles",
    "pressing_combinaisons",
    "pressing_combinaison_lignes",
)


def _uuid_pk():
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _restaurant():
    return sa.Column(
        "restaurant_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def upgrade() -> None:
    op.create_table(
        "pressing_tarifs",
        _uuid_pk(),
        _restaurant(),
        sa.Column("prix_kg", sa.Integer(), nullable=False),
        sa.Column("prix_sechage_kg", sa.Integer(), nullable=True),
        sa.Column("arrondi_pas_grammes", sa.Integer(), nullable=False),
        sa.Column("arrondi_mode", sa.String(10), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("restaurant_id", name="uq_pressing_tarif_restaurant"),
        sa.CheckConstraint("prix_kg >= 0", name="ck_pressing_tarif_prix_kg"),
        sa.CheckConstraint(
            "prix_sechage_kg IS NULL OR prix_sechage_kg >= 0",
            name="ck_pressing_tarif_prix_sechage",
        ),
        sa.CheckConstraint(
            "arrondi_pas_grammes IN (1, 100, 500, 1000)", name="ck_pressing_tarif_pas"
        ),
        sa.CheckConstraint(
            "arrondi_mode IN ('superieur', 'proche')", name="ck_pressing_tarif_mode"
        ),
    )

    op.create_table(
        "pressing_articles",
        _uuid_pk(),
        _restaurant(),
        sa.Column("nom", sa.String(120), nullable=False),
        sa.Column("prix_unitaire", sa.Integer(), nullable=False),
        sa.Column("categorie", sa.String(120), nullable=True),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.CheckConstraint("prix_unitaire >= 0", name="ck_pressing_article_prix"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_pressing_article_nom "
        "ON pressing_articles (restaurant_id, lower(nom))"
    )

    op.create_table(
        "pressing_combinaisons",
        _uuid_pk(),
        _restaurant(),
        sa.Column("nom", sa.String(120), nullable=False),
        sa.Column("prix", sa.Integer(), nullable=False),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.CheckConstraint("prix >= 0", name="ck_pressing_combinaison_prix"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_pressing_combinaison_nom "
        "ON pressing_combinaisons (restaurant_id, lower(nom))"
    )

    op.create_table(
        "pressing_combinaison_lignes",
        _uuid_pk(),
        _restaurant(),
        sa.Column(
            "combinaison_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pressing_combinaisons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pressing_articles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantite", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "combinaison_id", "article_id", name="uq_pressing_ligne_article"
        ),
        sa.CheckConstraint("quantite >= 1", name="ck_pressing_ligne_quantite"),
    )
    op.create_index(
        "idx_pressing_ligne_restaurant", "pressing_combinaison_lignes", ["restaurant_id"]
    )
    op.create_index(
        "idx_pressing_ligne_combinaison", "pressing_combinaison_lignes", ["combinaison_id"]
    )
    op.create_index(
        "idx_pressing_ligne_article", "pressing_combinaison_lignes", ["article_id"]
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"FOR ALL USING ({PREDICATE}) WITH CHECK ({PREDICATE})"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.drop_table("pressing_combinaison_lignes")
    op.drop_table("pressing_combinaisons")
    op.drop_table("pressing_articles")
    op.drop_table("pressing_tarifs")
