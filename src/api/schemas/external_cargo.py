"""Response schemas for the External Cargo API."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class FlightCargoItem(BaseModel):
    """Single flight_cargos row — all columns exposed."""

    id: int
    flight_name: str
    client_id: str
    weight_kg: Decimal | None = None
    price_per_kg: Decimal | None = None
    photo_file_ids: str = "[]"
    comment: str | None = None
    is_sent: bool = False
    is_sent_date: datetime | None = None
    is_sent_web: bool = False
    is_sent_web_date: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FlightCargoListResponse(BaseModel):
    """Paginated response for flight cargo queries."""

    items: list[FlightCargoItem]
    total: int
    page: int = Field(ge=1)
    size: int = Field(ge=1, le=200)
    client_code: str


class FlightCargoByTrackResponse(FlightCargoListResponse):
    """Response for track-code based queries — adds the resolved track code."""

    resolved_from_track_code: str
