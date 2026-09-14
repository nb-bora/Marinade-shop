from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
import uuid


class RestaurantBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    logo_url: Optional[str] = None
    currency: str = Field(default="XAF", max_length=3)
    phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = None
    city: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    horaires_ouverture: Optional[dict] = None
    taux_service: Decimal = Field(default=0.0, ge=0, le=100)
    config_jsonb: Optional[dict] = None
    is_active: bool = True


class RestaurantCreate(RestaurantBase):
    pass


class RestaurantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    logo_url: Optional[str] = None
    currency: Optional[str] = Field(None, max_length=3)
    phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = None
    city: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    horaires_ouverture: Optional[dict] = None
    taux_service: Optional[Decimal] = Field(None, ge=0, le=100)
    config_jsonb: Optional[dict] = None
    is_active: Optional[bool] = None


class RestaurantResponse(RestaurantBase):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MenuBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    actif: bool = True
    config_jsonb: Optional[dict] = None


class MenuCreate(MenuBase):
    pass


class MenuUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    actif: Optional[bool] = None
    config_jsonb: Optional[dict] = None


class MenuResponse(MenuBase):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MenuCategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    ordre: int = Field(default=0, ge=0)


class MenuCategoryCreate(MenuCategoryBase):
    menu_id: uuid.UUID


class MenuCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    ordre: Optional[int] = Field(None, ge=0)


class MenuCategoryResponse(MenuCategoryBase):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    menu_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlatBase(BaseModel):
    nom: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    prix: Decimal = Field(..., gt=0)
    devise: str = Field(default="XAF", max_length=3)
    disponible: bool = True
    allergenes: Optional[dict] = None
    photo_url: Optional[str] = None
    temps_preparation: Optional[int] = Field(None, ge=0)
    attributs_jsonb: Optional[dict] = None


class PlatCreate(PlatBase):
    category_id: Optional[uuid.UUID] = None


class PlatUpdate(BaseModel):
    nom: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    prix: Optional[Decimal] = Field(None, gt=0)
    devise: Optional[str] = Field(None, max_length=3)
    disponible: Optional[bool] = None
    allergenes: Optional[dict] = None
    photo_url: Optional[str] = None
    temps_preparation: Optional[int] = Field(None, ge=0)
    attributs_jsonb: Optional[dict] = None


class PlatResponse(PlatBase):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    category_id: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BoissonBase(BaseModel):
    nom: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    prix: Decimal = Field(..., gt=0)
    devise: str = Field(default="XAF", max_length=3)
    alcool: bool = False
    disponible: bool = True
    category: Optional[str] = Field(None, max_length=50)
    attributs_jsonb: Optional[dict] = None


class BoissonCreate(BoissonBase):
    pass


class BoissonUpdate(BaseModel):
    nom: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    prix: Optional[Decimal] = Field(None, gt=0)
    devise: Optional[str] = Field(None, max_length=3)
    alcool: Optional[bool] = None
    disponible: Optional[bool] = None
    category: Optional[str] = Field(None, max_length=50)
    attributs_jsonb: Optional[dict] = None


class BoissonResponse(BoissonBase):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TableBase(BaseModel):
    numero: str = Field(..., min_length=1, max_length=50)
    capacite: int = Field(default=4, gt=0)
    emplacement: Optional[str] = Field(None, max_length=50)
    statut: str = Field(default="libre", max_length=20)
    attributs_jsonb: Optional[dict] = None


class TableCreate(TableBase):
    pass


class TableUpdate(BaseModel):
    numero: Optional[str] = Field(None, min_length=1, max_length=50)
    capacite: Optional[int] = Field(None, gt=0)
    emplacement: Optional[str] = Field(None, max_length=50)
    statut: Optional[str] = Field(None, max_length=20)
    attributs_jsonb: Optional[dict] = None


class TableResponse(TableBase):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CommandeItemBase(BaseModel):
    plat_id: Optional[uuid.UUID] = None
    boisson_id: Optional[uuid.UUID] = None
    quantite: int = Field(..., gt=0)
    prix_unitaire: Decimal = Field(..., gt=0)
    total: Decimal = Field(..., ge=0)
    notes: Optional[str] = None


class CommandeItemCreate(CommandeItemBase):
    pass


class CommandeItemResponse(CommandeItemBase):
    id: uuid.UUID
    commande_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CommandeBase(BaseModel):
    table_id: Optional[uuid.UUID] = None
    statut: str = Field(default="en_cours", max_length=20)
    total: Decimal = Field(..., ge=0)
    taux_service: Optional[Decimal] = Field(None, ge=0, le=100)
    metadata_jsonb: Optional[dict] = None


class CommandeCreate(CommandeBase):
    pass


class CommandeUpdate(BaseModel):
    table_id: Optional[uuid.UUID] = None
    statut: Optional[str] = Field(None, max_length=20)
    total: Optional[Decimal] = Field(None, ge=0)
    taux_service: Optional[Decimal] = Field(None, ge=0, le=100)
    metadata_jsonb: Optional[dict] = None


class CommandeResponse(CommandeBase):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    items: List[CommandeItemResponse] = []

    model_config = ConfigDict(from_attributes=True)
