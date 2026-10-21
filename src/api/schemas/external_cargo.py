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
    #: A signed link (at least one hour) per photo, in ``photo_file_ids`` order.
    photo_urls: list[str] = Field(default_factory=list)

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
    #: The flight the track code is in (``cargo_items.flight_name``).
    flight_name: str | None = None
    #: Every track code of this client in that flight: the whole bag.
    track_codes: list[str] = Field(default_factory=list)
