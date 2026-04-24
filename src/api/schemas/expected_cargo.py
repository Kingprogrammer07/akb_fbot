"""Pydantic schemas for the Expected Cargo API.

Covers all 10 endpoints:
  1. Bulk create
  2. Paginated search
  3. Replace-all track codes
  4. Rename flight
  5. Dynamic delete
  6. Excel export  (no request schema — query params only)
  7. Resolve client by track code
  8. Summary stats
  9. Stats by flight (paginated)
 10. Stats by client (paginated)
"""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Shared read schema
# ---------------------------------------------------------------------------


class ExpectedCargoItem(BaseModel):
    """Single record returned by search and resolve endpoints."""

    id: int
    flight_name: str
    client_code: str
    track_code: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Paginated response wrapper
# ---------------------------------------------------------------------------


class PaginatedExpectedCargoResponse(BaseModel):
    """Paginated list of expected cargo records."""

    items: list[ExpectedCargoItem]
    total: int
    page: int
    size: int
    total_pages: int


# ---------------------------------------------------------------------------
# API 1 — Bulk create
# ---------------------------------------------------------------------------


class BulkCreateExpectedCargoRequest(BaseModel):
    """Request body for creating multiple track codes in one shot."""

    flight_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Flight / shipment batch name, e.g. 'M123-2025'",
    )
    client_code: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Client code matching Client.extra_code or Client.client_code",
    )
    track_codes: list[str] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="List of tracking codes to register (1–500 per request)",
    )

    @field_validator("track_codes")
    @classmethod
    def validate_track_codes(cls, v: list[str]) -> list[str]:
        """Strip whitespace and reject blank entries."""
        if cleaned := [code.strip() for code in v if code.strip()]:
            return cleaned
        else:
            raise ValueError("track_codes must contain at least one non-empty value.")


class BulkCreateExpectedCargoResponse(BaseModel):
    """Result of the bulk-create operation."""

    created_count: int = Field(..., description="Number of new records inserted")
    duplicate_track_codes: list[str] = Field(
        ..., description="Track codes that already existed and were skipped"
    )


# ---------------------------------------------------------------------------
# API 3 — Replace-all
# ---------------------------------------------------------------------------


class ReplaceTrackCodesRequest(BaseModel):
    """Request body for the replace-all strategy."""

    flight_name: str = Field(..., min_length=1, max_length=255)
    client_code: str = Field(..., min_length=1, max_length=50)
    new_track_codes: list[str] = Field(
        ...,
        min_length=0,
        description=(
            "Complete replacement list. Pass an empty list to delete all "
            "track codes for this client in this flight without inserting new ones."
        ),
    )

    @field_validator("new_track_codes")
    @classmethod
    def deduplicate_codes(cls, v: list[str]) -> list[str]:
        """Deduplicate and strip whitespace from the replacement list."""
        seen: set[str] = set()
        result: list[str] = []
        for code in v:
            normalised = code.strip().upper()
            if normalised and normalised not in seen:
                seen.add(normalised)
                result.append(normalised)
        return result


class ReplaceTrackCodesResponse(BaseModel):
    """Result of the replace-all operation."""

    deleted_count: int
    created_count: int


# ---------------------------------------------------------------------------
# API 4 — Rename flight
# ---------------------------------------------------------------------------


class RenameFlightRequest(BaseModel):
    """Request body for bulk-renaming a flight across all its records."""

    old_flight_name: str = Field(..., min_length=1, max_length=255)
    new_flight_name: str = Field(..., min_length=1, max_length=255)

    @field_validator("new_flight_name")
    @classmethod
    def names_must_differ(cls, v: str, info) -> str:
        old = info.data.get("old_flight_name", "")
        if v.strip().lower() == old.strip().lower():
            raise ValueError("new_flight_name must differ from old_flight_name.")
        return v.strip()


class RenameFlightResponse(BaseModel):
    """Result of the bulk rename operation."""

    updated_count: int
    old_flight_name: str
    new_flight_name: str


# ---------------------------------------------------------------------------
# API 4b — Rename client code within a flight
# ---------------------------------------------------------------------------


class RenameClientCodeRequest(BaseModel):
    """Request body for renaming a client code within a specific flight."""

    flight_name: str = Field(..., min_length=1, max_length=255)
    old_client_code: str = Field(..., min_length=1, max_length=50)
    new_client_code: str = Field(..., min_length=1, max_length=50)

    @field_validator("new_client_code")
    @classmethod
    def strip_code(cls, v: str) -> str:
        return v.strip()


class RenameClientCodeResponse(BaseModel):
    """Result of the client code rename operation."""

    updated_count: int
    flight_name: str
    old_client_code: str
    new_client_code: str


# ---------------------------------------------------------------------------
# API 5 — Dynamic delete response
# ---------------------------------------------------------------------------


class DeleteExpectedCargoResponse(BaseModel):
    """Result of the dynamic delete operation."""

    deleted_count: int


