"""Client API schemas for CRUD operations."""
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field, field_validator
import re


class ClientBase(BaseModel):
    """Base client schema with common fields."""
    full_name: str = Field(..., min_length=2, max_length=256)
    phone: Optional[str] = Field(None, description="Phone number (e.g., +998901234567)")
    passport_series: Optional[str] = Field(None, min_length=2, max_length=10)
    pinfl: Optional[str] = Field(None, min_length=14, max_length=14)
    date_of_birth: Optional[date] = None
    region: Optional[str] = Field(None, min_length=2, max_length=128)
    district: Optional[str] = Field(None, min_length=2, max_length=128)
    address: Optional[str] = Field(None, min_length=5, max_length=512)

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r'^\+998\d{9}$', v):
            raise ValueError('Phone number must be in format +998XXXXXXXXX')
        return v

    @field_validator('pinfl')
    @classmethod
    def validate_pinfl(cls, v: Optional[str]) -> Optional[str]:
        if v and not v.isdigit():
            raise ValueError('PINFL must contain only digits')
        return v


class ClientCreate(ClientBase):
    """Schema for creating a new client."""
    telegram_id: Optional[int] = Field(None, description="Telegram user ID (optional for offline registration)")
    client_code: Optional[str] = Field(None, description="Manual client code override")
    referrer_telegram_id: Optional[int] = Field(None, description="Referrer's Telegram ID")


class ClientUpdate(ClientBase):
    """Schema for updating an existing client."""
    full_name: Optional[str] = Field(None, min_length=2, max_length=256)
    client_code: Optional[str] = Field(None, description="Client code (must be unique)")


class ClientResponse(BaseModel):
    """Schema for client response."""
    id: int
    telegram_id: Optional[int]
    full_name: str
    phone: Optional[str]
    passport_series: Optional[str]
    pinfl: Optional[str]
    date_of_birth: Optional[date]
    region: Optional[str]
    district: Optional[str]
    address: Optional[str]
    client_code: Optional[str]
    referrer_telegram_id: Optional[int]
    referrer_client_code: Optional[str]
    is_logged_in: bool
    role: str
    language_code: str
    created_at: datetime
    current_balance: float = 0.0

    class Config:
        from_attributes = True


class PassportImageResponse(BaseModel):
    """Schema for passport image file IDs."""
    file_ids: list[str] = Field(default_factory=list, description="List of Telegram file IDs")


class ClientDeleteResponse(BaseModel):
    """Schema for client deletion response."""
    message: str
    deleted_client_id: int

# Response modeli
class CodePreviewResponse(BaseModel):
    preview_code: str
    prefix: str
    is_tashkent: bool