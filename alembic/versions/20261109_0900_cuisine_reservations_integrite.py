"""Cuisine et réservations : intégrité des états, routage serveur, fuseau du restaurant.

Cuisine (tickets de production)
* ``production_tickets`` : ``started_at``, ``served_at``, ``cancelled_at`` (horodatages de chaque
  transition), ``priority`` (0 = normal) et ``course`` (service : entrée, plat, dessert).
* ``plats``, ``boissons``, ``combinaisons`` : ``station`` (poste de production, défaut KITCHEN) ; les
  boissons passent au BAR. Le poste est désormais décidé par le catalogue, pas par le client.

Réservations et liste d'attente
* ``reservations.no_show_at`` : horodatage de l'absence, comme ``confirmed_at`` et ``checked_in_at``.
* ``restaurants.timezone`` : fuseau du restaurant (défaut Africa/Douala) ; les dates de réservation et
  les rappels s'y affichent, quel que soit le poste.
* ``waitlist_entries.customer_id`` : lien vers la fiche client (nullable).
* ``waitlist_entries`` : positions renumérotées (1, 2, 3… par restaurant pour les entrées en attente),
  puis index unique partiel ``(restaurant_id, position) WHERE status = 'WAITING'`` : deux ajouts
  simultanés ne peuvent plus recevoir la même position.

Le chevauchement des réservations n'est PAS une contrainte de base : des chevauchements existent dans
les données de test et une contrainte d'exclusion échouerait. Il est vérifié par le service, sous un
verrou sur la table (``SELECT ... FOR UPDATE``).

Revision ID: 20261109_0900
Revises: 20261020_0900
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261109_0900"
down_revision = "20261020_0900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Cuisine -----------------------------------------------------------------------------
    op.add_column("production_tickets", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("production_tickets", sa.Column("served_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("production_tickets", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "production_tickets",
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("production_tickets", sa.Column("course", sa.SmallInteger(), nullable=True))

    for table in ("plats", "combinaisons"):
        op.add_column(
            table,
            sa.Column("station", sa.String(length=30), nullable=False, server_default="KITCHEN"),
        )
    op.add_column(
        "boissons",
        sa.Column("station", sa.String(length=30), nullable=False, server_default="BAR"),
    )

    # --- Réservations, fuseau, liste d'attente ------------------------------------------------
    op.add_column("reservations", sa.Column("no_show_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "restaurants",
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Africa/Douala"),
    )
    op.add_column(
        "waitlist_entries",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_waitlist_customer",
        "waitlist_entries",
        "ros_customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Renumérotation des positions en attente (avant l'index unique) : 1, 2, 3… par restaurant.
    # ``waitlist_entries`` est protégée par RLS : sans ce contexte (transaction seulement), la mise à
    # jour ne verrait que les lignes d'un éventuel tenant, et des doublons resteraient.
    op.execute("SELECT set_config('app.is_platform_admin', 'true', true)")
    op.execute(
        """
        UPDATE waitlist_entries AS w
        SET position = r.rn
        FROM (
            SELECT id,
                   row_number() OVER (PARTITION BY restaurant_id ORDER BY position, joined_at, id) AS rn
            FROM waitlist_entries
            WHERE status = 'WAITING'
        ) AS r
        WHERE w.id = r.id
        """
    )
    op.create_index(
        "uq_waitlist_position_waiting",
        "waitlist_entries",
        ["restaurant_id", "position"],
        unique=True,
        postgresql_where=sa.text("status = 'WAITING'"),
    )


def downgrade() -> None:
    op.drop_index("uq_waitlist_position_waiting", table_name="waitlist_entries")
    op.drop_constraint("fk_waitlist_customer", "waitlist_entries", type_="foreignkey")
    op.drop_column("waitlist_entries", "customer_id")
    op.drop_column("restaurants", "timezone")
    op.drop_column("reservations", "no_show_at")

    op.drop_column("boissons", "station")
    for table in ("combinaisons", "plats"):
        op.drop_column(table, "station")

    op.drop_column("production_tickets", "course")
    op.drop_column("production_tickets", "priority")
    op.drop_column("production_tickets", "cancelled_at")
    op.drop_column("production_tickets", "served_at")
    op.drop_column("production_tickets", "started_at")
