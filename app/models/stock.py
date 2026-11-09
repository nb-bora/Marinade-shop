"""Gestion de stock complète : unités, lots, fournisseurs, achats, réceptions, inventaires, prix.

Toutes les tables portent ``restaurant_id`` et la RLS forcée (voir la migration 20261110_0900).
Les quantités sont en ``Numeric(12, 3)`` dans l'unité de stock du composant (``composants.stock_unite``) ;
les prix unitaires sont en ``Numeric(14, 4)`` par unité de stock, les montants en ``Numeric(14, 2)``.
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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


def _pk():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _restaurant():
    return Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )


def _composant(ondelete="CASCADE", nullable=False):
    return Column(
        UUID(as_uuid=True),
        ForeignKey("composants.id", ondelete=ondelete),
        nullable=nullable,
    )


def _user(name):
    return Column(name, UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class UniteConversion(Base):
    """Une unité alternative d'un composant : ``1 <unite> = facteur x stock_unite`` (1 carton = 12 bouteilles)."""

    __tablename__ = "unites_conversion"

    id = _pk()
    restaurant_id = _restaurant()
    composant_id = _composant()
    unite = Column(String(20), nullable=False)
    facteur = Column(Numeric(14, 6), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("composant_id", "unite", name="uq_unite_conversion_composant_unite"),
        Index("idx_unite_conversion_restaurant", "restaurant_id", "composant_id"),
        CheckConstraint("facteur > 0", name="check_unite_conversion_facteur_positif"),
    )


class Fournisseur(Base):
    __tablename__ = "fournisseurs"

    id = _pk()
    restaurant_id = _restaurant()
    nom = Column(String(255), nullable=False)
    contact = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    telephone = Column(String(30), nullable=True)
    adresse = Column(Text, nullable=True)
    delai_jours = Column(Integer, default=2, nullable=False, server_default="2")
    conditions_paiement = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)
    actif = Column(Boolean, default=True, nullable=False, server_default="true")
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_fournisseur_restaurant", "restaurant_id", "actif"),
        CheckConstraint("delai_jours >= 0", name="check_fournisseur_delai_positif"),
    )


class ComposantFournisseur(Base):
    """Catalogue d'achat : ce que chaque fournisseur vend, à quel prix, par quel conditionnement."""

    __tablename__ = "composant_fournisseurs"

    id = _pk()
    restaurant_id = _restaurant()
    composant_id = _composant()
    fournisseur_id = Column(
        UUID(as_uuid=True), ForeignKey("fournisseurs.id", ondelete="CASCADE"), nullable=False
    )
    reference = Column(String(60), nullable=True)
    prix_unitaire = Column(Numeric(14, 4), nullable=True)
    # Conditionnement d'achat en unités de stock (un sac de 25 kg) : la commande s'arrondit à ce multiple.
    conditionnement = Column(Numeric(12, 3), nullable=True)
    quantite_minimum = Column(Numeric(12, 3), nullable=True)
    principal = Column(Boolean, default=False, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("composant_id", "fournisseur_id", name="uq_composant_fournisseur"),
        Index("idx_composant_fournisseur_restaurant", "restaurant_id", "fournisseur_id"),
        CheckConstraint(
            "prix_unitaire IS NULL OR prix_unitaire >= 0", name="check_composant_fournisseur_prix"
        ),
    )


class StockLot(Base):
    """Un lot reçu : quantité restante, date de péremption, coût. Sorties FIFO (péremption la plus proche)."""

    __tablename__ = "stock_lots"

    id = _pk()
    restaurant_id = _restaurant()
    composant_id = _composant()
    numero = Column(String(60), nullable=True)
    quantite_initiale = Column(Numeric(12, 3), nullable=False)
    quantite_restante = Column(Numeric(12, 3), nullable=False)
    date_peremption = Column(Date, nullable=True)
    recu_le = Column(DateTime(timezone=True), server_default=func.now())
    fournisseur_id = Column(
        UUID(as_uuid=True), ForeignKey("fournisseurs.id", ondelete="SET NULL"), nullable=True
    )
    cout_unitaire = Column(Numeric(14, 4), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_stock_lot_composant_peremption", "restaurant_id", "composant_id", "date_peremption"),
        CheckConstraint("quantite_restante >= 0", name="check_stock_lot_restante_positive"),
        CheckConstraint("quantite_initiale > 0", name="check_stock_lot_initiale_positive"),
    )


class BonCommande(Base):
    """Bon de commande fournisseur. Statuts : brouillon, envoye, recu_partiel, recu, annule."""

    __tablename__ = "bons_commande"

    id = _pk()
    restaurant_id = _restaurant()
    numero = Column(String(30), nullable=False)
    fournisseur_id = Column(
        UUID(as_uuid=True), ForeignKey("fournisseurs.id", ondelete="RESTRICT"), nullable=False
    )
    statut = Column(String(20), default="brouillon", nullable=False, server_default="brouillon")
    date_livraison_prevue = Column(Date, nullable=True)
    note = Column(Text, nullable=True)
    total_estime = Column(Numeric(14, 2), default=0, nullable=False, server_default="0")
    cree_par = _user("cree_par")
    envoye_le = Column(DateTime(timezone=True), nullable=True)
    cloture_le = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("restaurant_id", "numero", name="uq_bon_commande_numero"),
        Index("idx_bon_commande_restaurant_statut", "restaurant_id", "statut", "created_at"),
        CheckConstraint(
            "statut IN ('brouillon', 'envoye', 'recu_partiel', 'recu', 'annule')",
            name="check_bon_commande_statut",
        ),
    )


