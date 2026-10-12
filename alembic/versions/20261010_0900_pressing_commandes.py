"""Commandes de pressing : commandes, lignes figées, affectations machines, paiements, clôtures.

Cinq tables avec ``restaurant_id`` et la même politique de RLS (forcée, contexte évalué une
seule fois par requête) que ``pressing_pricing``. ``pressing_machines.commande_courante_id``
reçoit enfin sa clé étrangère (SET NULL : la machine se libère si la commande disparaît).
Un index unique partiel interdit deux affectations vivantes sur la même machine.

Revision ID: 20261010_0900
Revises: 20261009_1400
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261010_0900"
down_revision = "20261009_1400"
branch_labels = None
depends_on = None

PREDICATE = (
    "((SELECT app_is_platform_admin()) OR restaurant_id = (SELECT app_current_tenant_id()))"
)
TABLES = (
    "pressing_commandes",
    "pressing_commande_lignes",
    "pressing_commande_machines",
    "pressing_paiements",
    "pressing_clotures",
)
STATUTS = (
    "recue", "en_attente_machine", "en_lavage", "attente_sechage",
    "en_sechage", "pret", "livre", "annulee",
)
MODES = ("especes", "mobile_money", "carte", "autre")


def _in(column, values):
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _uuid_pk():
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _restaurant():
    return sa.Column(
        "restaurant_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )


def _commande_fk():
    return sa.Column(
        "commande_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("pressing_commandes.id", ondelete="CASCADE"),
        nullable=False,
    )


def _auteur():
    return sa.Column(
        "auteur_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


def _tstz(name, nullable=True, default_now=False):
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if default_now else None,
    )


def upgrade() -> None:
    op.create_table(
        "pressing_commandes",
        _uuid_pk(),
        _restaurant(),
        sa.Column("numero", sa.String(30), nullable=False),
        sa.Column("client_nom", sa.String(120), nullable=False),
        sa.Column("client_telephone", sa.String(20), nullable=True),
        sa.Column("poids_grams", sa.Integer(), nullable=True),
        sa.Column("poids_facturable_grams", sa.Integer(), nullable=True),
        sa.Column("lavage", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sechage", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("instructions", sa.String(500), nullable=True),
        sa.Column(
            "types_linge",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("statut", sa.String(25), nullable=False, server_default="recue"),
        sa.Column("etape", sa.String(10), nullable=True),
        sa.Column("sous_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remise_fcfa", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("montant_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("montant_paye", sa.Integer(), nullable=False, server_default="0"),
        _tstz("cree_le", nullable=False, default_now=True),
        _tstz("pris_en_charge_le"),
        _tstz("pret_le"),
        _tstz("livre_le"),
        _tstz("debut_prevu"),
        _tstz("fin_estimee"),
        _tstz("fin_reelle"),
        _tstz("annule_le"),
        sa.Column("motif_annulation", sa.Text(), nullable=True),
        _auteur(),
        _tstz("updated_at", default_now=True),
        sa.UniqueConstraint("restaurant_id", "numero", name="uq_pressing_commande_numero"),
        sa.CheckConstraint(_in("statut", STATUTS), name="ck_pressing_commande_statut"),
        sa.CheckConstraint(
            "etape IS NULL OR etape IN ('lavage', 'sechage')", name="ck_pressing_commande_etape"
        ),
        sa.CheckConstraint(
            "poids_grams IS NULL OR (poids_grams >= 1 AND poids_grams <= 1000000)",
            name="ck_pressing_commande_poids",
        ),
        sa.CheckConstraint(
            "sous_total >= 0 AND remise_fcfa >= 0 AND montant_total >= 0",
            name="ck_pressing_commande_montants",
        ),
        sa.CheckConstraint(
            "montant_paye >= 0 AND montant_paye <= montant_total",
            name="ck_pressing_commande_paye",
        ),
    )
    op.create_index(
        "idx_pressing_commande_statut", "pressing_commandes", ["restaurant_id", "statut"]
    )
    op.create_index(
        "idx_pressing_commande_cree", "pressing_commandes", ["restaurant_id", "cree_le"]
    )
    op.create_index(
        "idx_pressing_commande_telephone",
        "pressing_commandes",
        ["restaurant_id", "client_telephone"],
    )

    op.create_table(
        "pressing_commande_lignes",
        _uuid_pk(),
        _restaurant(),
        _commande_fk(),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("type", sa.String(15), nullable=False),
        sa.Column("libelle", sa.String(160), nullable=False),
        sa.Column("quantite", sa.Numeric(10, 3), nullable=False),
        sa.Column("prix_unitaire", sa.Integer(), nullable=False),
        sa.Column("montant", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            _in("type", ("lavage", "sechage", "article", "combinaison")),
            name="ck_pressing_commande_ligne_type",
        ),
        sa.CheckConstraint(
            "montant >= 0 AND prix_unitaire >= 0", name="ck_pressing_commande_ligne_montant"
        ),
    )
    op.create_index("idx_pressing_ligne_commande", "pressing_commande_lignes", ["commande_id"])
    op.create_index(
        "idx_pressing_commande_ligne_restaurant", "pressing_commande_lignes", ["restaurant_id"]
    )

    op.create_table(
        "pressing_commande_machines",
        _uuid_pk(),
        _restaurant(),
        _commande_fk(),
        sa.Column(
            "machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pressing_machines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("etape", sa.String(10), nullable=False),
        sa.Column("charge_g", sa.Integer(), nullable=False),
        sa.Column("programme", sa.String(80), nullable=True),
        sa.Column("duree_min", sa.Integer(), nullable=True),
        sa.Column(
            "intervention_humaine", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        _tstz("debut_prevu"),
        _tstz("fin_prevue"),
        _tstz("debut_reel"),
        _tstz("fin_reelle"),
        _tstz("dechargee_le"),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
        _tstz("cree_le", nullable=False, default_now=True),
        sa.CheckConstraint("etape IN ('lavage', 'sechage')", name="ck_pressing_cm_etape"),
        sa.CheckConstraint("charge_g > 0", name="ck_pressing_cm_charge"),
    )
    op.create_index("idx_pressing_cm_commande", "pressing_commande_machines", ["commande_id"])
    op.create_index(
        "idx_pressing_cm_machine", "pressing_commande_machines", ["machine_id", "debut_reel"]
    )
    op.create_index(
        "idx_pressing_cm_restaurant", "pressing_commande_machines", ["restaurant_id", "fin_reelle"]
    )
    op.create_index(
        "uq_pressing_cm_machine_vivante",
        "pressing_commande_machines",
        ["machine_id"],
        unique=True,
        postgresql_where=sa.text("actif AND fin_reelle IS NULL"),
    )

    op.create_table(
        "pressing_paiements",
        _uuid_pk(),
        _restaurant(),
        _commande_fk(),
        sa.Column("montant", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(15), nullable=False),
        sa.Column("reference", sa.String(80), nullable=True),
        _tstz("cree_le", nullable=False, default_now=True),
        _auteur(),
        sa.CheckConstraint("montant > 0", name="ck_pressing_paiement_montant"),
        sa.CheckConstraint(_in("mode", MODES), name="ck_pressing_paiement_mode"),
    )
    op.create_index("idx_pressing_paiement_commande", "pressing_paiements", ["commande_id"])
    op.create_index(
        "idx_pressing_paiement_restaurant", "pressing_paiements", ["restaurant_id", "cree_le"]
    )

    op.create_table(
        "pressing_clotures",
        _uuid_pk(),
        _restaurant(),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("total_encaisse", sa.Integer(), nullable=False),
        sa.Column("especes_attendues", sa.Integer(), nullable=False),
        sa.Column("montant_compte", sa.Integer(), nullable=False),
        sa.Column("ecart", sa.Integer(), nullable=False),
        _auteur(),
        _tstz("cree_le", nullable=False, default_now=True),
        sa.UniqueConstraint("restaurant_id", "date", name="uq_pressing_cloture_jour"),
        sa.CheckConstraint("montant_compte >= 0", name="ck_pressing_cloture_compte"),
    )

    op.create_foreign_key(
        "fk_pressing_machine_commande_courante",
        "pressing_machines",
        "pressing_commandes",
        ["commande_courante_id"],
        ["id"],
        ondelete="SET NULL",
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
    op.drop_constraint(
        "fk_pressing_machine_commande_courante", "pressing_machines", type_="foreignkey"
    )
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.drop_table("pressing_clotures")
    op.drop_table("pressing_paiements")
    op.drop_table("pressing_commande_machines")
    op.drop_table("pressing_commande_lignes")
    op.drop_table("pressing_commandes")
