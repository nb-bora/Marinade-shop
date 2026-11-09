from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.enums import ReservationStatus

DUREE_MAX_MIN = 1440


def _exiger_fuseau(valeur: datetime) -> datetime:
    """Une date sans fuseau serait lue en UTC par erreur : on la refuse."""
    if valeur.tzinfo is None or valeur.tzinfo.utcoffset(valeur) is None:
        raise ValueError(
            "La date doit indiquer son fuseau horaire (par exemple 2026-11-14T19:00:00+01:00)."
        )
    return valeur


class ReservationGuestBase(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    age_category: Optional[str] = Field(None, max_length=20)
    is_vegetarian: bool = False
    allergenes: Optional[Dict[str, Any]] = None
    notes: Optional[str] = Field(None, max_length=500)


class ReservationGuestCreate(ReservationGuestBase):
    pass


class ReservationGuestResponse(ReservationGuestBase):
    id: uuid.UUID
    reservation_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table_id: Optional[uuid.UUID] = None
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=50)
    customer_email: Optional[str] = Field(None, max_length=254)
    party_size: int = Field(..., gt=0, le=500)
    reservation_date: datetime
    duration_minutes: int = Field(default=90, gt=0, le=DUREE_MAX_MIN)
    source: str = Field(default="POS", max_length=30)
    notes: Optional[str] = Field(None, max_length=1000)
    customer_id: Optional[uuid.UUID] = None
    reminder_sent: bool = False
    arrival_notes: Optional[str] = Field(None, max_length=255)
    preferences_jsonb: Optional[Dict[str, Any]] = None
    invites: List[ReservationGuestCreate] = []

    @field_validator("reservation_date")
    @classmethod
    def _fuseau_obligatoire(cls, valeur: datetime) -> datetime:
        return _exiger_fuseau(valeur)


class ReservationUpdate(BaseModel):
    """Modification des données d'une réservation. L'état ne se change pas ici : il passe
    par les routes de transition (confirmer, arrivée, absence, terminer, annuler)."""

    model_config = ConfigDict(extra="forbid")
    table_id: Optional[uuid.UUID] = None
    customer_name: Optional[str] = Field(None, min_length=1, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=50)
    customer_email: Optional[str] = Field(None, max_length=254)
    party_size: Optional[int] = Field(None, gt=0, le=500)
    reservation_date: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(None, gt=0, le=DUREE_MAX_MIN)
    notes: Optional[str] = Field(None, max_length=1000)
    source: Optional[str] = Field(None, max_length=30)
    customer_id: Optional[uuid.UUID] = None
    reminder_sent: Optional[bool] = None
    arrival_notes: Optional[str] = Field(None, max_length=255)
    preferences_jsonb: Optional[Dict[str, Any]] = None

    @field_validator("reservation_date")
    @classmethod
    def _fuseau_obligatoire(cls, valeur: Optional[datetime]) -> Optional[datetime]:
        return None if valeur is None else _exiger_fuseau(valeur)


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    restaurant_id: uuid.UUID
    table_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    session_id: Optional[uuid.UUID] = None
    created_by: Optional[uuid.UUID] = None
    customer_name: str
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    status: str
    party_size: int
    reservation_date: datetime
    duration_minutes: int
    notes: Optional[str] = None
    source: str
    reminder_sent: bool
    arrival_notes: Optional[str] = None
    preferences_jsonb: Optional[Dict[str, Any]] = None
    confirmed_at: Optional[datetime] = None
    checked_in_at: Optional[datetime] = None
    no_show_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[uuid.UUID] = None
    cancel_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    invites: List[ReservationGuestResponse] = []


class WaitlistCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=50)
    customer_email: Optional[str] = Field(None, max_length=254)
    party_size: int = Field(..., gt=0, le=500)
    requested_table_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    estimated_wait_minutes: Optional[int] = Field(None, ge=0, le=600)
    notes: Optional[str] = Field(None, max_length=500)
    preferences_jsonb: Optional[Dict[str, Any]] = None
    source: str = Field(default="POS", max_length=30)


class WaitlistUpdate(BaseModel):
    """Conservé pour les importations existantes ; aucune route ne modifie une entrée ici."""

    model_config = ConfigDict(extra="forbid")
    customer_name: Optional[str] = Field(None, min_length=1, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=50)
    customer_email: Optional[str] = Field(None, max_length=254)
    party_size: Optional[int] = Field(None, gt=0, le=500)
    requested_table_id: Optional[uuid.UUID] = None
    estimated_wait_minutes: Optional[int] = Field(None, ge=0, le=600)
    notes: Optional[str] = Field(None, max_length=500)
    preferences_jsonb: Optional[Dict[str, Any]] = None
    source: Optional[str] = Field(None, max_length=30)


class WaitlistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    restaurant_id: uuid.UUID
    customer_name: str
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    customer_id: Optional[uuid.UUID] = None
    party_size: int
    requested_table_id: Optional[uuid.UUID] = None
    assigned_table_id: Optional[uuid.UUID] = None
    position: int
    estimated_wait_minutes: Optional[int] = None
    status: str
    source: str
    notes: Optional[str] = None
    preferences_jsonb: Optional[Dict[str, Any]] = None
    joined_at: datetime
    seated_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    removed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ReservationCancelRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ReservationConfirmRequest(BaseModel):
    notes: Optional[str] = Field(None, max_length=500)


class CreneauDisponibilite(BaseModel):
    debut: datetime
    heure: str
    tables_libres: int
    disponible: bool
    passe: bool


class DisponibiliteResponse(BaseModel):
    date: str
    fuseau: str
    duree_minutes: int
    party_size: int
    horaires_configures: bool
    creneaux: List[CreneauDisponibilite]


class ClientRecherche(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class ClientResume(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    visites: int
    absences: int
    reservations: int
    derniere_visite: Optional[datetime] = None


class ListeAttenteNotification(BaseModel):
    envoye: bool
    destinataire: str


class ReservationListFilters(BaseModel):
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    status: Optional[str] = Field(None, max_length=30)
    table_id: Optional[uuid.UUID] = None
    search: Optional[str] = Field(None, max_length=255)


__all__ = [
    "ReservationStatus",
    "ReservationGuestCreate",
    "ReservationGuestResponse",
    "ReservationCreate",
    "ReservationUpdate",
    "ReservationResponse",
    "WaitlistCreate",
    "WaitlistResponse",
    "ReservationCancelRequest",
    "ReservationConfirmRequest",
    "ReservationListFilters",
    "DisponibiliteResponse",
    "ClientRecherche",
    "ClientResume",
]
