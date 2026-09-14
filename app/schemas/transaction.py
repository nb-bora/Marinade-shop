from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
import uuid


class TransactionBase(BaseModel):
    amount_fcfa: int = Field(..., gt=0)
    description: Optional[str] = Field(None, max_length=500)
    pos_transaction_id: Optional[str] = Field(None, max_length=100)
    idempotency_key: str = Field(..., min_length=1, max_length=100)


class TransactionCreate(TransactionBase):
    subscription_id: uuid.UUID


class TransactionResponse(TransactionBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subscription_id: uuid.UUID
    created_at: datetime


class RefreshTokenBase(BaseModel):
    user_id: uuid.UUID
    token_hash: str
    expires_at: datetime


class RefreshTokenCreate(RefreshTokenBase):
    pass


class RefreshTokenResponse(RefreshTokenBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
