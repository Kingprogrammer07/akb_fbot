"""External Flight Cargo API.

Read-only API for the webmandarin.uz backend to query ``flight_cargos``
by client code or track code.

Authentication
--------------
Every request must include the pre-shared API key::

    X-API-Key: <secret>

The key is configured via ``API_EXTERNAL_CARGO_KEY`` in ``.env``.

Photos
------
Each item carries ``photo_urls``: one signed link per photo, served by
``GET /external/photos/{cargo_id}/{index}``. The partner's browser shows them
in ``<img>`` and its server copies them, and neither can send the key, so the
photo route takes no key: the link's signature is the proof (see
``src/api/utils/external_photo_links.py``). Links start with
``API_EXTERNAL_PUBLIC_ORIGIN`` (e.g. ``https://bot.akbcargo.uz``).
"""

from __future__ import annotations

import hmac
import logging
import time
from collections.abc import Sequence
from urllib.parse import urlencode, urlparse, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import Response
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import json

from src.api.dependencies import get_db, get_redis
from src.api.schemas.external_cargo import (
    FlightCargoByTrackResponse,
    FlightCargoItem,
    FlightCargoListResponse,
    UztezCargoItemDetail,
    UztezClientReport,
    UztezFlightListItem,
    UztezFlightListResponse,
    UztezFlightReportsResponse,
)
from src.api.services.telegram_file_service import TelegramFileService
from src.api.services.verification.utils import parse_photo_file_ids
from src.api.utils.external_photo_links import (
    link_expiry,
    photo_link_valid,
    photo_signature,
)
from src.bot.bot_instance import bot
from src.config import config
from src.infrastructure.database.dao.cargo_item import CargoItemDAO
from src.infrastructure.database.dao.expected_cargo import ExpectedFlightCargoDAO
from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
from src.infrastructure.database.dao.partner import PartnerDAO
from src.infrastructure.database.models.cargo_item import CargoItem
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.services.flight_display import (
    FlightDisplay,
    resolve_partner_for_codes,
)
from src.infrastructure.tools.datetime_utils import get_current_time
from src.infrastructure.tools.s3_manager import s3_manager

logger = logging.getLogger(__name__)

#: Same ceiling the partner applies when it copies a photo.
PHOTO_MAX_BYTES = 15 * 1024 * 1024

#: The photo report allows 10 per row; anything past this gets no link.
MAX_PHOTOS_PER_ROW = 50

PHOTO_ROUTE_NAME = "external_cargo_photo"

# Allowed domains for webmandarin.uz and local development
_ALLOWED_DOMAINS = frozenset(
    {"webmandarin.uz", "bot.webmandarin.uz", "localhost", "127.0.0.1"}
)


def _is_allowed_origin(origin_or_url: str) -> bool:
    """Check if the provided Origin or Referer matches the allowed domains."""
    try:
        url = origin_or_url if "://" in origin_or_url else f"http://{origin_or_url}"
        hostname = urlparse(url).hostname
        if not hostname:
            return False
        hostname = hostname.lower()
        return hostname in _ALLOWED_DOMAINS or hostname.endswith(".webmandarin.uz")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/external", tags=["external-cargo"])


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


async def _verify_external_key(request: Request) -> None:
    """Validate the ``X-API-Key`` header and allowed origin/domain.

    Uses ``hmac.compare_digest`` for timing-safe comparison to prevent
    timing side-channel attacks.
    """
    provided = request.headers.get("X-API-Key", "")
    expected = config.api.EXTERNAL_CARGO_KEY.get_secret_value()

    if not hmac.compare_digest(provided.encode(), expected.encode()):
        logger.warning(
            "External Cargo API: invalid key from %s",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide a valid X-API-Key header.",
        )

    # Domain / Origin check (enforced when Origin or Referer header is present)
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if origin and not _is_allowed_origin(origin):
        logger.warning(
            "External Cargo API: unauthorized origin %r from %s",
            origin,
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Origin '{origin}' is not allowed to access this API.",
        )


# ---------------------------------------------------------------------------
# Photo links and bag lookup
# ---------------------------------------------------------------------------


def _https_origin(value: str | None) -> str | None:
    """``https://host[:port]`` of ``value``, or None unless it is a plain https URL."""
    try:
        parts = urlsplit((value or "").strip())
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname or "@" in parts.netloc:
        return None
    return f"https://{parts.netloc}"


