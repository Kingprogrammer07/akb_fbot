"""Extra Passports API schemas."""
import json
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ExtraPassportResponse(BaseModel):
    """Single extra passport response."""

    id: int
    passport_series: str
    pinfl: str
    date_of_birth: date
    image_urls: list[str] = Field(default_factory=list)
    created_at: datetime

    class Config:
        from_attributes = True

    @field_validator("image_urls", mode="before")
    @classmethod
    def parse_image_urls(cls, v):
        """Parse JSON string from DB into a list of strings."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        if v is None:
            return []
        return v


class ExtraPassportListResponse(BaseModel):
    """Paginated list of extra passports."""

    items: list[ExtraPassportResponse]
    total: int
    page: int
    size: int


class ExtraPassportDeleteResponse(BaseModel):
    """Response after deleting a passport."""

    success: bool = True
    message: str = "Passport deleted successfully"
