"""Client schemas for data validation."""
from datetime import date, datetime
from pydantic import BaseModel, Field


class ClientUpdate(BaseModel):
    """Schema for updating client data."""
    language_code: str | None = Field(None, max_length=5)
    phone: str | None = Field(None, max_length=20)
    passport_series: str | None = Field(None, max_length=10)
    pinfl: str | None = Field(None, max_length=14)
    date_of_birth: date | None = None
    region: str | None = Field(None, max_length=128)
    address: str | None = Field(None, max_length=512)
    passport_images: str | None = None
    is_logged_in: bool | None = None
    role: str | None = None


class ClientResponse(BaseModel):
    """Schema for client response."""
    id: int
    telegram_id: int
    full_name: str
    phone: str | None
    language_code: str
    role: str
    passport_series: str | None
    pinfl: str | None
    date_of_birth: date | None
    region: str | None
    address: str | None
    passport_images: str | None
    client_code: str | None
    referrer_telegram_id: int | None
    referrer_client_code: str | None
    is_logged_in: bool
    created_at: datetime

    class Config:
        from_attributes = True
