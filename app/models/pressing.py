"""Tarification d'un pressing : tarif au kilo, articles à l'unité, combinaisons composées.

Tous les montants sont des entiers en FCFA (pas de centimes). Chaque table porte son
``restaurant_id`` et la même politique de RLS que le reste du projet.
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


def _restaurant_fk():
    return Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )


class PressingTarif(Base):
    """Une ligne par restaurant, créée à la première lecture avec les valeurs par défaut."""

    __tablename__ = "pressing_tarifs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = _restaurant_fk()
    prix_kg = Column(Integer, nullable=False, default=500)
    prix_sechage_kg = Column(Integer, nullable=True)
    arrondi_pas_grammes = Column(Integer, nullable=False, default=1000)
    arrondi_mode = Column(String(10), nullable=False, default="superieur")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("restaurant_id", name="uq_pressing_tarif_restaurant"),
        CheckConstraint("prix_kg >= 0", name="ck_pressing_tarif_prix_kg"),
        CheckConstraint(
            "prix_sechage_kg IS NULL OR prix_sechage_kg >= 0",
            name="ck_pressing_tarif_prix_sechage",
        ),
        CheckConstraint(
            "arrondi_pas_grammes IN (1, 100, 500, 1000)", name="ck_pressing_tarif_pas"
        ),
        CheckConstraint(
            "arrondi_mode IN ('superieur', 'proche')", name="ck_pressing_tarif_mode"
        ),
    )


class PressingArticle(Base):
    __tablename__ = "pressing_articles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = _restaurant_fk()
    nom = Column(String(120), nullable=False)
    prix_unitaire = Column(Integer, nullable=False)
    categorie = Column(String(120), nullable=True)
    actif = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Unicité par restaurant, sans tenir compte de la casse.
        Index(
            "uq_pressing_article_nom",
            "restaurant_id",
            func.lower(nom),
            unique=True,
        ),
        CheckConstraint("prix_unitaire >= 0", name="ck_pressing_article_prix"),
    )


class PressingCombinaison(Base):
    __tablename__ = "pressing_combinaisons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = _restaurant_fk()
    nom = Column(String(120), nullable=False)
    prix = Column(Integer, nullable=False)
    actif = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "uq_pressing_combinaison_nom",
            "restaurant_id",
            func.lower(nom),
            unique=True,
        ),
        CheckConstraint("prix >= 0", name="ck_pressing_combinaison_prix"),
    )


class PressingCombinaisonLigne(Base):
    __tablename__ = "pressing_combinaison_lignes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = _restaurant_fk()
    combinaison_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pressing_combinaisons.id", ondelete="CASCADE"),
        nullable=False,
    )
    # RESTRICT : un article n'est jamais supprimé physiquement (DELETE = désactivation).
    article_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pressing_articles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantite = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("idx_pressing_ligne_restaurant", "restaurant_id"),
        Index("idx_pressing_ligne_combinaison", "combinaison_id"),
        Index("idx_pressing_ligne_article", "article_id"),
        UniqueConstraint(
            "combinaison_id", "article_id", name="uq_pressing_ligne_article"
        ),
        CheckConstraint("quantite >= 1", name="ck_pressing_ligne_quantite"),
    )


# ----------------------------------------------------------------------------------------
# Espace pressing : zones, machines (lave-linge / sèche-linge), événements, maintenances.
# ----------------------------------------------------------------------------------------
ZONE_TYPES = ("lavage", "sechage", "reception", "attente", "pliage", "stockage", "autre")
MACHINE_CATEGORIES = ("lave_linge", "seche_linge")
MACHINE_FONCTIONNEMENTS = ("semi_automatique", "automatique", "autre")
MACHINE_ETATS = (
    "libre",
    "reservee",
    "en_cycle",
    "cycle_termine",
    "attente_dechargement",
    "maintenance",
    "hors_service",
)
EVENEMENT_TYPES = ("etat_change", "maintenance", "note")
MAINTENANCE_TYPES = ("entretien", "panne", "reparation")


def _in_list(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class PressingZone(Base):
    """Zone rectangulaire du plan du pressing (pourcentages 0-100 de la largeur / hauteur)."""

    __tablename__ = "pressing_zones"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = _restaurant_fk()
    nom = Column(String(120), nullable=False)
    type = Column(String(20), nullable=False, default="autre")
    couleur = Column(String(7), nullable=False, default="#94A3B8")
    x = Column(Numeric(5, 2), nullable=False)
    y = Column(Numeric(5, 2), nullable=False)
    w = Column(Numeric(5, 2), nullable=False)
    h = Column(Numeric(5, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_pressing_zone_nom", "restaurant_id", func.lower(nom), unique=True),
        CheckConstraint(_in_list("type", ZONE_TYPES), name="ck_pressing_zone_type"),
        CheckConstraint("couleur ~ '^#[0-9A-Fa-f]{6}$'", name="ck_pressing_zone_couleur"),
        CheckConstraint(
            "x >= 0 AND y >= 0 AND w > 0 AND h > 0 AND x + w <= 100 AND y + h <= 100",
            name="ck_pressing_zone_geometrie",
        ),
    )


class PressingMachine(Base):
    __tablename__ = "pressing_machines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = _restaurant_fk()
    nom = Column(String(120), nullable=False)
    categorie = Column(String(20), nullable=False)
    marque = Column(String(120), nullable=True)
    modele = Column(String(120), nullable=True)
    numero_serie = Column(String(120), nullable=True)
    type_fonctionnement = Column(String(20), nullable=False, default="automatique")
    capacite_kg = Column(Numeric(6, 2), nullable=False)
    # [{nom, duree_min, types_linge: [..], intervention_humaine, etapes?: [{nom, duree_min}]}]
    programmes = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # RESTRICT : une zone qui porte des machines ne se supprime pas.
    zone_id = Column(
        UUID(as_uuid=True), ForeignKey("pressing_zones.id", ondelete="RESTRICT"), nullable=True
    )
    position_x = Column(Numeric(5, 2), nullable=True)
    position_y = Column(Numeric(5, 2), nullable=True)
    conso_electrique_kwh_cycle = Column(Numeric(8, 3), nullable=True)
    conso_eau_litres_cycle = Column(Numeric(8, 2), nullable=True)
    date_mise_en_service = Column(Date, nullable=True)
    remarques = Column(Text, nullable=True)
    contraintes = Column(Text, nullable=True)
    etat_operationnel = Column(String(25), nullable=False, default="libre")
    # Posés par le lot « commandes » ; libérés (SET NULL) si la commande disparaît.
    commande_courante_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pressing_commandes.id", ondelete="SET NULL"),
        nullable=True,
    )
    fin_estimee = Column(DateTime(timezone=True), nullable=True)
    actif = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_pressing_machine_nom", "restaurant_id", func.lower(nom), unique=True),
        Index(
            "uq_pressing_machine_serie",
            "restaurant_id",
            func.lower(numero_serie),
            unique=True,
            postgresql_where=text("numero_serie IS NOT NULL"),
        ),
        Index("idx_pressing_machine_etat", "restaurant_id", "etat_operationnel"),
        Index("idx_pressing_machine_zone", "zone_id"),
        CheckConstraint(
            _in_list("categorie", MACHINE_CATEGORIES), name="ck_pressing_machine_categorie"
        ),
        CheckConstraint(
            _in_list("type_fonctionnement", MACHINE_FONCTIONNEMENTS),
            name="ck_pressing_machine_fonctionnement",
        ),
        CheckConstraint(
            _in_list("etat_operationnel", MACHINE_ETATS), name="ck_pressing_machine_etat"
        ),
        CheckConstraint(
            "capacite_kg > 0 AND capacite_kg <= 200", name="ck_pressing_machine_capacite"
        ),
        CheckConstraint(
            "(position_x IS NULL OR (position_x >= 0 AND position_x <= 100)) AND "
            "(position_y IS NULL OR (position_y >= 0 AND position_y <= 100))",
            name="ck_pressing_machine_position",
        ),
        CheckConstraint(
            "(conso_electrique_kwh_cycle IS NULL OR conso_electrique_kwh_cycle >= 0) AND "
            "(conso_eau_litres_cycle IS NULL OR conso_eau_litres_cycle >= 0)",
            name="ck_pressing_machine_conso",
        ),
    )


class PressingMachineEvenement(Base):
    """Journal métier d'une machine (affiché dans l'historique) : changements d'état, maintenances, notes."""

    __tablename__ = "pressing_machine_evenements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = _restaurant_fk()
    machine_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pressing_machines.id", ondelete="CASCADE"),
        nullable=False,
    )
    type = Column(String(20), nullable=False)
    ancien_etat = Column(String(25), nullable=True)
    nouvel_etat = Column(String(25), nullable=True)
    motif = Column(Text, nullable=True)
    # Maintenance à l'origine de l'événement (aucune clé étrangère : l'historique se garde).
    maintenance_id = Column(UUID(as_uuid=True), nullable=True)
    auteur_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    date_evenement = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_pressing_evenement_machine", "machine_id", "date_evenement"),
        Index("idx_pressing_evenement_restaurant", "restaurant_id"),
        CheckConstraint(_in_list("type", EVENEMENT_TYPES), name="ck_pressing_evenement_type"),
    )


