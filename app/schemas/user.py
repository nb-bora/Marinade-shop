from typing import Optional, Literal
from datetime import datetime
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_phone(value: str) -> str:
    normalized = re.sub(r"[\s().-]", "", value)
    if normalized.startswith("00"):
        normalized = "+" + normalized[2:]
    if normalized.startswith("237"):
        normalized = "+" + normalized
    if not normalized.startswith("+"):
        raise ValueError("Phone must use an international format")
    if not re.fullmatch(r"\+[1-9]\d{6,14}", normalized):
        raise ValueError("Invalid phone number")
    return normalized


class UserBase(BaseModel):
    email: str = Field(..., min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    phone: str = Field(..., min_length=8, max_length=20)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    role: Literal["admin", "pos", "restaurant"]

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, value: str) -> str:
        if ".." in value or value.startswith(".") or value.split("@", 1)[0].endswith("."):
            raise ValueError("Invalid email format")
        return value.lower()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone(value)


class UserCreate(UserBase):
    password: str = Field(..., min_length=12, max_length=128)


class UserUpdate(BaseModel):
    email: Optional[str] = Field(None, min_length=3, max_length=254)
    phone: Optional[str] = Field(None, min_length=8, max_length=20)
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    role: Optional[Literal["admin", "pos", "restaurant"]] = None
    is_active: Optional[bool] = None

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if ".." in value or value.startswith(".") or value.split("@", 1)[0].endswith("."):
            raise ValueError("Invalid email format")
        return value.lower()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        return normalize_phone(value) if value is not None else value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    phone: str
    first_name: str
    last_name: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserLogin(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()
