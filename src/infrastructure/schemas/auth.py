"""Authentication schemas."""
from datetime import datetime, date
from pydantic import BaseModel, Field, field_validator
import re
from src.infrastructure.tools.datetime_utils import get_current_time

class LoginRequest(BaseModel):
    """Login request schema."""
    client_code: str = Field(..., description="Client code (e.g., ABC123)")
    phone_number: str = Field(..., description="Phone number (e.g., +998901234567)")
    region: str | None = Field(None, description="Region code (optional)")
    district: str | None = Field(None, description="District code (optional)")
    telegram_id: int | None = Field(None, description="Telegram ID (optional)")
    timestamp: datetime = Field(default_factory=get_current_time, description="Request timestamp (Tashkent timezone)")

    @field_validator('phone_number')
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Validate phone format
        if not re.match(r'^\+998\d{9}$', v):
            raise ValueError('Phone number must be in format +998XXXXXXXXX')
        return v



class LoginResponse(BaseModel):
    """Login response schema."""
    client_code: str
    full_name: str
    phone: str | None
    telegram_id: int
    created_at: datetime
    # Session token fields (returned on successful login)
    access_token: str | None = None
    token_type: str | None = None
    role: str = "user"


class RegisterRequest(BaseModel):
    """Registration request schema (for validation)."""
    full_name: str = Field(..., min_length=2, max_length=256)
    passport_series: str = Field(..., min_length=2, max_length=10)
    pinfl: str = Field(..., min_length=14, max_length=14)
    region: str = Field(..., min_length=2, max_length=128)
    district: str = Field(..., min_length=2, max_length=128)
    address: str = Field(..., min_length=5, max_length=512)
    phone_number: str = Field(..., description="Phone number (e.g., +998901234567)")
    date_of_birth: date

    @field_validator('phone_number')
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if not re.match(r'^\+998\d{9}$', v):
            raise ValueError('Phone number must be in format +998XXXXXXXXX')
        return v

    @field_validator('pinfl')
    @classmethod
    def validate_pinfl(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError('PINFL must contain only digits')
        return v


class RegisterResponse(BaseModel):
    """Registration response schema."""
    client_code: str | None = None  # Will be None until approved
    full_name: str
    phone: str
    passport_series: str
    pinfl: str
    telegram_id: int
    message: str = "Registration successful"


class TelegramLoginRequest(BaseModel):
    """Telegram automatic login request schema."""
    init_data: str = Field(..., description="Telegram Web App initData string")


class ValidateInitDataRequest(BaseModel):
    """Telegram Web App initData validation request."""
    init_data: str = Field(..., description="Telegram Web App initData string")


class ValidateInitDataResponse(BaseModel):
    """Telegram Web App initData validation response."""
    valid: bool
    user_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    message: str | None = None


class ErrorResponse(BaseModel):
    """Error response schema."""
    detail: str
    error_code: str | None = None

class AuthMeResponse(BaseModel):
    """Profile and role response for the current authenticated user."""
    id: int
    client_code: str | None
    full_name: str
    phone: str | None
    telegram_id: int | None
    role: str
