"""External Flight Cargo API.

Read-only API for the webmandarin.uz backend to query ``flight_cargos``
by client code or track code.

Authentication
--------------
Every request must include the pre-shared API key::

    X-API-Key: <secret>

The key is configured via ``API_EXTERNAL_CARGO_KEY`` in ``.env``.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.schemas.external_cargo import (
    FlightCargoByTrackResponse,
    FlightCargoItem,
    FlightCargoListResponse,
)
from src.config import config
from src.infrastructure.database.dao.cargo_item import CargoItemDAO
from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO

from urllib.parse import urlparse

logger = logging.getLogger(__name__)

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
        session, code, limit=size, offset=offset,
    )

    return FlightCargoListResponse(
        items=[FlightCargoItem.model_validate(r) for r in rows],
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
        session, track_code.strip(),
    )
    if not cargo_items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Track code '{track_code.strip()}' not found in cargo_items.",
        )

    # Use the client_id from the first matched cargo_item.
    client_code = cargo_items[0].client_id
    if not client_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Track code '{track_code.strip()}' has no associated client code.",
        )

    code = client_code.strip().upper()
    offset = (page - 1) * size

    total = await FlightCargoDAO.count_all_by_client(session, code)
    rows = await FlightCargoDAO.get_all_by_client(
        session, code, limit=size, offset=offset,
    )

    return FlightCargoByTrackResponse(
        items=[FlightCargoItem.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
        client_code=code,
        resolved_from_track_code=track_code.strip().upper(),
    )
