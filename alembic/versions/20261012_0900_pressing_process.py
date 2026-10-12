"""Process du pressing : charges successives, interruption de cycle, promesse client,
annulation (contre-passation) des paiements.

* ``pressing_commandes.fin_estimee_source`` : origine de la fin estimée
  (estimation_initiale | affectation | cycle) ;
* ``pressing_commande_machines.interrompue_le`` / ``motif_interruption`` : cycle interrompu ;
* ``pressing_paiements`` : une annulation est une écriture de contre-passation (montant
  négatif, ``annule_paiement_id`` vers l'original, au plus une par paiement) ; l'original porte
  ``annule_le`` / ``annule_par`` / ``motif_annulation``. ``montant > 0`` devient ``montant <> 0``
  avec « montant < 0 si et seulement si annule_paiement_id est renseigné ».

Aucune table créée : les colonnes ajoutées héritent de la RLS forcée de leur table
(politique ``*_tenant_isolation`` posée par 20261010_0900).

Revision ID: 20261012_0900
Revises: 20261010_0900
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261012_0900"
down_revision = "20261010_0900"
branch_labels = None
depends_on = None

SOURCES = ("estimation_initiale", "affectation", "cycle")


def upgrade() -> None:
    # --- commandes : origine de la fin estimée
    op.add_column(
        "pressing_commandes", sa.Column("fin_estimee_source", sa.String(25), nullable=True)
    )
    op.create_check_constraint(
        "ck_pressing_commande_fin_source",
        "pressing_commandes",
        "fin_estimee_source IS NULL OR fin_estimee_source IN ("
        + ", ".join(repr(s) for s in SOURCES)
        + ")",
    )
    op.execute(
        "UPDATE pressing_commandes SET fin_estimee_source = 'affectation' "
        "WHERE fin_estimee IS NOT NULL"
    )

    # --- affectations : interruption de cycle
    op.add_column(
        "pressing_commande_machines",
        sa.Column("interrompue_le", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pressing_commande_machines",
        sa.Column("motif_interruption", sa.String(500), nullable=True),
    )

    # --- paiements : contre-passation
    op.add_column(
        "pressing_paiements",
        sa.Column(
            "annule_paiement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "pressing_paiements.id",
                ondelete="CASCADE",
                name="fk_pressing_paiement_annule",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "pressing_paiements", sa.Column("annule_le", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "pressing_paiements",
        sa.Column(
            "annule_par",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_pressing_paiement_annule_par"),
            nullable=True,
        ),
    )
    op.add_column(
        "pressing_paiements", sa.Column("motif_annulation", sa.String(500), nullable=True)
    )
    op.drop_constraint("ck_pressing_paiement_montant", "pressing_paiements", type_="check")
    op.create_check_constraint(
        "ck_pressing_paiement_montant", "pressing_paiements", "montant <> 0"
    )
    op.create_check_constraint(
        "ck_pressing_paiement_contrepassation",
        "pressing_paiements",
        "(annule_paiement_id IS NULL AND montant > 0) OR "
        "(annule_paiement_id IS NOT NULL AND montant < 0)",
    )
    op.create_index(
        "uq_pressing_paiement_annulation",
        "pressing_paiements",
        ["annule_paiement_id"],
        unique=True,
        postgresql_where=sa.text("annule_paiement_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_pressing_paiement_annulation", table_name="pressing_paiements")
    op.drop_constraint(
        "ck_pressing_paiement_contrepassation", "pressing_paiements", type_="check"
    )
    op.drop_constraint("ck_pressing_paiement_montant", "pressing_paiements", type_="check")
    # NOT VALID : les contre-passations déjà écrites (montant < 0) sont conservées ; la règle
    # « montant > 0 » s'applique aux nouvelles lignes.
    op.execute(
        "ALTER TABLE pressing_paiements ADD CONSTRAINT ck_pressing_paiement_montant "
        "CHECK (montant > 0) NOT VALID"
    )
    op.drop_column("pressing_paiements", "motif_annulation")
    op.drop_column("pressing_paiements", "annule_par")
    op.drop_column("pressing_paiements", "annule_le")
    op.drop_column("pressing_paiements", "annule_paiement_id")
    op.drop_column("pressing_commande_machines", "motif_interruption")
    op.drop_column("pressing_commande_machines", "interrompue_le")
    op.drop_constraint("ck_pressing_commande_fin_source", "pressing_commandes", type_="check")
    op.drop_column("pressing_commandes", "fin_estimee_source")
