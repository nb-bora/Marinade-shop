from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Date,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.core.database import Base
from app.utils.enums import TableStatut, CommandeStatut, RefundStatus
import uuid


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    logo_url = Column(String(500), nullable=True)
    currency = Column(String(3), default="XAF", nullable=False)
    phone = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    horaires_ouverture = Column(JSONB, nullable=True)
    taux_service = Column(Numeric(5, 2), default=0.0)
    config_jsonb = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_restaurant_owner"),
        Index("idx_restaurant_user", "user_id"),
        Index("idx_restaurant_active", "is_active"),
    )


class Menu(Base):
    __tablename__ = "menus"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    actif = Column(Boolean, default=True)
    config_jsonb = Column(JSONB, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_menu_restaurant", "restaurant_id"),
        Index("idx_menu_active", "actif"),
        Index("idx_menu_deleted", "deleted_at"),
    )


class MenuCategory(Base):
    __tablename__ = "menu_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    menu_id = Column(
        UUID(as_uuid=True), ForeignKey("menus.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(100), nullable=False)
    ordre = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_category_restaurant", "restaurant_id"),
        Index("idx_category_menu", "menu_id"),
        Index("idx_category_order", "restaurant_id", "menu_id", "ordre"),
    )


class Composant(Base):
    __tablename__ = "composants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    nom = Column(String(255), nullable=False)
    type = Column(String(30), nullable=False)
    prix_supplement = Column(Numeric(10, 2), default=0, nullable=False)
    devise = Column(String(3), default="XAF", nullable=False)
    disponible = Column(Boolean, default=True, nullable=False)
    stock_unite = Column(String(20), default="portion", nullable=False)
    description = Column(Text, nullable=True)
    attributs_jsonb = Column(JSONB, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_composant_restaurant", "restaurant_id"),
        Index("idx_composant_type", "restaurant_id", "type"),
        Index("idx_composant_disponible", "restaurant_id", "disponible"),
        Index("idx_composant_deleted", "deleted_at"),
        CheckConstraint(
            "prix_supplement >= 0", name="check_composant_supplement_positive"
        ),
    )


class Combinaison(Base):
    __tablename__ = "combinaisons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    menu_id = Column(
        UUID(as_uuid=True), ForeignKey("menus.id", ondelete="SET NULL"), nullable=True
    )
    nom = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    prix = Column(Numeric(10, 2), nullable=False)
    devise = Column(String(3), default="XAF", nullable=False)
    disponible = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_combinaison_restaurant", "restaurant_id"),
        Index("idx_combinaison_menu", "menu_id"),
        Index("idx_combinaison_disponible", "restaurant_id", "disponible"),
        CheckConstraint("prix > 0", name="check_combinaison_prix_positive"),
    )


class CombinaisonComposant(Base):
    __tablename__ = "combinaison_composants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    combinaison_id = Column(
        UUID(as_uuid=True),
        ForeignKey("combinaisons.id", ondelete="CASCADE"),
        nullable=False,
    )
    composant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("composants.id", ondelete="CASCADE"),
        nullable=False,
    )
    quantite = Column(Numeric(10, 3), default=1, nullable=False)
    obligatoire = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_combinaison_composant_combinaison", "combinaison_id"),
        Index("idx_combinaison_composant_composant", "composant_id"),
        CheckConstraint(
            "quantite > 0", name="check_combinaison_composant_quantite_positive"
        ),
        UniqueConstraint(
            "combinaison_id", "composant_id", name="uq_combinaison_composant"
        ),
    )


class StockComposant(Base):
    __tablename__ = "stock_composants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    composant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("composants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    quantite = Column(Numeric(12, 3), default=0, nullable=False)
    reservee = Column(Numeric(12, 3), default=0, nullable=False)
    seuil_alerte = Column(Numeric(12, 3), default=0, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_stock_composant", "composant_id"),
        CheckConstraint("quantite >= 0", name="check_stock_quantite_positive"),
        CheckConstraint("reservee >= 0", name="check_stock_reservee_positive"),
        CheckConstraint("seuil_alerte >= 0", name="check_stock_seuil_positive"),
    )