def _public_origin(request: Request) -> str:
    """Where the partner reaches this API from outside.

    The configured origin wins; the webhook URL is the same public host in a
    normal deployment; the request's own host is the last resort. Always https:
    the partner refuses any other photo link.
    """
    for candidate in (config.api.EXTERNAL_PUBLIC_ORIGIN, config.telegram.WEBHOOK_URL):
        origin = _https_origin(candidate)
        if origin:
            return origin
    return f"https://{request.url.netloc}"


def _photo_links(
    request: Request, origin: str, row: FlightCargo, expires_at: int
) -> list[str]:
    links: list[str] = []
    file_ids = parse_photo_file_ids(row.photo_file_ids)[:MAX_PHOTOS_PER_ROW]
    for index, file_id in enumerate(file_ids):
        if not file_id.strip():
            continue
        path = request.app.url_path_for(
            PHOTO_ROUTE_NAME, cargo_id=str(row.id), index=str(index)
        )
        query = urlencode(
            {"exp": expires_at, "sig": photo_signature(row.id, index, expires_at)}
        )
        links.append(f"{origin}{path}?{query}")
    return links


def _items(request: Request, rows: Sequence[FlightCargo]) -> list[FlightCargoItem]:
    origin = _public_origin(request)
    expires_at = link_expiry()
    items: list[FlightCargoItem] = []
    for row in rows:
        item = FlightCargoItem.model_validate(row)
        item.photo_urls = _photo_links(request, origin, row, expires_at)
        items.append(item)
    return items


async def _bag_track_codes(
    session: AsyncSession, flight_name: str, client_id: str
) -> list[str]:
    """Every track code of this client in this flight: one bag.

    Exact match on the values stored on the scanned parcel's own row. A
    pattern match (``ilike``) would read ``_`` in a code as a wildcard and
    could hand the partner another client's parcels.
    """
    result = await session.execute(
        select(CargoItem.track_code)
        .where(
            CargoItem.client_id == client_id,
            CargoItem.flight_name == flight_name,
            CargoItem.track_code.isnot(None),
        )
        .order_by(CargoItem.id)
    )
    codes = (code.strip().upper() for code in result.scalars() if code)
    return list(dict.fromkeys(code for code in codes if code))


_IMAGE_SIGNATURES: tuple[tuple[bytes, int, str], ...] = (
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"GIF87a", 0, "image/gif"),
    (b"GIF89a", 0, "image/gif"),
    (b"WEBP", 8, "image/webp"),
)


def _image_type(data: bytes) -> str | None:
    """The raster type the bytes really are, or None.

    Decided from the bytes, never from the stored content type: whatever was
    uploaded, this host only ever serves something a browser renders as a
    picture, never as a page.
    """
    for magic, offset, media_type in _IMAGE_SIGNATURES:
        if data[offset : offset + len(magic)] == magic:
            if media_type == "image/webp" and data[:4] != b"RIFF":
                continue
            return media_type
    return None


def _is_s3_key(file_id: str) -> bool:
    # Telegram file ids are base64url; S3 keys always carry a folder or an
    # extension. Same rule as the client report service.
    return "/" in file_id or "." in file_id


async def _read_photo(file_id: str, redis: Redis) -> bytes | None:
    if _is_s3_key(file_id):
        stored = await s3_manager.download_bytes(file_id, PHOTO_MAX_BYTES)
        return stored[0] if stored else None
    data = await TelegramFileService(bot, redis).download_file(file_id)
    if data is None or len(data) > PHOTO_MAX_BYTES:
        return None
    return data


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/flight-cargos",
    response_model=FlightCargoListResponse,
    summary="Get flight cargos by client code",
    description=(
        "Returns all ``flight_cargos`` rows for a given client code, "
        "paginated. Requires ``X-API-Key`` header."
    ),
)
async def get_by_client_code(
    request: Request,
    client_code: str = Query(
        ...,
        min_length=1,
        max_length=50,
        description="Client code to search for (e.g. H99-010020)",
    ),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(50, ge=1, le=200, description="Page size (max 200)"),
    _auth: None = Depends(_verify_external_key),
    session: AsyncSession = Depends(get_db),
) -> FlightCargoListResponse:
    code = client_code.strip().upper()
    offset = (page - 1) * size

    total = await FlightCargoDAO.count_all_by_client(session, code)
    rows = await FlightCargoDAO.get_all_by_client(
        session,
        code,
        limit=size,
        offset=offset,
    )

    return FlightCargoListResponse(
        items=_items(request, rows),
        total=total,
        page=page,
        size=size,
        client_code=code,
    )


