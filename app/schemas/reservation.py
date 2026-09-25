from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

from app.utils.enums import ReservationStatus


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


class ReservationBase(BaseModel):
    table_id: Optional[uuid.UUID] = None
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=50)
    customer_email: Optional[str] = Field(None, max_length=254)
    status: str = Field(default=ReservationStatus.PENDING.value, max_length=30)
    party_size: int = Field(..., gt=0)
    reservation_date: datetime
    duration_minutes: int = Field(default=90, gt=0)
    notes: Optional[str] = Field(None, max_length=1000)
    source: str = Field(default="POS", max_length=30)
    customer_id: Optional[uuid.UUID] = None
    reminder_sent: bool = False
    arrival_notes: Optional[str] = Field(None, max_length=255)
    preferences_jsonb: Optional[Dict[str, Any]] = None


class ReservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table_id: Optional[uuid.UUID] = None
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=50)
    customer_email: Optional[str] = Field(None, max_length=254)
    party_size: int = Field(..., gt=0)
    reservation_date: datetime
    duration_minutes: int = Field(default=90, gt=0)
    source: str = Field(default="POS", max_length=30)
    notes: Optional[str] = Field(None, max_length=1000)
    customer_id: Optional[uuid.UUID] = None
    reminder_sent: bool = False
    arrival_notes: Optional[str] = Field(None, max_length=255)
    preferences_jsonb: Optional[Dict[str, Any]] = None
    invites: List[ReservationGuestCreate] = []


class ReservationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table_id: Optional[uuid.UUID] = None
    customer_name: Optional[str] = Field(None, min_length=1, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=50)
    customer_email: Optional[str] = Field(None, max_length=254)
    status: Optional[str] = Field(None, max_length=30)
    party_size: Optional[int] = Field(None, gt=0)
    reservation_date: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(None, gt=0)
    notes: Optional[str] = Field(None, max_length=1000)
    source: Optional[str] = Field(None, max_length=30)
    customer_id: Optional[uuid.UUID] = None
    reminder_sent: Optional[bool] = None
    arrival_notes: Optional[str] = Field(None, max_length=255)
    preferences_jsonb: Optional[Dict[str, Any]] = None


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
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[uuid.UUID] = None
    cancel_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    invites: List[ReservationGuestResponse] = []


class WaitlistBase(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=50)
    customer_email: Optional[str] = Field(None, max_length=254)
    party_size: int = Field(..., gt=0)
    requested_table_id: Optional[uuid.UUID] = None
    estimated_wait_minutes: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=500)
    preferences_jsonb: Optional[Dict[str, Any]] = None
    source: str = Field(default="POS", max_length=30)


class WaitlistCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=50)
    customer_email: Optional[str] = Field(None, max_length=254)
    party_size: int = Field(..., gt=0)
    requested_table_id: Optional[uuid.UUID] = None
    estimated_wait_minutes: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=500)
    preferences_jsonb: Optional[Dict[str, Any]] = None
    source: str = Field(default="POS", max_length=30)


class WaitlistUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_name: Optional[str] = Field(None, min_length=1, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=50)
    customer_email: Optional[str] = Field(None, max_length=254)
    party_size: Optional[int] = Field(None, gt=0)
    requested_table_id: Optional[uuid.UUID] = None
    assigned_table_id: Optional[uuid.UUID] = None
    position: Optional[int] = Field(None, gt=0)
    status: Optional[str] = Field(None, max_length=30)
    estimated_wait_minutes: Optional[int] = Field(None, ge=0)
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


class ReservationListFilters(BaseModel):
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    status: Optional[str] = Field(None, max_length=30)
    table_id: Optional[uuid.UUID] = None
    search: Optional[str] = Field(None, max_length=255)


class ReservationConfirmRequest(BaseModel):
    notes: Optional[str] = Field(None, max_length=500)


class ReservationCancelRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)
