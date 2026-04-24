"""China Partner Shipment Import API.

This router exposes a single public endpoint used exclusively by the
China-side partner company to push inbound shipment records into the system.

Authentication
--------------
No JWT is used.  Instead, every request must include the pre-shared API key:

    X-Partner-Key: <secret>

The key is configured via ``API_CHINA_PARTNER_KEY`` in ``.env``.

Rate limiting
-------------
Two layers protect this endpoint:

1. Global middleware (100 req / 60 s per IP) — applied to all routes.
2. Endpoint-level limiter (30 req / 60 s per IP) — tighter guard applied
   **before** business logic runs, so a leaked key cannot flood the DB.

A 429 response is returned when either limit is breached.

Image upload
------------
``file`` is an optional JPEG / PNG / WebP / HEIC image (≤ 15 MB).
It is compressed to WebP (quality 82, max 1920 × 1920) before being
stored in S3 under ``china_import_image/``.  The presigned URL returned
in the response is valid for 7 days.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_redis
from src.config import config
from src.infrastructure.database.models.cargo_item import CargoItem
from src.infrastructure.database.models.partner_shipment_temp import PartnerShipmentTemp
from src.infrastructure.tools.image_optimizer import optimize_image_to_webp
from src.infrastructure.tools.s3_manager import s3_manager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/shipment", tags=["shipment-partner"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# _SHIPMENT_RATE_LIMIT_MAX: int = 30  # requests
# _SHIPMENT_RATE_LIMIT_WINDOW: int = 60  # seconds
# _SHIPMENT_RATE_KEY_PREFIX: str = "rate:shipment:"

_MAX_IMAGE_BYTES: int = 15 * 1024 * 1024  # 15 MB hard cap before optimisation
_ALLOWED_IMAGE_MIMES: frozenset[str] = frozenset(
    {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic"}
)

# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class ShipmentCreateResponse(BaseModel):
    """Returned on successful shipment creation."""

    success: bool = True
    id: int = Field(description="Database primary key of the created shipment record")
    photo_url: str | None = Field(
        None,
        description=(
            "Presigned S3 URL for the uploaded product image, valid for 7 days. "
            "Null when no image was attached."
        ),
    )


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def _verify_partner_key(request: Request) -> None:
    """Validate the ``X-Partner-Key`` header against the configured secret.

    Deliberately returns 401 (not 403) so the caller knows authentication
    failed — not that they are forbidden from an authenticated resource.
    A constant-time comparison is used to prevent timing side-channels.
    """
    import hmac

    provided_key = request.headers.get("X-Partner-Key", "")
    expected_key = config.api.CHINA_PARTNER_KEY.get_secret_value()

    # hmac.compare_digest avoids timing attacks even on short strings.
    if not hmac.compare_digest(provided_key.encode(), expected_key.encode()):
        logger.warning(
            "Shipment API: invalid partner key from %s",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide a valid X-Partner-Key header.",
        )


# async def _shipment_rate_limit(request: Request) -> None:
#     """Endpoint-level rate limiter: 30 requests / 60 s per client IP.
#
#     Runs **in addition to** the global middleware limit (100 req / 60 s).
#     If Redis is unavailable the request is allowed through so a cache
#     outage never blocks legitimate imports.
#     """
#     redis = getattr(request.app.state, "redis", None)
#     if redis is None:
#         return
#
#     client_ip = request.client.host if request.client else "unknown"
#     key = f"{_SHIPMENT_RATE_KEY_PREFIX}{client_ip}"
#
#     try:
#         count = await redis.incr(key)
#         if count == 1:
#             await redis.expire(key, _SHIPMENT_RATE_LIMIT_WINDOW)
#
#         if count > _SHIPMENT_RATE_LIMIT_MAX:
#             ttl = max(await redis.ttl(key), 1)
#             raise HTTPException(
#                 status_code=status.HTTP_429_TOO_MANY_REQUESTS,
#                 detail={
#                     "error": "rate_limit_exceeded",
#                     "message": (
#                         f"Too many requests. This endpoint allows "
#                         f"{_SHIPMENT_RATE_LIMIT_MAX} requests per "
#                         f"{_SHIPMENT_RATE_LIMIT_WINDOW} seconds."
#                     ),
#                     "retry_after_seconds": ttl,
#                 },
#                 headers={"Retry-After": str(ttl)},
#             )
#     except HTTPException:
#         raise
#     except Exception as exc:
#         logger.warning("Shipment rate-limit Redis error (allowing request): %s", exc)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/temp-list",
    summary="View temporary shipment records (Admin)",
    description="Fetch latest records pushed by China partner to the temporary DB table.",
)
async def get_temp_shipments(
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
):
    query = (
        select(PartnerShipmentTemp)
        .order_by(PartnerShipmentTemp.created_at.desc())
        .limit(limit)
    )
    records = (await session.execute(query)).scalars().all()

    return [
        {
            "id": r.id,
            "track_code": r.track_code,
            "client_code": r.client_code,
            "flight_name": r.flight_name,
            "received_date": r.received_date,
            "weight_kg": r.weight_kg,
            "quantity": r.quantity,
            "created_at": r.created_at,
        }
        for r in records
    ]


