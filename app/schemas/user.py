from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, Literal
from datetime import datetime
import uuid


class UserBase(BaseModel):
    email: str = Field(..., pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    phone: str = Field(..., min_length=10, max_length=20)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    role: Literal["admin", "pos"]

    @field_validator('email')
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        # Additional validation checks
        if '..' in v:
            raise ValueError('Email cannot contain consecutive dots')
        local_part = v.split('@')[0]
        if local_part.startswith('.') or local_part.endswith('.'):
            raise ValueError('Email local part cannot start or end with a dot')
        return v


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    email: Optional[str] = Field(None, pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    phone: Optional[str] = Field(None, min_length=10, max_length=20)
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    role: Optional[Literal["admin", "pos"]] = None

    @field_validator('email')
    @classmethod
    def validate_email_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        # Additional validation checks
        if '..' in v:
            raise ValueError('Email cannot contain consecutive dots')
        local_part = v.split('@')[0]
        if local_part.startswith('.') or local_part.endswith('.'):
            raise ValueError('Email local part cannot start or end with a dot')
        return v


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    phone: str
    first_name: str
    last_name: str
    role: str
    created_at: datetime
    updated_at: datetime


class UserLogin(BaseModel):
    email: str = Field(..., pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    password: str

    @field_validator('email')
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        # Additional validation checks
        if '..' in v:
            raise ValueError('Email cannot contain consecutive dots')
        local_part = v.split('@')[0]
        if local_part.startswith('.') or local_part.endswith('.'):
            raise ValueError('Email local part cannot start or end with a dot')
        return v