class PressingMaintenance(Base):
    __tablename__ = "pressing_maintenances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = _restaurant_fk()
    machine_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pressing_machines.id", ondelete="CASCADE"),
        nullable=False,
    )
    type = Column(String(20), nullable=False)
    description = Column(Text, nullable=False)
    debut = Column(DateTime(timezone=True), nullable=False)
    fin = Column(DateTime(timezone=True), nullable=True)
    duree_estimee_min = Column(Integer, nullable=True)
    auteur_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_pressing_maintenance_machine", "machine_id", "debut"),
        Index("idx_pressing_maintenance_restaurant", "restaurant_id"),
        CheckConstraint(
            _in_list("type", MAINTENANCE_TYPES), name="ck_pressing_maintenance_type"
        ),
        CheckConstraint("fin IS NULL OR fin >= debut", name="ck_pressing_maintenance_dates"),
        CheckConstraint(
            "duree_estimee_min IS NULL OR duree_estimee_min > 0",
            name="ck_pressing_maintenance_duree",
        ),
    )


# ----------------------------------------------------------------------------------------
# Commandes de pressing : commande, lignes figées, affectations de machines, paiements, clôtures.
# ----------------------------------------------------------------------------------------
COMMANDE_STATUTS = (
    "recue",
    "en_attente_machine",
    "en_lavage",
    "attente_sechage",
    "en_sechage",
    "pret",
    "livre",
    "annulee",
)
PAIEMENT_MODES = ("especes", "mobile_money", "carte", "autre")
LIGNE_TYPES = ("lavage", "sechage", "article", "combinaison")
ETAPES = ("lavage", "sechage")
# Origine de ``pressing_commandes.fin_estimee`` (c'est toujours une ESTIMATION).
FIN_ESTIMEE_SOURCES = ("estimation_initiale", "affectation", "cycle")


