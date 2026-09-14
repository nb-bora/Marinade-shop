from sqlalchemy import Column, Integer, String, DateTime, Date, Boolean, CheckConstraint, ForeignKey, Index, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.core.database import Base
from app.utils.enums import TableStatut, CommandeStatut
import uuid


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
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
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_restaurant_user", "user_id"),
        Index("idx_restaurant_active", "is_active"),
    )


class Menu(Base):
    __tablename__ = "menus"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    actif = Column(Boolean, default=True)
    config_jsonb = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_menu_restaurant", "restaurant_id"),
        Index("idx_menu_active", "actif"),
    )


class MenuCategory(Base):
    __tablename__ = "menu_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    menu_id = Column(UUID(as_uuid=True), ForeignKey("menus.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    ordre = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_category_restaurant", "restaurant_id"),
        Index("idx_category_menu", "menu_id"),
        Index("idx_category_order", "restaurant_id", "menu_id", "ordre"),
    )


class Plat(Base):
    __tablename__ = "plats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(UUID(as_uuid=True), ForeignKey("menu_categories.id", ondelete="SET NULL"), nullable=True)
    nom = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    prix = Column(Numeric(10, 2), nullable=False)
    devise = Column(String(3), default="XAF", nullable=False)
    disponible = Column(Boolean, default=True)
    allergenes = Column(JSONB, nullable=True)
    photo_url = Column(String(500), nullable=True)
    temps_preparation = Column(Integer, nullable=True)
    attributs_jsonb = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_plat_restaurant", "restaurant_id"),
        Index("idx_plat_category", "category_id"),
        Index("idx_plat_disponible", "disponible"),
        CheckConstraint("prix > 0", name="check_prix_positive"),
    )


class Boisson(Base):
    __tablename__ = "boissons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    nom = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    prix = Column(Numeric(10, 2), nullable=False)
    devise = Column(String(3), default="XAF", nullable=False)
    alcool = Column(Boolean, default=False)
    disponible = Column(Boolean, default=True)
    category = Column(String(50), nullable=True)
    attributs_jsonb = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_boisson_restaurant", "restaurant_id"),
        Index("idx_boisson_disponible", "disponible"),
        Index("idx_boisson_category", "category"),
        CheckConstraint("prix > 0", name="check_prix_positive"),
    )


class Table(Base):
    __tablename__ = "tables"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    numero = Column(String(50), nullable=False)
    capacite = Column(Integer, default=4, nullable=False)
    emplacement = Column(String(50), nullable=True)
    statut = Column(String(20), default=TableStatut.LIBRE.value, nullable=False)
    attributs_jsonb = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_table_restaurant", "restaurant_id"),
        Index("idx_table_statut", "statut"),
        Index("idx_table_numero", "restaurant_id", "numero"),
        CheckConstraint("capacite > 0", name="check_capacite_positive"),
    )


class Commande(Base):
    __tablename__ = "commandes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    table_id = Column(UUID(as_uuid=True), ForeignKey("tables.id", ondelete="SET NULL"), nullable=True)
    statut = Column(String(20), default=CommandeStatut.EN_COURS.value, nullable=False)
    total = Column(Numeric(10, 2), nullable=False)
    taux_service = Column(Numeric(5, 2), nullable=True)
    metadata_jsonb = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_commande_restaurant", "restaurant_id"),
        Index("idx_commande_table", "table_id"),
        Index("idx_commande_statut", "statut"),
        Index("idx_commande_date", "created_at"),
        CheckConstraint("total >= 0", name="check_total_positive"),
    )


class CommandeItem(Base):
    __tablename__ = "commande_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    commande_id = Column(UUID(as_uuid=True, ForeignKey("commandes.id", ondelete="CASCADE"), nullable=False)
    plat_id = Column(UUID(as_uuid=True, ForeignKey("plats.id", ondelete="SET NULL"), nullable=True)
    boisson_id = Column(UUID(as_uuid=True, ForeignKey("boissons.id", ondelete="SET NULL"), nullable=True)
    quantite = Column(Integer, nullable=False)
    prix_unitaire = Column(Numeric(10, 2), nullable=False)
    total = Column(Numeric(10, 2), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_item_commande", "commande_id"),
        Index("idx_item_plat", "plat_id"),
        Index("idx_item_boisson", "boisson_id"),
        CheckConstraint("quantite > 0", name="check_quantite_positive"),
        CheckConstraint("total >= 0", name="check_total_positive"),
    )
