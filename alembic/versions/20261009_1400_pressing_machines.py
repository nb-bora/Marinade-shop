"""Espace pressing : type d'établissement, zones, machines, événements, maintenances.

- ``restaurants.type_etablissement`` : 'restaurant' (défaut, lignes existantes) ou 'pressing'.
- ``pressing_zones`` (plan), ``pressing_machines`` (fiche technique, programmes en JSONB, état
  opérationnel), ``pressing_machine_evenements`` (historique), ``pressing_maintenances``.

Chaque nouvelle table porte ``restaurant_id`` et la même politique de RLS (forcée, contexte
évalué une seule fois par requête) que la migration de tarification pressing. Les unicités
de nom et de numéro de série sont par restaurant, insensibles à la casse.

Revision ID: 20261009_1400
Revises: 20261009_1000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261009_1400"
down_revision = "20261009_1000"
branch_labels = None
depends_on = None

PREDICATE = (
    "((SELECT app_is_platform_admin()) OR restaurant_id = (SELECT app_current_tenant_id()))"
)
TABLES = (
    "pressing_zones",
    "pressing_machines",
    "pressing_machine_evenements",
    "pressing_maintenances",
)

ZONE_TYPES = ("lavage", "sechage", "reception", "attente", "pliage", "stockage", "autre")
ETATS = (
    "libre",
    "reservee",
    "en_cycle",
    "cycle_termine",
    "attente_dechargement",
    "maintenance",
    "hors_service",
)


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


def _uuid_fk(name, target, ondelete, nullable):
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
    )


def upgrade() -> None:
    op.add_column(
        "restaurants",
        sa.Column(
            "type_etablissement",
            sa.String(20),
            nullable=False,
            server_default="restaurant",
        ),
    )
    op.create_check_constraint(
        "ck_restaurants_type_etablissement",
        "restaurants",
        "type_etablissement IN ('restaurant', 'pressing')",
    )

    op.create_table(
        "pressing_zones",
        _uuid_pk(),
        _restaurant(),
        sa.Column("nom", sa.String(120), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("couleur", sa.String(7), nullable=False),
        sa.Column("x", sa.Numeric(5, 2), nullable=False),
        sa.Column("y", sa.Numeric(5, 2), nullable=False),
        sa.Column("w", sa.Numeric(5, 2), nullable=False),
        sa.Column("h", sa.Numeric(5, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(_in("type", ZONE_TYPES), name="ck_pressing_zone_type"),
        sa.CheckConstraint("couleur ~ '^#[0-9A-Fa-f]{6}$'", name="ck_pressing_zone_couleur"),
        sa.CheckConstraint(
            "x >= 0 AND y >= 0 AND w > 0 AND h > 0 AND x + w <= 100 AND y + h <= 100",
            name="ck_pressing_zone_geometrie",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_pressing_zone_nom ON pressing_zones (restaurant_id, lower(nom))"
    )

    op.create_table(
        "pressing_machines",
        _uuid_pk(),
        _restaurant(),
        sa.Column("nom", sa.String(120), nullable=False),
        sa.Column("categorie", sa.String(20), nullable=False),
        sa.Column("marque", sa.String(120), nullable=True),
        sa.Column("modele", sa.String(120), nullable=True),
        sa.Column("numero_serie", sa.String(120), nullable=True),
        sa.Column("type_fonctionnement", sa.String(20), nullable=False),
        sa.Column("capacite_kg", sa.Numeric(6, 2), nullable=False),
        sa.Column(
            "programmes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        _uuid_fk("zone_id", "pressing_zones.id", "RESTRICT", True),
        sa.Column("position_x", sa.Numeric(5, 2), nullable=True),
        sa.Column("position_y", sa.Numeric(5, 2), nullable=True),
        sa.Column("conso_electrique_kwh_cycle", sa.Numeric(8, 3), nullable=True),
        sa.Column("conso_eau_litres_cycle", sa.Numeric(8, 2), nullable=True),
        sa.Column("date_mise_en_service", sa.Date(), nullable=True),
        sa.Column("remarques", sa.Text(), nullable=True),
        sa.Column("contraintes", sa.Text(), nullable=True),
        sa.Column(
            "etat_operationnel", sa.String(25), nullable=False, server_default="libre"
        ),
        sa.Column("commande_courante_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fin_estimee", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            _in("categorie", ("lave_linge", "seche_linge")),
            name="ck_pressing_machine_categorie",
        ),
        sa.CheckConstraint(
            _in("type_fonctionnement", ("semi_automatique", "automatique", "autre")),
            name="ck_pressing_machine_fonctionnement",
        ),
        sa.CheckConstraint(_in("etat_operationnel", ETATS), name="ck_pressing_machine_etat"),
        sa.CheckConstraint(
            "capacite_kg > 0 AND capacite_kg <= 200", name="ck_pressing_machine_capacite"
        ),
        sa.CheckConstraint(
            "(position_x IS NULL OR (position_x >= 0 AND position_x <= 100)) AND "
            "(position_y IS NULL OR (position_y >= 0 AND position_y <= 100))",
            name="ck_pressing_machine_position",
        ),
        sa.CheckConstraint(
            "(conso_electrique_kwh_cycle IS NULL OR conso_electrique_kwh_cycle >= 0) AND "
            "(conso_eau_litres_cycle IS NULL OR conso_eau_litres_cycle >= 0)",
            name="ck_pressing_machine_conso",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_pressing_machine_nom "
        "ON pressing_machines (restaurant_id, lower(nom))"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_pressing_machine_serie "
        "ON pressing_machines (restaurant_id, lower(numero_serie)) "
        "WHERE numero_serie IS NOT NULL"
    )
    op.create_index(
        "idx_pressing_machine_etat", "pressing_machines", ["restaurant_id", "etat_operationnel"]
    )
    op.create_index("idx_pressing_machine_zone", "pressing_machines", ["zone_id"])

    op.create_table(
        "pressing_machine_evenements",
        _uuid_pk(),
        _restaurant(),
        _uuid_fk("machine_id", "pressing_machines.id", "CASCADE", False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("ancien_etat", sa.String(25), nullable=True),
        sa.Column("nouvel_etat", sa.String(25), nullable=True),
        sa.Column("motif", sa.Text(), nullable=True),
        sa.Column("maintenance_id", postgresql.UUID(as_uuid=True), nullable=True),
        _uuid_fk("auteur_id", "users.id", "SET NULL", True),
        sa.Column(
            "date_evenement",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            _in("type", ("etat_change", "maintenance", "note")),
            name="ck_pressing_evenement_type",
        ),
    )
    op.create_index(
        "idx_pressing_evenement_machine",
        "pressing_machine_evenements",
        ["machine_id", "date_evenement"],
    )
    op.create_index(
        "idx_pressing_evenement_restaurant", "pressing_machine_evenements", ["restaurant_id"]
    )

    op.create_table(
        "pressing_maintenances",
        _uuid_pk(),
        _restaurant(),
        _uuid_fk("machine_id", "pressing_machines.id", "CASCADE", False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("debut", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fin", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duree_estimee_min", sa.Integer(), nullable=True),
        _uuid_fk("auteur_id", "users.id", "SET NULL", True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            _in("type", ("entretien", "panne", "reparation")),
            name="ck_pressing_maintenance_type",
        ),
        sa.CheckConstraint("fin IS NULL OR fin >= debut", name="ck_pressing_maintenance_dates"),
        sa.CheckConstraint(
            "duree_estimee_min IS NULL OR duree_estimee_min > 0",
            name="ck_pressing_maintenance_duree",
        ),
    )
    op.create_index(
        "idx_pressing_maintenance_machine", "pressing_maintenances", ["machine_id", "debut"]
    )
    op.create_index(
        "idx_pressing_maintenance_restaurant", "pressing_maintenances", ["restaurant_id"]
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
    op.drop_table("pressing_maintenances")
    op.drop_table("pressing_machine_evenements")
    op.drop_table("pressing_machines")
    op.drop_table("pressing_zones")
    op.drop_constraint("ck_restaurants_type_etablissement", "restaurants", type_="check")
    op.drop_column("restaurants", "type_etablissement")