class PressingCommande(Base):
    __tablename__ = "pressing_commandes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = _restaurant_fk()
    numero = Column(String(30), nullable=False)
    client_nom = Column(String(120), nullable=False)
    client_telephone = Column(String(20), nullable=True)
    poids_grams = Column(Integer, nullable=True)
    poids_facturable_grams = Column(Integer, nullable=True)
    lavage = Column(Boolean, nullable=False, default=True)
    sechage = Column(Boolean, nullable=False, default=False)
    instructions = Column(String(500), nullable=True)
    types_linge = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    statut = Column(String(25), nullable=False, default="recue")
    # Étape machine courante : « lavage » / « sechage », NULL sans machine (articles seuls,
    # commande prête, livrée ou annulée).
    etape = Column(String(10), nullable=True)
    sous_total = Column(Integer, nullable=False, default=0)
    remise_fcfa = Column(Integer, nullable=False, default=0)
    montant_total = Column(Integer, nullable=False, default=0)
    montant_paye = Column(Integer, nullable=False, default=0)
    cree_le = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    pris_en_charge_le = Column(DateTime(timezone=True), nullable=True)
    pret_le = Column(DateTime(timezone=True), nullable=True)
    livre_le = Column(DateTime(timezone=True), nullable=True)
    debut_prevu = Column(DateTime(timezone=True), nullable=True)
    fin_estimee = Column(DateTime(timezone=True), nullable=True)
    # estimation_initiale (création) | affectation | cycle ; NULL quand fin_estimee est NULL.
    fin_estimee_source = Column(String(25), nullable=True)
    fin_reelle = Column(DateTime(timezone=True), nullable=True)
    annule_le = Column(DateTime(timezone=True), nullable=True)
    motif_annulation = Column(Text, nullable=True)
    auteur_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("restaurant_id", "numero", name="uq_pressing_commande_numero"),
        CheckConstraint(
            "fin_estimee_source IS NULL OR " + _in_list("fin_estimee_source", FIN_ESTIMEE_SOURCES),
            name="ck_pressing_commande_fin_source",
        ),
        Index("idx_pressing_commande_statut", "restaurant_id", "statut"),
        Index("idx_pressing_commande_cree", "restaurant_id", "cree_le"),
        Index("idx_pressing_commande_telephone", "restaurant_id", "client_telephone"),
        CheckConstraint(_in_list("statut", COMMANDE_STATUTS), name="ck_pressing_commande_statut"),
        CheckConstraint(
            "etape IS NULL OR etape IN ('lavage', 'sechage')", name="ck_pressing_commande_etape"
        ),
        CheckConstraint(
            "poids_grams IS NULL OR (poids_grams >= 1 AND poids_grams <= 1000000)",
            name="ck_pressing_commande_poids",
        ),
        CheckConstraint(
            "sous_total >= 0 AND remise_fcfa >= 0 AND montant_total >= 0",
            name="ck_pressing_commande_montants",
        ),
        CheckConstraint(
            "montant_paye >= 0 AND montant_paye <= montant_total",
            name="ck_pressing_commande_paye",
        ),
    )


