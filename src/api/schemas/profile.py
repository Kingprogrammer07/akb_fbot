from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, validator

class ProfileResponse(BaseModel):
    """Profile information response."""
    full_name: str
    phone: str
    client_code: str
    extra_code: Optional[str] = None
    passport_series: str
    pinfl: str
    date_of_birth: Optional[str] = None  # Format: DD.MM.YYYY
    region: str
    district: Optional[str] = None
    address: str
    created_at: str  # Format: DD.MM.YYYY HH:MM
    referral_count: int
    passport_images: List[str] = Field(default_factory=list)
    telegram_id: int

class UpdateProfileRequest(BaseModel):
    """Request to update profile fields."""
    full_name: Optional[str] = None
    phone: Optional[str] = None
    region: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None

    @validator('full_name')
    def validate_name(cls, v):
        if v and len(v) < 2:
            raise ValueError("Name must be at least 2 characters")
        return v

    @validator('phone')
    def validate_phone(cls, v):
        if v:
            # Frontend ba'zida '+' belgisisiz yuboradi — avtomatik qo'shamiz
            if not v.startswith("+"):
                v = "+" + v
            if len(v) < 10:
                raise ValueError("Phone number is too short")
        return v
        
    @validator('address')
    def validate_address(cls, v):
        if v and len(v) < 5:
            raise ValueError("Address must be at least 5 characters")
        return v

class SessionLogItem(BaseModel):
    date: str
    client_code: str
    event_type: str
    username: Optional[str] = None

class SessionHistoryResponse(BaseModel):
    logs: List[SessionLogItem]