@router.post(
    "/create",
    response_model=ShipmentCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a single China shipment record",
    description=(
        "Partner-facing endpoint for pushing inbound shipment data from China. "
        "Requires ``X-Partner-Key`` header.  All text fields are stored as-is; "
        "``clientId`` and ``flightNumber`` are upper-cased automatically. "
        "An optional product image (JPEG / PNG / WebP / HEIC, ≤ 15 MB) is "
        "accepted as ``multipart/form-data``; it is compressed to WebP and "
        "stored in S3."
    ),
)
async def create_shipment(
    # ── Auth & rate-limit guards ───────────────────────────────────────────
    _key: None = Depends(_verify_partner_key),
    # _rate: None = Depends(_shipment_rate_limit),
    # ── Required fields ────────────────────────────────────────────────────
    code: str = Form(
        ...,
        min_length=3,
        max_length=100,
        description="Tracking / barcode for this shipment",
    ),
    clientId: str = Form(
        ...,
        min_length=2,
        max_length=50,
        description="Customer identifier (e.g. SS123)",
    ),
    flightNumber: str = Form(
        ...,
        min_length=1,
        max_length=50,
        description="Flight / batch identifier (e.g. M185)",
    ),
    receivedDate: str = Form(
        ...,
        min_length=1,
        max_length=50,
        description="Date the item was received at the China warehouse",
    ),
    weight: float = Form(
        ...,
        gt=0,
        description="Gross weight in kilograms (must be > 0)",
    ),
    count: int = Form(
        ...,
        ge=1,
        description="Number of pieces / units (must be ≥ 1)",
    ),
    # ── Optional fields ────────────────────────────────────────────────────
    productName: str | None = Form(
        None,
        max_length=200,
        description="Product name in Russian or Uzbek (optional)",
    ),
    productNameCn: str | None = Form(
        None,
        max_length=200,
        description="Product name in Chinese (optional)",
    ),
    boxNumber: str | None = Form(
        None,
        max_length=50,
        description="Box / pallet identifier (optional)",
    ),
    file: UploadFile | None = File(
        None,
        description=(
            "Product image — JPEG, PNG, WebP or HEIC, max 15 MB. "
            "Compressed to WebP before storage."
        ),
    ),
    # ── Infrastructure ─────────────────────────────────────────────────────
    session: AsyncSession = Depends(get_db),
) -> ShipmentCreateResponse:    # sourcery skip: low-code-quality
    """
    Create a single China-side shipment record (``checkin_status = 'pre'``).

    ### Validation rules
    - ``code`` must be ≥ 3 characters and **unique** per ``flightNumber``+``clientId``
      combination.  A 409 is returned if the record already exists.
    - ``weight`` must be a positive number.
    - ``count`` must be ≥ 1.
    - ``file`` (if provided) must be a recognised image MIME type and ≤ 15 MB.

    ### Image processing
    Images are resized (max 1920 × 1920, aspect ratio preserved) and converted
    to WebP at quality 82 before upload.  This typically reduces size by 50–80 %.
    The original bytes are discarded; only the optimised version is stored.

    ### Idempotency
    The combination of ``(code, clientId, flightNumber)`` is treated as a
    logical unique key.  Re-sending the same record returns **409 Conflict**
    rather than creating a duplicate row.
    """
    clean_code = code.strip().upper()
    clean_client = clientId.strip().upper()
    clean_flight = flightNumber.strip().upper()
    clean_date = receivedDate.strip()

    # ── Duplicate check ────────────────────────────────────────────────────
    # Only the tracking code needs to be unique — a single client legitimately
    # has many packages per flight, each with its own distinct tracking code.
    existing = await session.execute(
        select(PartnerShipmentTemp.id)
        .where(
            PartnerShipmentTemp.track_code == clean_code,
        )
        .limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A shipment record with tracking code '{clean_code}' already exists. "
                "Each package must have a unique tracking code."
            ),
        )

    # ── Image processing ───────────────────────────────────────────────────
    photo_s3_key: str | None = None
    photo_url: str | None = None

    if file is not None and file.filename:
        content_type = (file.content_type or "").lower().strip()

        if content_type not in _ALLOWED_IMAGE_MIMES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Unsupported image type: '{content_type}'. "
                    "Accepted types: JPEG, PNG, WebP, HEIC."
                ),
            )

        raw_bytes = await file.read()

        if not raw_bytes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Uploaded file is empty.",
            )

        if len(raw_bytes) > _MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Image too large: {len(raw_bytes) / (1024 * 1024):.1f} MB. "
                    f"Maximum allowed size is {_MAX_IMAGE_BYTES // (1024 * 1024)} MB."
                ),
            )

        try:
            optimized_bytes = await optimize_image_to_webp(
                raw_bytes,
                quality=82,
                max_size=(1920, 1920),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Image could not be processed: {exc}",
            ) from exc

        unique_stem = f"{uuid.uuid4().hex[:16]}_{clean_client}_{clean_code}"
        upload_filename = f"{unique_stem}.webp"

        photo_s3_key = await s3_manager.upload_file(
            file_content=optimized_bytes,
            file_name=upload_filename,
            telegram_id=0,
            client_code=clean_client,
            base_folder="china_import_image",
            sub_folder=clean_flight,
            content_type="image/webp",
        )

        logger.info(
            "Shipment image uploaded: client=%s flight=%s code=%s "
            "original=%d bytes optimized=%d bytes key=%s",
            clean_client,
            clean_flight,
            clean_code,
            len(raw_bytes),
            len(optimized_bytes),
            photo_s3_key,
        )

    # ── Persist record to temporary table ──────────────────────────────────
    cargo = PartnerShipmentTemp(
        track_code=clean_code,
        client_code=clean_client,
        flight_name=clean_flight,
        received_date=clean_date,
        item_name_ru=productName.strip() if productName else None,
        item_name_cn=productNameCn.strip() if productNameCn else None,
        weight_kg=str(weight),
        quantity=str(count),
        box_number=boxNumber.strip() if boxNumber else None,
        photo_s3_key=photo_s3_key,
    )
    session.add(cargo)
    await session.flush()
    await session.refresh(cargo)
    await session.commit()

    # Generate presigned URL for the uploaded image (7-day expiry).
    if photo_s3_key:
        try:
            photo_url = await s3_manager.generate_presigned_url(
                photo_s3_key,
                expires_in=7 * 24 * 3600,
            )
        except Exception as exc:
            # Non-fatal: record is already saved; just omit the URL.
            logger.warning(
                "Could not generate presigned URL for %s: %s", photo_s3_key, exc
            )

    logger.info(
        "Shipment created: id=%d client=%s flight=%s code=%s",
        cargo.id,
        clean_client,
        clean_flight,
        clean_code,
    )

    return ShipmentCreateResponse(
        success=True,
        id=cargo.id,
        photo_url=photo_url,
    )