class PressingCommandeLigne(Base):
    """Ligne figée au moment de la création : le tarif peut changer sans toucher la commande."""

    __tablename__ = "pressing_commande_lignes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = _restaurant_fk()
    commande_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pressing_commandes.id", ondelete="CASCADE"),
        nullable=False,
    )
    position = Column(Integer, nullable=False, default=0)
    type = Column(String(15), nullable=False)
    libelle = Column(String(160), nullable=False)
    quantite = Column(Numeric(10, 3), nullable=False)
    prix_unitaire = Column(Integer, nullable=False)
    montant = Column(Integer, nullable=False)

    __table_args__ = (
        Index("idx_pressing_ligne_commande", "commande_id"),
        Index("idx_pressing_commande_ligne_restaurant", "restaurant_id"),
        CheckConstraint(_in_list("type", LIGNE_TYPES), name="ck_pressing_commande_ligne_type"),
        CheckConstraint(
            "montant >= 0 AND prix_unitaire >= 0", name="ck_pressing_commande_ligne_montant"
        ),
    )


class PressingCommandeMachine(Base):
    """Affectation d'une machine à une commande pour une étape (lavage ou séchage)."""

    __tablename__ = "pressing_commande_machines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = _restaurant_fk()
    commande_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pressing_commandes.id", ondelete="CASCADE"),
        nullable=False,
    )
    machine_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pressing_machines.id", ondelete="CASCADE"),
        nullable=False,
    )
    etape = Column(String(10), nullable=False)
    charge_g = Column(Integer, nullable=False)
    programme = Column(String(80), nullable=True)
    duree_min = Column(Integer, nullable=True)
    intervention_humaine = Column(Boolean, nullable=False, default=False)
    debut_prevu = Column(DateTime(timezone=True), nullable=True)
    fin_prevue = Column(DateTime(timezone=True), nullable=True)
    debut_reel = Column(DateTime(timezone=True), nullable=True)
    fin_reelle = Column(DateTime(timezone=True), nullable=True)
    dechargee_le = Column(DateTime(timezone=True), nullable=True)
    # Cycle interrompu (panne, coupure, erreur de programme) : fin_reelle = interrompue_le.
    interrompue_le = Column(DateTime(timezone=True), nullable=True)
    motif_interruption = Column(String(500), nullable=True)
    # Faux quand l'affectation est abandonnée (annulation de la commande, libération d'une
    # réservation, cycle interrompu dont la charge n'a pas été traitée) : sa charge redevient
    # « restante » pour l'étape.
    actif = Column(Boolean, nullable=False, default=True)
    cree_le = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_pressing_cm_commande", "commande_id"),
        Index("idx_pressing_cm_machine", "machine_id", "debut_reel"),
        Index("idx_pressing_cm_restaurant", "restaurant_id", "fin_reelle"),
        # Une machine n'a qu'une affectation vivante à la fois : garde-fou contre la double affectation.
        Index(
            "uq_pressing_cm_machine_vivante",
            "machine_id",
            unique=True,
            postgresql_where=text("actif AND fin_reelle IS NULL"),
        ),
        CheckConstraint("etape IN ('lavage', 'sechage')", name="ck_pressing_cm_etape"),
        CheckConstraint("charge_g > 0", name="ck_pressing_cm_charge"),
    )