@router.get(
    "/flight-cargos/by-track-code",
    response_model=FlightCargoByTrackResponse,
    summary="Resolve track code → client code, then return flight cargos",
    description=(
        "Looks up ``cargo_items`` by track code to determine the client code, "
        "then returns all ``flight_cargos`` for that client. "
        "Requires ``X-API-Key`` header."
    ),
)
async def get_by_track_code(
    request: Request,
    track_code: str = Query(
        ...,
        min_length=1,
        max_length=100,
        description="Track code to resolve (e.g. ABC123456)",
    ),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(50, ge=1, le=200, description="Page size (max 200)"),
    _auth: None = Depends(_verify_external_key),
    session: AsyncSession = Depends(get_db),
) -> FlightCargoByTrackResponse:
    cargo_items = await CargoItemDAO.get_by_track_code(
        session,
        track_code.strip(),
    )
    if not cargo_items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Track code '{track_code.strip()}' not found in cargo_items.",
        )

    # Use the client_id from the first matched cargo_item.
    scanned = cargo_items[0]
    client_code = scanned.client_id
    if not client_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Track code '{track_code.strip()}' has no associated client code.",
        )

    code = client_code.strip().upper()
    offset = (page - 1) * size

    total = await FlightCargoDAO.count_all_by_client(session, code)
    rows = await FlightCargoDAO.get_all_by_client(
        session,
        code,
        limit=size,
        offset=offset,
    )

    flight_name = (scanned.flight_name or "").strip() or None
    track_codes = (
        await _bag_track_codes(session, scanned.flight_name, client_code)
        if flight_name
        else []
    )

    return FlightCargoByTrackResponse(
        items=_items(request, rows),
        total=total,
        page=page,
        size=size,
        client_code=code,
        resolved_from_track_code=track_code.strip().upper(),
        flight_name=flight_name,
        track_codes=track_codes,
    )