# ---------------------------------------------------------------------------
# API 7 — Resolve client
# ---------------------------------------------------------------------------


class AlreadySentResponse(BaseModel):
    """409 error body — track code already processed (is_used=True)."""

    detail: str
    track_code: str
    flight_name: str | None = None


class ResolvedClientResponse(BaseModel):
    """
    Client information resolved from a track code lookup.

    Returned by the warehouse scanning bridge endpoint so that scanning
    a parcel barcode immediately reveals who the package belongs to.

    ``client_id`` and ``full_name`` are ``None`` when the cargo record exists
    but no matching Client row is registered in the system yet.
    """

    client_id: int | None = Field(
        None,
        description="Primary key of the Client record; null if client is not registered",
    )
    client_code: str = Field(
        ...,
        description="The active code of this client (extra_code > client_code priority)",
    )
    full_name: str | None = Field(
        None,
        description="Client's full name; null if client is not registered",
    )
    phone: str | None = None
    track_code: str = Field(..., description="The scanned track code that triggered the lookup")
    flight_name: str = Field(..., description="Flight this track code belongs to")


# ---------------------------------------------------------------------------
# API 8 — Summary stats
# ---------------------------------------------------------------------------


class ExpectedCargoSummaryStats(BaseModel):
    """Aggregate totals for the entire expected cargo table."""

    total_records: int = Field(..., description="Total number of track code rows")
    total_unique_flights: int = Field(..., description="Number of distinct flight names")
    total_unique_clients: int = Field(..., description="Number of distinct client codes")


# ---------------------------------------------------------------------------
# API 9 — Stats by flight (paginated)
# ---------------------------------------------------------------------------


class FlightStatItem(BaseModel):
    """Statistics row for a single flight."""

    flight_name: str
    client_count: int = Field(..., description="Number of distinct clients in this flight")
    track_code_count: int = Field(..., description="Total track codes in this flight")


class PaginatedFlightStatsResponse(BaseModel):
    """Paginated list of per-flight statistics."""

    items: list[FlightStatItem]
    total: int
    page: int
    size: int
    total_pages: int


# ---------------------------------------------------------------------------
# API 10 — Stats by client (paginated)
# ---------------------------------------------------------------------------


class ClientStatItem(BaseModel):
    """Statistics row for a single client."""

    client_code: str
    flight_count: int = Field(..., description="Number of distinct flights this client appears in")
    track_code_count: int = Field(..., description="Total track codes belonging to this client")


class PaginatedClientStatsResponse(BaseModel):
    """Paginated list of per-client statistics."""

    items: list[ClientStatItem]
    total: int
    page: int
    size: int
    total_pages: int


# ---------------------------------------------------------------------------
# API 11 — Summary by flight (collapsed client list)
# ---------------------------------------------------------------------------


class ClientSummaryItem(BaseModel):
    """
    Collapsed row for one client within a specific flight.

    Used by the frontend to render the grouped/collapsed list view where
    each client row shows a total count without loading individual track codes.
    """

    client_code: str
    total_track_codes: int = Field(
        ..., description="Number of track codes this client has in the queried flight"
    )


class PaginatedClientSummaryResponse(BaseModel):
    """Paginated collapsed client list for a specific flight."""

    flight_name: str
    items: list[ClientSummaryItem]
    total: int = Field(..., description="Total number of distinct clients in this flight")
    page: int
    size: int
    total_pages: int


# ---------------------------------------------------------------------------
# API 12 — Distinct flight list
# ---------------------------------------------------------------------------


class FlightListItem(BaseModel):
    """
    Single flight entry returned by the flight list endpoint.

    Includes aggregate counts so the frontend can show a summary badge
    (e.g. "M123-2025 — 15 clients, 320 track codes") without a second request.
    """

    flight_name: str
    client_count: int
    track_code_count: int


class FlightListResponse(BaseModel):
    """Full list of distinct flights (not paginated)."""

    items: list[FlightListItem]
    total: int = Field(..., description="Total number of distinct flights")


# ---------------------------------------------------------------------------
# API 13 — Empty flight registration
# ---------------------------------------------------------------------------


class CreateEmptyFlightRequest(BaseModel):
    """Request body for registering an empty flight (no cargo yet).

    Used to provision an ``A-`` ostatka flight entirely from the web UI,
    replacing the legacy workflow of opening a worksheet in Google Sheets
    purely to reserve a flight name.
    """

    flight_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Flight name to register (e.g. 'A-2026-04-24')",
    )

    @field_validator("flight_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("flight_name must be non-empty")
        return cleaned


class CreateEmptyFlightResponse(BaseModel):
    """Result of empty-flight registration."""

    flight_name: str = Field(..., description="Canonicalised flight name that was stored")
    created: bool = Field(
        ...,
        description=(
            "True when a new placeholder was inserted; False when the flight "
            "was already known (idempotent no-op)."
        ),
    )
