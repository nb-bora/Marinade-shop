from datetime import datetime
from typing import Literal, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.phone import normalize_cameroon_mobile


class EasyTransactCheckoutCreate(BaseModel):
    restaurant_id: uuid.UUID
    commande_id: Optional[uuid.UUID] = None
    subscription_id: Optional[uuid.UUID] = None
    billing_period: Literal["monthly", "annual"] = "monthly"
    description: str = Field(..., min_length=1, max_length=255)
    amount_fcfa: int = Field(..., gt=0)
    idempotency_key: str = Field(..., min_length=8, max_length=120)
    success_url: Optional[str] = Field(None, max_length=500)
    cancel_url: Optional[str] = Field(None, max_length=500)

    @field_validator("success_url", "cancel_url")
    @classmethod
    def validate_https_url(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.startswith("https://"):
            raise ValueError("Callback URLs must use HTTPS")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("idempotency_key is required")
        return value


class EasyTransactInitiateRequest(BaseModel):
    restaurant_id: uuid.UUID
    vendor_reference: str = Field(..., min_length=1, max_length=100)
    amount_fcfa: int = Field(..., gt=0)
    service_code: str = Field("DEPOSIT", min_length=1, max_length=50)
    currency_code: Literal["XAF"] = "XAF"
    operator_id: Optional[str] = Field(None, max_length=100)
    sender_number: Optional[str] = Field(None, max_length=20)
    receiver_number: Optional[str] = Field(None, max_length=20)

    @field_validator("sender_number", "receiver_number")
    @classmethod
    def validate_mobile_number(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized, _ = normalize_cameroon_mobile(value)
        return normalized


class PaymentConfigurationUpsert(BaseModel):
    restaurant_id: uuid.UUID
    service_code: str = Field("DEPOSIT", min_length=1, max_length=50)
    webhook_url: Optional[str] = Field(None, max_length=500)
    success_url: Optional[str] = Field(None, max_length=500)
    failure_url: Optional[str] = Field(None, max_length=500)
    vendor_reference_prefix: str = Field(
        "MRD", min_length=2, max_length=30, pattern=r"^[A-Za-z0-9_-]+$"
    )
    provider_account_ref: Optional[str] = Field(None, max_length=255)
    credential_env_key: str = Field(
        "EASYTRANSACT_API_TOKEN", min_length=3, max_length=255
    )
    webhook_secret_env_key: str = Field(
        "EASYTRANSACT_WEBHOOK_SECRET", min_length=3, max_length=255
    )
    enabled: bool = True

    @field_validator("webhook_url", "success_url", "failure_url")
    @classmethod
    def validate_urls(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.startswith("https://"):
            raise ValueError("Payment URLs must use HTTPS")
        return value


class PaymentConfigurationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    restaurant_id: uuid.UUID
    provider: str
    service_code: str
    webhook_url: Optional[str]
    success_url: Optional[str]
    failure_url: Optional[str]
    vendor_reference_prefix: str
    provider_account_ref: Optional[str]
    credential_env_key: str
    webhook_secret_env_key: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class CashPaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    restaurant_id: uuid.UUID
    commande_id: uuid.UUID
    amount_fcfa: int = Field(..., gt=0)
    idempotency_key: str = Field(..., min_length=8, max_length=120)
    received_by: uuid.UUID
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("idempotency_key is required")
        return value


class PaymentIntentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    restaurant_id: uuid.UUID
    commande_id: Optional[uuid.UUID]
    subscription_id: Optional[uuid.UUID]
    provider: str
    vendor_reference: str
    provider_transaction_id: Optional[str]
    idempotency_key: str
    amount_fcfa: int
    currency: str
    status: str
    checkout_url: Optional[str]
    expires_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class EasyTransactWebhookResponse(BaseModel):
    accepted: bool
    duplicate: bool = False
    status: Optional[str] = None
