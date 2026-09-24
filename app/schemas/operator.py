from datetime import datetime
from typing import Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MobileOperatorPrefixCreate(BaseModel):
    country_code: str = Field(default="+237", min_length=4, max_length=4)
    operator_code: str = Field(..., min_length=2, max_length=30)
    operator_name: str = Field(..., min_length=2, max_length=100)
    national_prefix: str = Field(..., min_length=2, max_length=4)
    is_active: bool = True

    @field_validator("country_code")
    @classmethod
    def validate_country(cls, value: str) -> str:
        if not value.startswith("+") or not value[1:].isdigit():
            raise ValueError("country_code must look like +237")
        return value

    @field_validator("national_prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        if not value.isdigit() or len(value) not in {2, 3, 4}:
            raise ValueError("national_prefix must contain 2 to 4 digits")
        return value


class MobileOperatorPrefixUpdate(BaseModel):
    operator_name: Optional[str] = Field(None, min_length=2, max_length=100)
    is_active: Optional[bool] = None


class MobileOperatorPrefixResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    country_code: str
    operator_code: str
    operator_name: str
    national_prefix: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
