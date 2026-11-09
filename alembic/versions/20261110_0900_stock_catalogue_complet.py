"""Carte et stock : gestion de stock complète, catalogue archivable et sans doublon.

Stock
* ``stock_mouvements`` devient un journal : ``restaurant_id`` (rempli depuis le composant),
  ``delta`` signé, ``stock_apres``, ``motif``, ``acteur_user_id``, ``lot_id``, ``cout_unitaire``.
  La politique RLS passe de la jointure sur ``composants`` à la colonne ``restaurant_id`` directe.
* ``composants`` : ``code``, ``categorie``, ``cout_unitaire``, ``cout_maj_le``, ``suit_peremption``.
* ``stock_composants.stock_cible`` (niveau cible de réapprovisionnement).
* ``plat_composants.rendement`` (perte de préparation).
* Garde d'idempotence : ``commandes.stock_consomme_at``, ``ros_orders.stock_restitue_at``.
* Nouvelles tables (RLS forcée) : ``unites_conversion``, ``fournisseurs``, ``composant_fournisseurs``,
  ``stock_lots``, ``bons_commande`` (+ lignes), ``receptions`` (+ lignes), ``inventaires`` (+ lignes).

Catalogue
* Archivage : ``deleted_at`` ajouté à ``combinaisons`` et ``menu_categories``.
* ``plats`` / ``boissons`` : ``ordre``, ``taux_tva`` ; ``boissons.photo_url`` ; ``combinaisons.photo_url`` et
  ``taux_tva`` ; ``menus.valide_du`` / ``valide_au`` / ``jours_semaine``.
* ``catalogue_historique_prix`` (RLS forcée).
* Unicité du nom par restaurant (insensible à la casse, hors archivés) sur plats, boissons, composants,
  menus, combinaisons et fournisseurs. Les doublons existants sont renommés (« Nom (2) ») avant la création
  des index, sans rien supprimer.

Les clés étrangères ``stock_mouvements`` / ``plat_composants`` vers ``composants`` restent en CASCADE :
l'application n'efface jamais un composant (archivage), et un RESTRICT casserait la suppression en cascade
d'un restaurant. Le garde-fou est dans le service.

Revision ID: 20261110_0900
Revises: 20261109_0900
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261110_0900"
down_revision = "20261109_0900"
branch_labels = None
depends_on = None

PREDICATE = "((SELECT app_is_platform_admin()) OR restaurant_id = (SELECT app_current_tenant_id()))"

NEW_TABLES = (
    "unites_conversion",
    "fournisseurs",
    "composant_fournisseurs",
    "stock_lots",
    "bons_commande",
    "bons_commande_lignes",
    "receptions",
    "reception_lignes",
    "inventaires",
    "inventaire_lignes",
    "catalogue_historique_prix",
)

# (table, colonne du nom) : unicité insensible à la casse parmi les lignes non archivées.
UNIQUE_NAMES = (
    ("plats", "nom"),
    ("boissons", "nom"),
    ("composants", "nom"),
    ("combinaisons", "nom"),
    ("menus", "name"),
)


def _uuid_pk():
    return sa.Column(
        "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _restaurant():
    return sa.Column(
        "restaurant_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )


def _fk(name, target, ondelete, nullable=True):
    return sa.Column(
        name, postgresql.UUID(as_uuid=True), sa.ForeignKey(target, ondelete=ondelete), nullable=nullable
    )


def _tstz(name, nullable=True, default_now=False):
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if default_now else None,
    )


def upgrade() -> None:
    # Les tables du tenant sont sous RLS forcée : sans ce contexte (limité à la transaction), les
    # remplissages et dédoublonnages ci-dessous ne verraient aucune ligne.
    op.execute("SELECT set_config('app.is_platform_admin', 'true', true)")

    # --- Colonnes ajoutées aux tables existantes ---------------------------------------------
    op.add_column("menus", sa.Column("valide_du", sa.Date(), nullable=True))
    op.add_column("menus", sa.Column("valide_au", sa.Date(), nullable=True))
    op.add_column("menus", sa.Column("jours_semaine", postgresql.ARRAY(sa.SmallInteger()), nullable=True))
    op.add_column("menu_categories", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("composants", sa.Column("code", sa.String(length=40), nullable=True))
    op.add_column("composants", sa.Column("categorie", sa.String(length=60), nullable=True))
    op.add_column("composants", sa.Column("cout_unitaire", sa.Numeric(14, 4), nullable=True))
    op.add_column("composants", sa.Column("cout_maj_le", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "composants",
        sa.Column("suit_peremption", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.add_column("combinaisons", sa.Column("photo_url", sa.String(length=500), nullable=True))
    op.add_column("combinaisons", sa.Column("taux_tva", sa.Numeric(5, 2), nullable=True))
    op.add_column("combinaisons", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column(
        "stock_composants",
        sa.Column("stock_cible", sa.Numeric(12, 3), nullable=False, server_default=sa.text("0")),
    )
    op.create_check_constraint("check_stock_cible_positive", "stock_composants", "stock_cible >= 0")

    op.add_column("plats", sa.Column("ordre", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("plats", sa.Column("taux_tva", sa.Numeric(5, 2), nullable=True))
    op.add_column("boissons", sa.Column("photo_url", sa.String(length=500), nullable=True))
    op.add_column("boissons", sa.Column("ordre", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("boissons", sa.Column("taux_tva", sa.Numeric(5, 2), nullable=True))

    op.add_column(
        "plat_composants",
        sa.Column("rendement", sa.Numeric(5, 4), nullable=False, server_default=sa.text("1")),
    )
    op.create_check_constraint(
        "check_plat_composant_rendement", "plat_composants", "rendement > 0 AND rendement <= 1"
    )

    op.add_column("commandes", sa.Column("stock_consomme_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ros_orders", sa.Column("stock_restitue_at", sa.DateTime(timezone=True), nullable=True))

    # --- Nouvelles tables (avant le journal : stock_mouvements référence stock_lots) -----------
    op.create_table(
        "unites_conversion",
        _uuid_pk(),
        _restaurant(),
        _fk("composant_id", "composants.id", "CASCADE", nullable=False),
        sa.Column("unite", sa.String(length=20), nullable=False),
        sa.Column("facteur", sa.Numeric(14, 6), nullable=False),
        _tstz("created_at", default_now=True),
        sa.UniqueConstraint("composant_id", "unite", name="uq_unite_conversion_composant_unite"),
        sa.CheckConstraint("facteur > 0", name="check_unite_conversion_facteur_positif"),
    )
    op.create_index("idx_unite_conversion_restaurant", "unites_conversion", ["restaurant_id", "composant_id"])

    op.create_table(
        "fournisseurs",
        _uuid_pk(),
        _restaurant(),
        sa.Column("nom", sa.String(length=255), nullable=False),
        sa.Column("contact", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("telephone", sa.String(length=30), nullable=True),
        sa.Column("adresse", sa.Text(), nullable=True),
        sa.Column("delai_jours", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column("conditions_paiement", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _tstz("deleted_at"),
        _tstz("created_at", default_now=True),
        _tstz("updated_at", default_now=True),
        sa.CheckConstraint("delai_jours >= 0", name="check_fournisseur_delai_positif"),
    )
    op.create_index("idx_fournisseur_restaurant", "fournisseurs", ["restaurant_id", "actif"])

    op.create_table(
        "composant_fournisseurs",
        _uuid_pk(),
        _restaurant(),
        _fk("composant_id", "composants.id", "CASCADE", nullable=False),
        _fk("fournisseur_id", "fournisseurs.id", "CASCADE", nullable=False),
        sa.Column("reference", sa.String(length=60), nullable=True),
        sa.Column("prix_unitaire", sa.Numeric(14, 4), nullable=True),
        sa.Column("conditionnement", sa.Numeric(12, 3), nullable=True),
        sa.Column("quantite_minimum", sa.Numeric(12, 3), nullable=True),
        sa.Column("principal", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _tstz("created_at", default_now=True),
        _tstz("updated_at", default_now=True),
        sa.UniqueConstraint("composant_id", "fournisseur_id", name="uq_composant_fournisseur"),
        sa.CheckConstraint(
            "prix_unitaire IS NULL OR prix_unitaire >= 0", name="check_composant_fournisseur_prix"
        ),
    )
    op.create_index(
        "idx_composant_fournisseur_restaurant", "composant_fournisseurs", ["restaurant_id", "fournisseur_id"]
    )

    op.create_table(
        "stock_lots",
        _uuid_pk(),
        _restaurant(),
        _fk("composant_id", "composants.id", "CASCADE", nullable=False),
        sa.Column("numero", sa.String(length=60), nullable=True),
        sa.Column("quantite_initiale", sa.Numeric(12, 3), nullable=False),
        sa.Column("quantite_restante", sa.Numeric(12, 3), nullable=False),
        sa.Column("date_peremption", sa.Date(), nullable=True),
        _tstz("recu_le", default_now=True),
        _fk("fournisseur_id", "fournisseurs.id", "SET NULL"),
        sa.Column("cout_unitaire", sa.Numeric(14, 4), nullable=True),
        _tstz("created_at", default_now=True),
        sa.CheckConstraint("quantite_restante >= 0", name="check_stock_lot_restante_positive"),
        sa.CheckConstraint("quantite_initiale > 0", name="check_stock_lot_initiale_positive"),
    )
    op.create_index(
        "idx_stock_lot_composant_peremption",
        "stock_lots",
        ["restaurant_id", "composant_id", "date_peremption"],
    )

    op.create_table(
        "bons_commande",
        _uuid_pk(),
        _restaurant(),
        sa.Column("numero", sa.String(length=30), nullable=False),
        _fk("fournisseur_id", "fournisseurs.id", "RESTRICT", nullable=False),
        sa.Column("statut", sa.String(length=20), nullable=False, server_default="brouillon"),
        sa.Column("date_livraison_prevue", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("total_estime", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
        _fk("cree_par", "users.id", "SET NULL"),
        _tstz("envoye_le"),
        _tstz("cloture_le"),
        _tstz("created_at", default_now=True),
        _tstz("updated_at", default_now=True),
        sa.UniqueConstraint("restaurant_id", "numero", name="uq_bon_commande_numero"),
        sa.CheckConstraint(
            "statut IN ('brouillon', 'envoye', 'recu_partiel', 'recu', 'annule')",
            name="check_bon_commande_statut",
        ),
    )
    op.create_index(
        "idx_bon_commande_restaurant_statut", "bons_commande", ["restaurant_id", "statut", "created_at"]
    )

    op.create_table(
        "bons_commande_lignes",
        _uuid_pk(),
        _restaurant(),
        _fk("bon_id", "bons_commande.id", "CASCADE", nullable=False),
        _fk("composant_id", "composants.id", "RESTRICT", nullable=False),
        sa.Column("quantite_commandee", sa.Numeric(12, 3), nullable=False),
        sa.Column("quantite_recue", sa.Numeric(12, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("prix_unitaire", sa.Numeric(14, 4), nullable=True),
        _tstz("created_at", default_now=True),
        sa.UniqueConstraint("bon_id", "composant_id", name="uq_bon_commande_ligne_composant"),
        sa.CheckConstraint("quantite_commandee > 0", name="check_bon_ligne_commandee_positive"),
        sa.CheckConstraint("quantite_recue >= 0", name="check_bon_ligne_recue_positive"),
    )
    op.create_index("idx_bon_commande_ligne_restaurant", "bons_commande_lignes", ["restaurant_id", "bon_id"])

    op.create_table(
        "receptions",
        _uuid_pk(),
        _restaurant(),
        _fk("bon_id", "bons_commande.id", "SET NULL"),
        _fk("fournisseur_id", "fournisseurs.id", "SET NULL"),
        sa.Column("numero_bl", sa.String(length=60), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        _fk("recu_par", "users.id", "SET NULL"),
        _tstz("recu_le", default_now=True),
    )
    op.create_index("idx_reception_restaurant_date", "receptions", ["restaurant_id", "recu_le"])

    op.create_table(
        "reception_lignes",
        _uuid_pk(),
        _restaurant(),
        _fk("reception_id", "receptions.id", "CASCADE", nullable=False),
        _fk("composant_id", "composants.id", "RESTRICT", nullable=False),
        sa.Column("quantite", sa.Numeric(12, 3), nullable=False),
        sa.Column("prix_unitaire", sa.Numeric(14, 4), nullable=True),
        sa.Column("lot_numero", sa.String(length=60), nullable=True),
        sa.Column("date_peremption", sa.Date(), nullable=True),
        _fk("lot_id", "stock_lots.id", "SET NULL"),
        sa.CheckConstraint("quantite > 0", name="check_reception_ligne_quantite_positive"),
    )
    op.create_index("idx_reception_ligne_restaurant", "reception_lignes", ["restaurant_id", "reception_id"])

    op.create_table(
        "inventaires",
        _uuid_pk(),
        _restaurant(),
        sa.Column("numero", sa.String(length=30), nullable=False),
        sa.Column("statut", sa.String(length=20), nullable=False, server_default="ouvert"),
        sa.Column("note", sa.Text(), nullable=True),
        _fk("cree_par", "users.id", "SET NULL"),
        _fk("valide_par", "users.id", "SET NULL"),
        _tstz("valide_le"),
        _tstz("created_at", default_now=True),
        sa.UniqueConstraint("restaurant_id", "numero", name="uq_inventaire_numero"),
        sa.CheckConstraint("statut IN ('ouvert', 'valide', 'annule')", name="check_inventaire_statut"),
    )
    op.create_index("idx_inventaire_restaurant", "inventaires", ["restaurant_id", "created_at"])
    op.create_index(
        "uq_inventaire_un_seul_ouvert",
        "inventaires",
        ["restaurant_id"],
        unique=True,
        postgresql_where=sa.text("statut = 'ouvert'"),
    )

    op.create_table(
        "inventaire_lignes",
        _uuid_pk(),
        _restaurant(),
        _fk("inventaire_id", "inventaires.id", "CASCADE", nullable=False),
        _fk("composant_id", "composants.id", "RESTRICT", nullable=False),
        sa.Column("quantite_theorique", sa.Numeric(12, 3), nullable=False),
        sa.Column("quantite_comptee", sa.Numeric(12, 3), nullable=True),
        sa.Column("cout_unitaire", sa.Numeric(14, 4), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("inventaire_id", "composant_id", name="uq_inventaire_ligne_composant"),
        sa.CheckConstraint(
            "quantite_comptee IS NULL OR quantite_comptee >= 0", name="check_inventaire_comptee_positive"
        ),
    )
    op.create_index("idx_inventaire_ligne_restaurant", "inventaire_lignes", ["restaurant_id", "inventaire_id"])

    op.create_table(
        "catalogue_historique_prix",
        _uuid_pk(),
        _restaurant(),
        sa.Column("entite", sa.String(length=20), nullable=False),
        sa.Column("entite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ancien_prix", sa.Numeric(10, 2), nullable=True),
        sa.Column("nouveau_prix", sa.Numeric(10, 2), nullable=False),
        _fk("auteur_id", "users.id", "SET NULL"),
        _tstz("created_at", default_now=True),
        sa.CheckConstraint("entite IN ('plat', 'boisson', 'combinaison')", name="check_catalogue_prix_entite"),
    )
    op.create_index(
        "idx_catalogue_prix_entite",
        "catalogue_historique_prix",
        ["restaurant_id", "entite", "entite_id", "created_at"],
    )

    # --- Journal des mouvements ---------------------------------------------------------------
    op.add_column("stock_mouvements", sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(
        "UPDATE stock_mouvements m SET restaurant_id = c.restaurant_id "
        "FROM composants c WHERE c.id = m.composant_id"
    )
    op.alter_column("stock_mouvements", "restaurant_id", nullable=False)
    op.create_foreign_key(
        "fk_stock_mouvements_restaurant", "stock_mouvements", "restaurants", ["restaurant_id"], ["id"],
        ondelete="CASCADE",
    )
    op.add_column("stock_mouvements", sa.Column("delta", sa.Numeric(12, 3), nullable=True))
    op.add_column("stock_mouvements", sa.Column("stock_apres", sa.Numeric(12, 3), nullable=True))
    op.add_column("stock_mouvements", sa.Column("motif", sa.String(length=40), nullable=True))
    op.add_column("stock_mouvements", sa.Column("acteur_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("stock_mouvements", sa.Column("lot_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("stock_mouvements", sa.Column("cout_unitaire", sa.Numeric(14, 4), nullable=True))
    op.create_foreign_key(
        "fk_stock_mouvements_acteur", "stock_mouvements", "users", ["acteur_user_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_stock_mouvements_lot", "stock_mouvements", "stock_lots", ["lot_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("idx_stock_mouvement_restaurant_date", "stock_mouvements", ["restaurant_id", "created_at"])
    # Historique existant : delta déduit du type quand il est sans ambiguïté ; sinon laissé vide.
    op.execute(
        "UPDATE stock_mouvements SET delta = CASE "
        "WHEN lower(type) IN ('entree', 'in', 'restock', 'retour') THEN quantite "
        "WHEN lower(type) IN ('sortie', 'out', 'perte', 'consommation') THEN -quantite "
        "ELSE NULL END"
    )

    # --- RLS : politique directe sur restaurant_id --------------------------------------------
    op.execute("DROP POLICY IF EXISTS stock_mouvements_tenant_isolation ON stock_mouvements")
    op.execute(
        f"CREATE POLICY stock_mouvements_tenant_isolation ON stock_mouvements "
        f"FOR ALL USING ({PREDICATE}) WITH CHECK ({PREDICATE})"
    )
    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"FOR ALL USING ({PREDICATE}) WITH CHECK ({PREDICATE})"
        )

    # --- Unicité des noms : renommer les doublons, puis index uniques partiels ----------------
    for table, column in UNIQUE_NAMES:
        op.execute(
            f"""
            UPDATE {table} AS t
            SET {column} = left(t.{column}, 240) || ' (' || r.rn || ')'
            FROM (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY restaurant_id, lower({column}) ORDER BY created_at, id
                       ) AS rn
                FROM {table}
                WHERE deleted_at IS NULL
            ) AS r
            WHERE t.id = r.id AND r.rn > 1
            """
        )
        op.execute(
            f"CREATE UNIQUE INDEX uq_{table}_restaurant_nom ON {table} (restaurant_id, lower({column})) "
            f"WHERE deleted_at IS NULL"
        )
    op.execute(
        "CREATE UNIQUE INDEX uq_fournisseurs_restaurant_nom ON fournisseurs (restaurant_id, lower(nom)) "
        "WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_fournisseurs_restaurant_nom")
    for table, _column in reversed(UNIQUE_NAMES):
        op.execute(f"DROP INDEX IF EXISTS uq_{table}_restaurant_nom")

    for table in reversed(NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.execute("DROP POLICY IF EXISTS stock_mouvements_tenant_isolation ON stock_mouvements")
    op.execute(
        "CREATE POLICY stock_mouvements_tenant_isolation ON stock_mouvements FOR ALL "
        "USING ((SELECT app_is_platform_admin()) OR EXISTS (SELECT 1 FROM composants c "
        "WHERE c.id = stock_mouvements.composant_id AND c.restaurant_id = (SELECT app_current_tenant_id()))) "
        "WITH CHECK ((SELECT app_is_platform_admin()) OR EXISTS (SELECT 1 FROM composants c "
        "WHERE c.id = stock_mouvements.composant_id AND c.restaurant_id = (SELECT app_current_tenant_id())))"
    )

    op.drop_index("idx_stock_mouvement_restaurant_date", table_name="stock_mouvements")
    op.drop_constraint("fk_stock_mouvements_lot", "stock_mouvements", type_="foreignkey")
    op.drop_constraint("fk_stock_mouvements_acteur", "stock_mouvements", type_="foreignkey")
    op.drop_constraint("fk_stock_mouvements_restaurant", "stock_mouvements", type_="foreignkey")
    for column in ("cout_unitaire", "lot_id", "acteur_user_id", "motif", "stock_apres", "delta", "restaurant_id"):
        op.drop_column("stock_mouvements", column)

    for table in (
        "catalogue_historique_prix",
        "inventaire_lignes",
        "inventaires",
        "reception_lignes",
        "receptions",
        "bons_commande_lignes",
        "bons_commande",
        "stock_lots",
        "composant_fournisseurs",
        "fournisseurs",
        "unites_conversion",
    ):
        op.drop_table(table)

    op.drop_column("ros_orders", "stock_restitue_at")
    op.drop_column("commandes", "stock_consomme_at")
    op.drop_constraint("check_plat_composant_rendement", "plat_composants", type_="check")
    op.drop_column("plat_composants", "rendement")
    for column in ("taux_tva", "ordre", "photo_url"):
        op.drop_column("boissons", column)
    for column in ("taux_tva", "ordre"):
        op.drop_column("plats", column)
    op.drop_constraint("check_stock_cible_positive", "stock_composants", type_="check")
    op.drop_column("stock_composants", "stock_cible")
    for column in ("deleted_at", "taux_tva", "photo_url"):
        op.drop_column("combinaisons", column)
    for column in ("suit_peremption", "cout_maj_le", "cout_unitaire", "categorie", "code"):
        op.drop_column("composants", column)
    op.drop_column("menu_categories", "deleted_at")
    for column in ("jours_semaine", "valide_au", "valide_du"):
        op.drop_column("menus", column)