@router.get(
    "/photos/{cargo_id}/{index}",
    name=PHOTO_ROUTE_NAME,
    summary="One photo of a flight_cargos row, by signed link",
    description=(
        "Opened from the ``photo_urls`` the other endpoints return. Takes no "
        "API key: the ``exp``/``sig`` pair is the proof, and it opens only "
        "this one photo until it expires."
    ),
    responses={200: {"content": {"image/jpeg": {}}}},
)
async def get_photo(
    cargo_id: int = Path(..., ge=1),
    index: int = Path(..., ge=0, lt=MAX_PHOTOS_PER_ROW),
    exp: int = Query(..., description="Expiry, Unix seconds"),
    sig: str = Query(..., pattern=r"^[0-9a-f]{64}$"),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> Response:
    if not photo_link_valid(cargo_id, index, exp, sig):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Photo link is invalid or has expired.",
        )

    row = await FlightCargoDAO.get_by_id(session, cargo_id)
    file_ids = parse_photo_file_ids(row.photo_file_ids) if row else []
    # Hand the connection back before a download that can take seconds.
    await session.close()
    file_id = file_ids[index].strip() if index < len(file_ids) else ""
    if not file_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found."
        )

    data = await _read_photo(file_id, redis)
    if data is None:
        logger.warning(
            "External Cargo API: photo %s/%s could not be read", cargo_id, index
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Photo storage did not return the photo.",
        )
    media_type = _image_type(data)
    if media_type is None:
        logger.warning(
            "External Cargo API: photo %s/%s is not a JPEG/PNG/WebP/GIF",
            cargo_id,
            index,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found."
        )

    max_age = max(0, min(exp - int(time.time()), 3600))
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Cache-Control": f"private, max-age={max_age}",
            "X-Content-Type-Options": "nosniff",
            # Shown in the partner's pages, so another origin may embed it.
            "Cross-Origin-Resource-Policy": "cross-origin",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.get(
    "/partner/uztez/flight-reports",
    response_model=UztezFlightReportsResponse,
    summary="Get all cargo reports for Uztez partner in a flight",
    description=(
        "Returns all cargo photo reports belonging to Uztez (partner code 'U') "
        "for the specified flight. Includes both real and masked flight names, "
        "weights, prices, items, track codes, and presigned photo URLs."
    ),
)
async def get_uztez_flight_reports(
    flight_name: str = Query(
        ...,
        min_length=1,
        max_length=100,
        description="Real flight name (e.g. M200)",
    ),
    _auth: None = Depends(_verify_external_key),
    session: AsyncSession = Depends(get_db),
) -> UztezFlightReportsResponse:
    flight_upper = flight_name.strip().upper()
    partner = await PartnerDAO.get_by_code(session, "U")
    if not partner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Uztez partner (code 'U') not found in database.",
        )

    # 1. Resolve masked flight name
    masked_flight = await FlightDisplay(partner).label(session, flight_upper)

    # 2. Fetch all cargo rows for this flight
    all_cargos = await FlightCargoDAO.get_by_flight(session, flight_upper, limit=10000)

    # 3. Filter for Uztez clients
    client_cargos: dict[str, list] = {}
    for cargo in all_cargos:
        c_code = cargo.client_id.strip().upper()
        p = await resolve_partner_for_codes(session, [c_code])
        if p and p.code.upper() == "U":
            client_cargos.setdefault(c_code, []).append(cargo)

    reports: list[UztezClientReport] = []
    total_flight_weight = 0.0

    for client_id, cargos in client_cargos.items():
        # Track codes
        track_codes = await ExpectedFlightCargoDAO.get_track_codes_by_flight_and_client(
            session, flight_upper, client_id
        )

        # Photos
        photo_urls: list[str] = []
        for cargo in cargos:
            try:
                raw_photos = json.loads(cargo.photo_file_ids or "[]")
                for p in raw_photos:
                    if "/" in p:
                        url = await s3_manager.generate_presigned_url(
                            p, expires_in=60 * 24 * 3600
                        )
                        photo_urls.append(url)
                    else:
                        photo_urls.append(p)
            except Exception:
                continue

        # Items and weights
        item_details: list[UztezCargoItemDetail] = []
        client_weight = 0.0
        for cargo in cargos:
            w = float(cargo.weight_kg or 0.0)
            client_weight += w
            price = float(cargo.price_per_kg or 0.0)
            item_details.append(
                UztezCargoItemDetail(
                    weight=round(w, 2),
                    price_usd=round(w * price, 2),
                    price_uzs=0.0,
                    category="Yuk",
                )
            )

        total_flight_weight += client_weight
        reports.append(
            UztezClientReport(
                client_id=client_id,
                track_codes=track_codes,
                total_weight=round(client_weight, 2),
                extra_charge=0.0,
                items=item_details,
                photo_urls=photo_urls,
                message_text="",
            )
        )

    return UztezFlightReportsResponse(
        event="cargo_photos_sent",
        flight_name=flight_upper,
        masked_flight_name=masked_flight or flight_upper,
        partner_code="U",
        partner_name=partner.display_name,
        sent_at=get_current_time().isoformat(),
        total_clients=len(reports),
        total_weight=round(total_flight_weight, 2),
        reports=reports,
    )


@router.get(
    "/partner/uztez/flights",
    response_model=UztezFlightListResponse,
    summary="Get paginated list of flights containing Uztez cargos",
    description=(
        "Returns a paginated list of flights from flight_cargos that contain "
        "cargo belonging to Uztez (partner code 'U'). Includes real and masked "
        "flight names, client counts, total weight, and cargo dates."
    ),
)
async def get_uztez_flights(
    page: int = Query(1, ge=1, description="Page number (starts at 1)"),
    size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    search: str | None = Query(None, description="Optional flight name search filter"),
    only_uztez: bool = Query(
        True,
        description="If true, only returns flights containing Uztez cargo. If false, returns all flights.",
    ),
    _auth: None = Depends(_verify_external_key),
    session: AsyncSession = Depends(get_db),
) -> UztezFlightListResponse:
    partner = await PartnerDAO.get_by_code(session, "U")
    if not partner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Uztez partner (code 'U') not found in database.",
        )

    offset = (page - 1) * size
    raw_rows, total = await FlightCargoDAO.get_uztez_flights(
        session,
        limit=size,
        offset=offset,
        search=search,
        only_uztez=only_uztez,
    )

    flight_display = FlightDisplay(partner)
    items: list[UztezFlightListItem] = []
    for r in raw_rows:
        masked = await flight_display.label(session, r["flight_name"])
        items.append(
            UztezFlightListItem(
                flight_name=r["flight_name"],
                masked_flight_name=masked or r["flight_name"],
                clients_count=r["clients_count"],
                cargos_count=r["cargos_count"],
                total_weight=r["total_weight"],
                latest_cargo_date=r["latest_cargo_date"],
            )
        )

    total_pages = (total + size - 1) // size if total > 0 else 0

    return UztezFlightListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
        total_pages=total_pages,
    )
