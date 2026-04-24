"""Expected Cargo Admin Router.

Prefix : /admin/expected-cargos
Tags   : ["Expected Cargo"]

All endpoints require a valid Admin JWT (X-Admin-Authorization: Bearer <token>)
and the RBAC permission ``expected_cargo:manage``.

Endpoint summary:
  POST   /                     → Bulk create track codes            (API 1)
  GET    /                     → Paginated search                   (API 2)
  PUT    /replace               → Replace-all track codes for client (API 3)
  PATCH  /rename-flight         → Bulk rename flight                 (API 4)
  PATCH  /rename-client-code    → Rename client code in a flight     (API 4b)
  DELETE /                     → Dynamic delete                     (API 5)
  GET    /export/excel          → Streaming xlsx download            (API 6)
  GET    /resolve-client        → Bridge: track_code → Client        (API 7)
  GET    /stats                 → Aggregate summary totals           (API 8)
  GET    /stats/by-flight       → Per-flight stats (paginated)       (API 9)
  GET    /stats/by-client       → Per-client stats (paginated)       (API 10)
  GET    /summary               → Collapsed client list for a flight (API 11)
  GET    /flights               → Distinct flight list with counts   (API 12)
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import AdminJWTPayload, get_db, get_redis, require_permission
from src.api.schemas.expected_cargo import (
    AlreadySentResponse,
    BulkCreateExpectedCargoRequest,
    BulkCreateExpectedCargoResponse,
    CreateEmptyFlightRequest,
    CreateEmptyFlightResponse,
    DeleteExpectedCargoResponse,
    ExpectedCargoSummaryStats,
    FlightListResponse,
    PaginatedClientStatsResponse,
    PaginatedClientSummaryResponse,
    PaginatedExpectedCargoResponse,
    PaginatedFlightStatsResponse,
    RenameClientCodeRequest,
    RenameClientCodeResponse,
    RenameFlightRequest,
    RenameFlightResponse,
    ReplaceTrackCodesRequest,
    ReplaceTrackCodesResponse,
    ResolvedClientResponse,
)
from src.api.services.expected_cargo import ExpectedCargoService

router = APIRouter(
    prefix="/admin/expected-cargos",
    tags=["Expected Cargo"],
)

# ---------------------------------------------------------------------------
# Shared dependency alias for brevity
# ---------------------------------------------------------------------------

_RequireManage = Depends(require_permission("expected_cargo", "manage"))


# ===========================================================================
# API 1 — Bulk create track codes
# ===========================================================================


from datetime import timezone
@router.post(
    "",
    response_model=BulkCreateExpectedCargoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Bulk create expected cargo track codes",
)
async def bulk_create_expected_cargo(
    body: BulkCreateExpectedCargoRequest,
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
) -> BulkCreateExpectedCargoResponse:
    """
    Register one or more tracking codes under a given flight and client.

    Existing track codes are skipped without raising an error; they are
    reported back in ``duplicate_track_codes`` so the caller knows which
    entries were already present.

    **Input:** flight_name, client_code, track_codes (1–500 items)
    **Output:** created_count, duplicate_track_codes
    """
    return await ExpectedCargoService.bulk_create(
        session=session,
        flight_name=body.flight_name,
        client_code=body.client_code,
        track_codes=body.track_codes,
    )


# ===========================================================================
# API 2 — Paginated search
# ===========================================================================


@router.get(
    "",
    response_model=PaginatedExpectedCargoResponse,
    summary="Search expected cargo (paginated)",
)
async def search_expected_cargo(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(50, ge=1, le=1000, description="Records per page"),
    flight_name: str | None = Query(
        None,
        description=(
            "Filter by exact flight name. When provided, client_code and "
            "track_code become secondary refinements within this flight."
        ),
    ),
    client_code: str | None = Query(None, description="Filter by exact client code"),
    track_code: str | None = Query(None, description="Partial track code search"),
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
) -> PaginatedExpectedCargoResponse:
    """
    Return a paginated list of expected cargo records with optional filters.

    **Filter logic:**
    - `flight_name` provided → primary scope is flight; other params narrow within it.
    - `flight_name` absent   → global search across all flights.
    """
    return await ExpectedCargoService.search(
        session=session,
        page=page,
        size=size,
        flight_name=flight_name,
        client_code=client_code,
        track_code=track_code,
    )


# ===========================================================================
# API 3 — Replace-all track codes for a client in a flight
# ===========================================================================


@router.put(
    "/replace",
    response_model=ReplaceTrackCodesResponse,
    summary="Replace all track codes for a client in a flight",
)
async def replace_track_codes(
    body: ReplaceTrackCodesRequest,
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
) -> ReplaceTrackCodesResponse:
    """
    Atomically delete all existing track codes for `flight_name` + `client_code`
    and insert `new_track_codes` in their place (single DB transaction).

    Pass an empty list for `new_track_codes` to clear the client's codes without
    adding new ones.

    **Input:** flight_name, client_code, new_track_codes
    **Output:** deleted_count, created_count
    """
    return await ExpectedCargoService.replace_track_codes(
        session=session,
        flight_name=body.flight_name,
        client_code=body.client_code,
        new_track_codes=body.new_track_codes,
    )


# ===========================================================================
# API 4 — Bulk rename flight
# ===========================================================================


@router.patch(
    "/rename-flight",
    response_model=RenameFlightResponse,
    summary="Rename a flight across all its expected cargo records",
)
async def rename_flight(
    body: RenameFlightRequest,
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
) -> RenameFlightResponse:
    """
    Update `flight_name` for every record that currently matches `old_flight_name`.

    Returns 404 if no records are found (prevents silent no-ops from typos).

    **Input:** old_flight_name, new_flight_name
    **Output:** updated_count, old_flight_name, new_flight_name
    """
    return await ExpectedCargoService.rename_flight(
        session=session,
        old_flight_name=body.old_flight_name,
        new_flight_name=body.new_flight_name,
    )


# ===========================================================================
# API 4b — Rename client code within a flight
# ===========================================================================


@router.patch(
    "/rename-client-code",
    response_model=RenameClientCodeResponse,
    summary="Rename a client code within a specific flight",
)
async def rename_client_code(
    body: RenameClientCodeRequest,
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
) -> RenameClientCodeResponse:
    """
    Update `client_code` for every record that matches `flight_name` + `old_client_code`.

    Returns 404 if no records are found (prevents silent no-ops from typos).

    **Input:** flight_name, old_client_code, new_client_code
    **Output:** updated_count, flight_name, old_client_code, new_client_code
    """
    return await ExpectedCargoService.rename_client_code(
        session=session,
        flight_name=body.flight_name,
        old_client_code=body.old_client_code,
        new_client_code=body.new_client_code,
    )


# ===========================================================================
# API 5 — Dynamic delete
# ===========================================================================


@router.delete(
    "",
    response_model=DeleteExpectedCargoResponse,
    summary="Delete expected cargo records (dynamic filter)",
)
async def delete_expected_cargo(
    flight_name: str | None = Query(
        None,
        description=(
            "If provided alone → delete ALL records for this flight. "
            "If combined with client_code → delete only that client's records in this flight."
        ),
    ),
    client_code: str | None = Query(
        None,
        description=(
            "If provided alone → global delete: remove all records for this "
            "client across every flight."
        ),
    ),
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
) -> DeleteExpectedCargoResponse:
    """
    Delete records according to the provided filter combination.

    | flight_name | client_code | Behaviour                                          |
    |-------------|-------------|----------------------------------------------------|
    | ✓           | —           | Delete **all** records for this flight             |
    | ✓           | ✓           | Delete only this **client** in this flight         |
    | —           | ✓           | Global delete across **all flights** for client    |
    | —           | —           | **400 Bad Request** — at least one param required  |

    Returns 404 if no records match the given filters.
    """
    return await ExpectedCargoService.dynamic_delete(
        session=session,
        flight_name=flight_name,
        client_code=client_code,
    )


# ===========================================================================
# API 6 — Streaming Excel export
# ===========================================================================


_EXPORT_COOLDOWN_SECONDS = 30


@router.get(
    "/export/excel",
    summary="Export expected cargo to Excel (.xlsx)",
    response_class=StreamingResponse,
)
async def export_expected_cargo_excel(
    flight_name: str | None = Query(
        None,
        description="Filter by flight name. Leave empty to export ALL records.",
    ),
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> StreamingResponse:
    """
    Stream an Excel (.xlsx) file with expected cargo data.

    **Worksheet layout:**
    - Each distinct flight name gets its own worksheet tab.
    - Within each sheet, client groups are visually separated (first row shaded).
    - Column T/R resets to 1 on every sheet.

    **Rate limit:**
    - Each admin may trigger this export at most once every 30 seconds.
    - Subsequent requests within the cooldown window receive **429 Too Many Requests**
      with a `Retry-After` header indicating remaining seconds.
    """
    # ── Per-admin export cooldown (Redis TTL key) ──────────────────────────
    cooldown_key = f"excel_export_cooldown:{admin.admin_id}"
    ttl: int = await redis.ttl(cooldown_key)

    if ttl > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Eksport {ttl} soniyadan keyin qayta mavjud bo'ladi."
            ),
            headers={"Retry-After": str(ttl)},
        )

    buffer = await ExpectedCargoService.generate_excel(
        session=session,
        flight_name=flight_name,
    )

    # Lock this admin out for the cooldown window only after a successful build.
    await redis.setex(cooldown_key, _EXPORT_COOLDOWN_SECONDS, "1")

    filename_part = flight_name.replace(" ", "_") if flight_name else "all"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"expected_cargo_{filename_part}_{timestamp}.xlsx"

    return StreamingResponse(
        content=buffer,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ===========================================================================
# API 7 — Resolve client by track code
# ===========================================================================


@router.get(
    "/resolve-client",
    response_model=ResolvedClientResponse,
    responses={409: {"model": AlreadySentResponse, "description": "Trek kodi allaqachon yuborilgan (is_used=True)"}},
    summary="Resolve a track code to its owning Client",
)
async def resolve_client_by_track_code(
    track_code: str = Query(
        ...,
        min_length=1,
        description="The tracking code to look up",
    ),
    flight_name: str | None = Query(
        None,
        description="Optional: narrow the search to a specific flight",
    ),
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
) -> ResolvedClientResponse:
    """
    Warehouse scanning bridge: given a `track_code`, return the Client who owns it.

    Lookup order:
      1. Find the `ExpectedFlightCargo` row by track_code.
      2. Resolve its `client_code` → `Client` record (priority: extra_code → client_code).

    Returns 404 only if the track code is not in the expected cargo table.
    If the Client record does not exist, the response still succeeds with
    ``client_id=null`` and ``full_name=null``.
    """
    return await ExpectedCargoService.resolve_client(
        session=session,
        track_code=track_code,
        flight_name=None,  # flight_name is currently unused in the service but accepted for potential future filtering needs
        # flight_name=flight_name,
    )


# ===========================================================================
# API 8 — Summary stats
# ===========================================================================


@router.get(
    "/stats",
    response_model=ExpectedCargoSummaryStats,
    summary="Expected cargo aggregate summary",
)
async def get_expected_cargo_stats(
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
) -> ExpectedCargoSummaryStats:
    """
    Return aggregate totals for the entire expected cargo table.

    No filters, no pagination — just the three headline numbers:
    total records, distinct flights, distinct clients.
    """
    return await ExpectedCargoService.get_summary_stats(session=session)


# ===========================================================================
# API 9 — Stats by flight (paginated)
# ===========================================================================


@router.get(
    "/stats/by-flight",
    response_model=PaginatedFlightStatsResponse,
    summary="Per-flight expected cargo statistics (paginated)",
)
async def get_stats_by_flight(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(50, ge=1, le=1000, description="Rows per page"),
    client_code: str | None = Query(
        None,
        description="Optional — show only flights that contain this client",
    ),
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
) -> PaginatedFlightStatsResponse:
    """
    Return per-flight statistics ordered by track code count (busiest first).

    Each item shows: flight_name, how many distinct clients, total track codes.
    Optionally filter to flights containing a specific `client_code`.
    """
    return await ExpectedCargoService.get_stats_by_flight(
        session=session,
        page=page,
        size=size,
        client_code=client_code,
    )


# ===========================================================================
# API 10 — Stats by client (paginated)
# ===========================================================================


@router.get(
    "/stats/by-client",
    response_model=PaginatedClientStatsResponse,
    summary="Per-client expected cargo statistics (paginated)",
)
async def get_stats_by_client(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(50, ge=1, le=1000, description="Rows per page"),
    flight_name: str | None = Query(
        None,
        description="Optional — show only clients present in this flight",
    ),
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
) -> PaginatedClientStatsResponse:
    """
    Return per-client statistics ordered by track code count (most cargo first).

    Each item shows: client_code, how many distinct flights, total track codes.
    Optionally filter to clients in a specific `flight_name`.
    """
    return await ExpectedCargoService.get_stats_by_client(
        session=session,
        page=page,
        size=size,
        flight_name=flight_name,
    )


# ===========================================================================
# API 11 — Summary: collapsed client list for a specific flight
# ===========================================================================


@router.get(
    "/summary",
    response_model=PaginatedClientSummaryResponse,
    summary="Collapsed client list for a flight (count per client)",
)
async def get_clients_summary_by_flight(
    flight_name: str = Query(
        ...,
        min_length=1,
        description="Flight name to scope the summary to (required)",
    ),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(50, ge=1, le=1000, description="Rows per page"),
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
) -> PaginatedClientSummaryResponse:
    """
    Return each client's track code count within a specific flight.

    Designed for the **collapsed list view**: the frontend renders a row per
    client showing `total_track_codes` as a badge, then expands on demand by
    calling `GET /` with `flight_name + client_code` to load the actual codes.

    This endpoint is intentionally fast — it runs a single `GROUP BY` query
    and never loads individual track code rows.

    **Response example:**
    ```json
    {
      "flight_name": "M123-2025",
      "items": [
        { "client_code": "STCH3", "total_track_codes": 14 },
        { "client_code": "AD001", "total_track_codes":  6 }
      ],
      "total": 2, "page": 1, "size": 50, "total_pages": 1
    }
    ```
    """
    return await ExpectedCargoService.get_clients_summary_by_flight(
        session=session,
        flight_name=flight_name,
        page=page,
        size=size,
    )


# ===========================================================================
# API 12 — Distinct flight list
# ===========================================================================


@router.post(
    "/flights",
    response_model=CreateEmptyFlightResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register an empty flight (no cargo yet)",
)
async def create_empty_flight(
    body: CreateEmptyFlightRequest,
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
) -> CreateEmptyFlightResponse:
    """
    Register a flight name as a placeholder so it appears in the listings
    without needing any cargo yet.  Primary use-case: provisioning ``A-``
    ostatka flights entirely from the web UI, replacing the legacy
    workflow of opening a fresh worksheet in Google Sheets.

    **Behaviour**
    - Creates a single sentinel row (``is_placeholder=true``, hidden from
      every read/stat/export query) tagged to the target flight.
    - Idempotent — calling with an already-known flight returns 201 with
      ``created=false`` and no row is inserted.
    - The placeholder is removed automatically the moment the first real
      track code is added to the flight via ``POST /``.

    **Input:** flight_name
    **Output:** flight_name (canonicalised), created (bool)
    """
    return await ExpectedCargoService.create_empty_flight(
        session=session,
        flight_name=body.flight_name,
    )


@router.get(
    "/flights",
    response_model=FlightListResponse,
    summary="List all distinct flights with aggregate counts",
)
async def get_flight_list(
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(get_db),
) -> FlightListResponse:
    """
    Return all distinct flight names together with their aggregate counts.

    Not paginated — flight names are few in practice and the full list is
    needed to populate dropdowns, tabs, and navigation menus.

    **Response example:**
    ```json
    {
      "items": [
        { "flight_name": "M123-2025", "client_count": 50, "track_code_count": 320 },
        { "flight_name": "M124-2025", "client_count": 30, "track_code_count": 180 }
      ],
      "total": 2
    }
    ```
    """
    return await ExpectedCargoService.get_flight_list(session=session)
