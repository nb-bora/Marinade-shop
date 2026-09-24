from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime, date
import uuid


class SubscriptionTierBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    daily_limit_fcfa: int = Field(..., gt=0)
    monthly_price_fcfa: int = Field(..., gt=0)
    annual_price_fcfa: int = Field(..., gt=0)


class SubscriptionTierCreate(SubscriptionTierBase):
    pass


class SubscriptionTierUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    daily_limit_fcfa: Optional[int] = Field(None, gt=0)
    monthly_price_fcfa: Optional[int] = Field(None, gt=0)
    annual_price_fcfa: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None


class SubscriptionTierResponse(SubscriptionTierBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_active: bool


class SubscriptionBase(BaseModel):
    tier_id: int
    status: str
    start_date: date
    end_date: Optional[date] = None


class SubscriptionCreate(SubscriptionBase):
    user_id: uuid.UUID
    restaurant_id: uuid.UUID


class SubscriptionUpdate(BaseModel):
    status: Optional[str] = None
    end_date: Optional[date] = None


class SubscriptionResponse(SubscriptionBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    restaurant_id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class DailyBalanceBase(BaseModel):
    balance_date: date
    initial_balance_fcfa: int = Field(..., gt=0)
    used_balance_fcfa: int = Field(..., ge=0)


class DailyBalanceCreate(DailyBalanceBase):
    subscription_id: uuid.UUID


class DailyBalanceUpdate(BaseModel):
    used_balance_fcfa: int = Field(..., ge=0)


class DailyBalanceResponse(DailyBalanceBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    restaurant_id: uuid.UUID
    subscription_id: uuid.UUID