class PressingPaiement(Base):
    """Encaissement (montant > 0) ou contre-passation d'un encaissement (montant < 0,
    ``annule_paiement_id`` renseigné) : on n'efface jamais un paiement, on l'annule."""

    __tablename__ = "pressing_paiements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = _restaurant_fk()
    commande_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pressing_commandes.id", ondelete="CASCADE"),
        nullable=False,
    )
    montant = Column(Integer, nullable=False)
    mode = Column(String(15), nullable=False)
    reference = Column(String(80), nullable=True)
    cree_le = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    auteur_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Contre-passation : paiement qu'elle annule (au plus une contre-passation par paiement).
    annule_paiement_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pressing_paiements.id", ondelete="CASCADE"),
        nullable=True,
    )
    # Paiement annulé : quand, par qui, pourquoi.
    annule_le = Column(DateTime(timezone=True), nullable=True)
    annule_par = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    motif_annulation = Column(String(500), nullable=True)

    __table_args__ = (
        Index("idx_pressing_paiement_commande", "commande_id"),
        Index("idx_pressing_paiement_restaurant", "restaurant_id", "cree_le"),
        Index(
            "uq_pressing_paiement_annulation",
            "annule_paiement_id",
            unique=True,
            postgresql_where=text("annule_paiement_id IS NOT NULL"),
        ),
        CheckConstraint("montant <> 0", name="ck_pressing_paiement_montant"),
        CheckConstraint(
            "(annule_paiement_id IS NULL AND montant > 0) OR "
            "(annule_paiement_id IS NOT NULL AND montant < 0)",
            name="ck_pressing_paiement_contrepassation",
        ),
        CheckConstraint(_in_list("mode", PAIEMENT_MODES), name="ck_pressing_paiement_mode"),
    )


class PressingCloture(Base):
    """Clôture de caisse : une seule par jour et par restaurant."""

    __tablename__ = "pressing_clotures"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = _restaurant_fk()
    date = Column(Date, nullable=False)
    total_encaisse = Column(Integer, nullable=False)
    especes_attendues = Column(Integer, nullable=False)
    montant_compte = Column(Integer, nullable=False)
    ecart = Column(Integer, nullable=False)
    auteur_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cree_le = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("restaurant_id", "date", name="uq_pressing_cloture_jour"),
        CheckConstraint("montant_compte >= 0", name="ck_pressing_cloture_compte"),
    )