class StockMouvement(Base):
    __tablename__ = "stock_mouvements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    composant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("composants.id", ondelete="CASCADE"),
        nullable=False,
    )
    type = Column(String(20), nullable=False)
    quantite = Column(Numeric(12, 3), nullable=False)
    reference_type = Column(String(30), nullable=True)
    reference_id = Column(UUID(as_uuid=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_stock_mouvement_composant", "composant_id"),
        Index("idx_stock_mouvement_date", "created_at"),
        CheckConstraint("quantite > 0", name="check_stock_mouvement_quantite_positive"),
    )


class Plat(Base):
    __tablename__ = "plats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id = Column(
        UUID(as_uuid=True),
        ForeignKey("menu_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    nom = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    prix = Column(Numeric(10, 2), nullable=False)
    devise = Column(String(3), default="XAF", nullable=False)
    disponible = Column(Boolean, default=True)
    allergenes = Column(JSONB, nullable=True)
    photo_url = Column(String(500), nullable=True)
    temps_preparation = Column(Integer, nullable=True)
    attributs_jsonb = Column(JSONB, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_plat_restaurant", "restaurant_id"),
        Index("idx_plat_category", "category_id"),
        Index("idx_plat_disponible", "disponible"),
        Index("idx_plat_deleted", "deleted_at"),
        CheckConstraint("prix > 0", name="check_prix_positive"),
    )


class PlatComposant(Base):
    __tablename__ = "plat_composants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plat_id = Column(
        UUID(as_uuid=True), ForeignKey("plats.id", ondelete="CASCADE"), nullable=False
    )
    composant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("composants.id", ondelete="CASCADE"),
        nullable=False,
    )
    quantite = Column(Numeric(12, 3), default=1, nullable=False)
    unite = Column(String(20), default="portion", nullable=False)
    ordre = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_plat_composant_plat", "plat_id"),
        Index("idx_plat_composant_composant", "composant_id"),
        Index("idx_plat_composant_ordre", "plat_id", "ordre"),
        UniqueConstraint("plat_id", "composant_id", name="uq_plat_composant"),
        CheckConstraint("quantite > 0", name="check_plat_composant_quantite_positive"),
    )


class Boisson(Base):
    __tablename__ = "boissons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    nom = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    prix = Column(Numeric(10, 2), nullable=False)
    devise = Column(String(3), default="XAF", nullable=False)
    alcool = Column(Boolean, default=False)
    disponible = Column(Boolean, default=True)
    category = Column(String(50), nullable=True)
    attributs_jsonb = Column(JSONB, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_boisson_restaurant", "restaurant_id"),
        Index("idx_boisson_disponible", "disponible"),
        Index("idx_boisson_category", "category"),
        Index("idx_boisson_deleted", "deleted_at"),
        CheckConstraint("prix > 0", name="check_boisson_prix_positive"),
    )


class Table(Base):
    __tablename__ = "tables"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    numero = Column(String(50), nullable=False)
    capacite = Column(Integer, default=4, nullable=False)
    emplacement = Column(String(50), nullable=True)
    statut = Column(String(20), default=TableStatut.LIBRE.value, nullable=False)
    attributs_jsonb = Column(JSONB, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_table_restaurant", "restaurant_id"),
        Index("idx_table_statut", "statut"),
        Index("idx_table_numero", "restaurant_id", "numero"),
        Index("idx_table_deleted", "deleted_at"),
        CheckConstraint("capacite > 0", name="check_capacite_positive"),
    )