class BonCommandeLigne(Base):
    __tablename__ = "bons_commande_lignes"

    id = _pk()
    restaurant_id = _restaurant()
    bon_id = Column(
        UUID(as_uuid=True), ForeignKey("bons_commande.id", ondelete="CASCADE"), nullable=False
    )
    composant_id = _composant(ondelete="RESTRICT")
    quantite_commandee = Column(Numeric(12, 3), nullable=False)
    quantite_recue = Column(Numeric(12, 3), default=0, nullable=False, server_default="0")
    prix_unitaire = Column(Numeric(14, 4), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("bon_id", "composant_id", name="uq_bon_commande_ligne_composant"),
        Index("idx_bon_commande_ligne_restaurant", "restaurant_id", "bon_id"),
        CheckConstraint("quantite_commandee > 0", name="check_bon_ligne_commandee_positive"),
        CheckConstraint("quantite_recue >= 0", name="check_bon_ligne_recue_positive"),
    )


class Reception(Base):
    """Une livraison reçue, avec ou sans bon de commande (bon de livraison du fournisseur)."""

    __tablename__ = "receptions"

    id = _pk()
    restaurant_id = _restaurant()
    bon_id = Column(
        UUID(as_uuid=True), ForeignKey("bons_commande.id", ondelete="SET NULL"), nullable=True
    )
    fournisseur_id = Column(
        UUID(as_uuid=True), ForeignKey("fournisseurs.id", ondelete="SET NULL"), nullable=True
    )
    numero_bl = Column(String(60), nullable=True)
    note = Column(Text, nullable=True)
    recu_par = _user("recu_par")
    recu_le = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_reception_restaurant_date", "restaurant_id", "recu_le"),)


class ReceptionLigne(Base):
    __tablename__ = "reception_lignes"

    id = _pk()
    restaurant_id = _restaurant()
    reception_id = Column(
        UUID(as_uuid=True), ForeignKey("receptions.id", ondelete="CASCADE"), nullable=False
    )
    composant_id = _composant(ondelete="RESTRICT")
    quantite = Column(Numeric(12, 3), nullable=False)
    prix_unitaire = Column(Numeric(14, 4), nullable=True)
    lot_numero = Column(String(60), nullable=True)
    date_peremption = Column(Date, nullable=True)
    lot_id = Column(
        UUID(as_uuid=True), ForeignKey("stock_lots.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("idx_reception_ligne_restaurant", "restaurant_id", "reception_id"),
        CheckConstraint("quantite > 0", name="check_reception_ligne_quantite_positive"),
    )


class Inventaire(Base):
    """Session de comptage physique. Statuts : ouvert, valide, annule. Un seul ouvert par restaurant."""

    __tablename__ = "inventaires"

    id = _pk()
    restaurant_id = _restaurant()
    numero = Column(String(30), nullable=False)
    statut = Column(String(20), default="ouvert", nullable=False, server_default="ouvert")
    note = Column(Text, nullable=True)
    cree_par = _user("cree_par")
    valide_par = _user("valide_par")
    valide_le = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("restaurant_id", "numero", name="uq_inventaire_numero"),
        Index("idx_inventaire_restaurant", "restaurant_id", "created_at"),
        CheckConstraint("statut IN ('ouvert', 'valide', 'annule')", name="check_inventaire_statut"),
    )


class InventaireLigne(Base):
    __tablename__ = "inventaire_lignes"

    id = _pk()
    restaurant_id = _restaurant()
    inventaire_id = Column(
        UUID(as_uuid=True), ForeignKey("inventaires.id", ondelete="CASCADE"), nullable=False
    )
    composant_id = _composant(ondelete="RESTRICT")
    quantite_theorique = Column(Numeric(12, 3), nullable=False)
    quantite_comptee = Column(Numeric(12, 3), nullable=True)
    cout_unitaire = Column(Numeric(14, 4), nullable=True)
    note = Column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("inventaire_id", "composant_id", name="uq_inventaire_ligne_composant"),
        Index("idx_inventaire_ligne_restaurant", "restaurant_id", "inventaire_id"),
        CheckConstraint(
            "quantite_comptee IS NULL OR quantite_comptee >= 0", name="check_inventaire_comptee_positive"
        ),
    )


class CatalogueHistoriquePrix(Base):
    """Historique des prix de vente : chaque changement de prix d'un plat, d'une boisson ou d'une combinaison."""

    __tablename__ = "catalogue_historique_prix"

    id = _pk()
    restaurant_id = _restaurant()
    entite = Column(String(20), nullable=False)
    entite_id = Column(UUID(as_uuid=True), nullable=False)
    ancien_prix = Column(Numeric(10, 2), nullable=True)
    nouveau_prix = Column(Numeric(10, 2), nullable=False)
    auteur_id = _user("auteur_id")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_catalogue_prix_entite", "restaurant_id", "entite", "entite_id", "created_at"),
        CheckConstraint("entite IN ('plat', 'boisson', 'combinaison')", name="check_catalogue_prix_entite"),
    )