class Commande(Base):
    __tablename__ = "commandes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    table_id = Column(
        UUID(as_uuid=True), ForeignKey("tables.id", ondelete="SET NULL"), nullable=True
    )
    payment_intent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("payment_intents.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    statut = Column(String(20), default=CommandeStatut.EN_COURS.value, nullable=False)
    total = Column(Numeric(12, 2), nullable=False)
    taux_service = Column(Numeric(5, 2), nullable=True)
    refund_status = Column(String(20), default=RefundStatus.NONE.value, nullable=False)
    refunded_amount = Column(Numeric(12, 2), default=0, nullable=False)
    refunded_at = Column(DateTime(timezone=True), nullable=True)
    refund_reason = Column(Text, nullable=True)
    refunded_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    refund_idempotency_key = Column(UUID(as_uuid=True), nullable=True, unique=True)
    metadata_jsonb = Column(JSONB, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_commande_restaurant", "restaurant_id"),
        Index("idx_commande_table", "table_id"),
        Index("idx_commande_statut", "statut"),
        Index("idx_commande_date", "created_at"),
        Index("idx_commande_payment_intent", "payment_intent_id", unique=True),
        Index("idx_commande_refund_status", "refund_status"),
        Index("idx_commande_refund_idempotency", "refund_idempotency_key", unique=True),
        Index("idx_commande_deleted", "deleted_at"),
        CheckConstraint("total >= 0", name="check_total_positive"),
        CheckConstraint("refunded_amount >= 0", name="check_refunded_amount_positive"),
        CheckConstraint(
            "refunded_amount <= total", name="check_refunded_amount_le_total"
        ),
        CheckConstraint(
            "statut IN ('en_cours', 'servie', 'annulee', 'payee', 'paiement_en_attente', 'paiement_a_verifier')",
            name="check_commande_status",
        ),
        CheckConstraint(
            "refund_status IN ('none', 'requested', 'approved', 'rejected', 'partial', 'completed', 'failed')",
            name="check_commande_refund_status",
        ),
    )


class CommandeItem(Base):
    __tablename__ = "commande_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    commande_id = Column(
        UUID(as_uuid=True),
        ForeignKey("commandes.id", ondelete="CASCADE"),
        nullable=False,
    )
    plat_id = Column(
        UUID(as_uuid=True), ForeignKey("plats.id", ondelete="SET NULL"), nullable=True
    )
    boisson_id = Column(
        UUID(as_uuid=True),
        ForeignKey("boissons.id", ondelete="SET NULL"),
        nullable=True,
    )
    combinaison_id = Column(
        UUID(as_uuid=True),
        ForeignKey("combinaisons.id", ondelete="SET NULL"),
        nullable=True,
    )
    quantite = Column(Integer, nullable=False)
    prix_unitaire = Column(Numeric(10, 2), nullable=False)
    total = Column(Numeric(10, 2), nullable=False)
    supplements_total = Column(Numeric(10, 2), default=0, nullable=False)
    refunded_quantity = Column(Integer, default=0, nullable=False)
    details_jsonb = Column(JSONB, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_item_commande", "commande_id"),
        Index("idx_item_plat", "plat_id"),
        Index("idx_item_boisson", "boisson_id"),
        Index("idx_item_combinaison", "combinaison_id"),
        CheckConstraint("quantite > 0", name="check_quantite_positive"),
        CheckConstraint("total >= 0", name="check_item_total_positive"),
        CheckConstraint(
            "supplements_total >= 0", name="check_item_supplements_positive"
        ),
        CheckConstraint(
            "refunded_quantity >= 0 AND refunded_quantity <= quantite",
            name="check_item_refunded_quantity_valid",
        ),
    )


class CommandeRefund(Base):
    __tablename__ = "commande_refunds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    commande_id = Column(
        UUID(as_uuid=True),
        ForeignKey("commandes.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount = Column(Numeric(12, 2), nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String(20), default=RefundStatus.REQUESTED.value, nullable=False)
    initiated_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    processed_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    processed_at = Column(DateTime(timezone=True), nullable=True)
    external_reference = Column(String(255), nullable=True)
    notes_jsonb = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_refund_commande", "commande_id"),
        Index("idx_refund_status", "status"),
        Index("idx_refund_created", "created_at"),
        CheckConstraint("amount > 0", name="check_refund_amount_positive"),
        CheckConstraint(
            "status IN ('requested', 'approved', 'rejected', 'partial', 'completed', 'failed')",
            name="check_refund_status_valid",
        ),
    )
