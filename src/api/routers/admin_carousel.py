"""Admin Carousel management endpoints.

All routes require a valid Admin JWT (X-Admin-Authorization: Bearer <token>)
and the RBAC permission listed below.

Permission map:
    carousel:read   → list all items (incl. inactive), stats
    carousel:create → upload media, create a new carousel item
    carousel:update → update an existing carousel item
    carousel:delete → hard-delete a carousel item (also removes S3 file)

Media upload flow:
    1. POST /admin/carousel/upload  →  upload file, get back s3_key + media_url
    2. POST /admin/carousel/        →  create item using the returned media_url
                                       (or an external URL if preferred)
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import AdminJWTPayload, get_db, get_redis, require_permission
from src.infrastructure.cache.keys import CacheKeys
from src.infrastructure.database.dao.admin_audit_log import AdminAuditLogDAO
from src.infrastructure.database.dao.carousel import CarouselDAO
from src.infrastructure.database.dao.carousel_item_media import (
    CarouselItemMediaDAO,
    MEDIA_LIMITS,
)
from src.infrastructure.database.models.carousel_item import CarouselItem
from src.infrastructure.database.models.carousel_item_media import CarouselItemMedia
from src.infrastructure.tools.image_optimizer import optimize_image_to_webp
from src.infrastructure.tools.s3_manager import s3_manager
from src.api.schemas.carousel import (
    CarouselItemCreate,
    CarouselItemResponse,
    CarouselItemStatsResponse,
    CarouselItemUpdate,
    CarouselMediaItemInput,
    CarouselMediaItemResponse,
    CarouselMediaUploadResponse,
    FEATURE_MEDIA_LIMITS,
    mime_to_media_type,
    size_limit_for,
)

logger = logging.getLogger(__name__)

# Set this logger to DEBUG so upload debug lines appear in stdout.
logger.setLevel(logging.DEBUG)

# Presigned URL lifetime: 7 days (S3 maximum for IAM-signed URLs).
# Cache TTL is 1 day shorter so Redis never hands out an already-expired link.
_PRESIGNED_EXPIRES_SEC: int = 7 * 24 * 3600        # 604 800 s
_PRESIGNED_CACHE_TTL_SEC: int = 6 * 24 * 3600      # 518 400 s

router = APIRouter(prefix="/admin/carousel", tags=["admin-carousel"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _delete_s3_media(s3_key: str | None) -> None:
    """Fire-and-forget S3 cleanup — logs on failure but never raises."""
    if not s3_key:
        return
    success = await s3_manager.delete_file(s3_key)
    if not success:
        logger.warning("Could not delete carousel S3 object: %s", s3_key)


async def _presigned_or_raw(s3_key: str | None, fallback_url: str, redis: Redis) -> str:
    """Return a presigned URL for an S3 key, or the raw URL if no key is set.

    Result is cached in Redis for 6 days (below the 7-day S3 expiry).
    """
    if not s3_key:
        return fallback_url

    cache_key = CacheKeys.carousel_presigned_url(s3_key)
    cached: str | bytes | None = await redis.get(cache_key)
    if cached:
        return cached if isinstance(cached, str) else cached.decode()

    presigned_url = await s3_manager.generate_presigned_url(
        s3_key,
        expires_in=_PRESIGNED_EXPIRES_SEC,
    )
    await redis.setex(cache_key, _PRESIGNED_CACHE_TTL_SEC, presigned_url)
    return presigned_url


async def _resolve_media_url(item: CarouselItem, redis: Redis) -> str:
    """Resolve the primary media URL for a carousel item."""
    return await _presigned_or_raw(item.media_s3_key, item.media_url, redis)


async def _resolve_media_items(
    media_entries: list[CarouselItemMedia],
    redis: Redis,
) -> list[CarouselMediaItemResponse]:
    """Resolve presigned URLs for all media entries of a feature item."""
    resolved: list[CarouselMediaItemResponse] = []
    for entry in media_entries:
        url = await _presigned_or_raw(entry.media_s3_key, entry.media_url, redis)
        resolved.append(
            CarouselMediaItemResponse(
                id=entry.id,
                media_type=entry.media_type,  # type: ignore[arg-type]
                media_url=url,
                media_s3_key=entry.media_s3_key,
                order=entry.order,
            )
        )
    return resolved


async def _build_item_response(
    item: CarouselItem,
    redis: Redis,
    total_views: int = 0,
    total_clicks: int = 0,
    as_stats: bool = False,
) -> CarouselItemResponse | CarouselItemStatsResponse:
    """Build a full response object for a carousel item, resolving all URLs."""
    primary_url = await _resolve_media_url(item, redis)
    media_items = await _resolve_media_items(item.media_items, redis)

    fields = dict(
        id=item.id,
        type=item.type,
        title=item.title,
        sub_title=item.sub_title,
        media_type=item.media_type,
        media_url=primary_url,
        media_s3_key=item.media_s3_key,
        action_url=item.action_url,
        text_color=item.text_color,
        gradient=item.gradient,
        order=item.order,
        is_active=item.is_active,
        created_at=item.created_at,
        media_items=media_items,
    )
    if as_stats:
        return CarouselItemStatsResponse(**fields, total_views=total_views, total_clicks=total_clicks)
    return CarouselItemResponse(**fields)


async def _validate_media_limits(
    session: AsyncSession,
    carousel_item_id: int,
    new_entries: list[CarouselMediaItemInput],
    replace_all: bool = False,
) -> None:
    """Raise HTTPException if adding entries would exceed per-type limits.

    When ``replace_all`` is True the check is against the new list only
    (existing entries will be wiped).  Otherwise it checks existing + new.
    """
    from collections import Counter
    incoming_counts: Counter[str] = Counter(e.media_type for e in new_entries)

    if replace_all:
        existing_counts: Counter[str] = Counter()
    else:
        existing_counts = Counter()
        for media_type in FEATURE_MEDIA_LIMITS:
            count = await CarouselItemMediaDAO.count_by_type(
                session, carousel_item_id, media_type
            )
            existing_counts[media_type] = count

    for media_type, limit in FEATURE_MEDIA_LIMITS.items():
        total = existing_counts[media_type] + incoming_counts[media_type]
        if total > limit:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"'{media_type}' uchun limit oshib ketdi: "
                    f"mavjud={existing_counts[media_type]}, "
                    f"yangi={incoming_counts[media_type]}, "
                    f"limit={limit}."
                ),
            )


async def _save_media_items(
    session: AsyncSession,
    carousel_item_id: int,
    entries: list[CarouselMediaItemInput],
) -> None:
    """Persist a list of media entries (already limit-validated)."""
    await CarouselItemMediaDAO.create_bulk(
        session,
        carousel_item_id,
        [
            {
                "media_type": e.media_type,
                "media_s3_key": e.media_s3_key,
                "media_url": e.media_url or "",
                "order": e.order,
            }
            for e in entries
        ],
    )


# ---------------------------------------------------------------------------
# Media upload
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    response_model=CarouselMediaUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Carousel uchun media faylni S3 ga yuklash",
)
async def upload_carousel_media(
    request: Request,
    file: UploadFile = File(..., description="Rasm (JPEG/PNG/WebP/HEIC), GIF yoki video (MP4/MOV/WebM)"),
    admin: AdminJWTPayload = Depends(require_permission("carousel", "create")),
) -> CarouselMediaUploadResponse:
    """
    Upload a media file to the S3 ``carousel/`` folder and return the public URL.

    **Supported types & limits:**
    | Type  | Formats                        | Max size |
    |-------|--------------------------------|----------|
    | image | JPEG, PNG, WebP, HEIC          | 50 MB    |
    | gif   | GIF                            | 50 MB    |
    | video | MP4, MOV, WebM, AVI, MPEG      | 200 MB   |

    Returns ``s3_key`` (for cleanup tracking) and ``media_url`` (public HTTPS URL
    ready to paste into the ``media_url`` field when creating a carousel item).
    """
    logger.debug(
        "UPLOAD DEBUG — headers: %s",
        dict(request.headers),
    )
    content_type = (file.content_type or "").lower()
    logger.debug(
        "UPLOAD DEBUG — filename=%r content_type=%r size_hint=%r",
        file.filename,
        content_type,
        file.size,
    )
    media_type = mime_to_media_type(content_type)
    logger.debug("UPLOAD DEBUG — resolved media_type=%r", media_type)

    if media_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Qo'llab-quvvatlanmaydigan fayl turi: {content_type!r}. "
                f"Ruxsat etilganlar: JPEG, PNG, WebP, HEIC, GIF, MP4, MOV, WebM."
            ),
        )

    raw_bytes = await file.read()

    if not raw_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Yuklangan fayl bo'sh.",
        )

    max_bytes = size_limit_for(media_type)
    if len(raw_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Fayl hajmi {len(raw_bytes) // (1024 * 1024)} MB — "
                f"{media_type} uchun ruxsat etilgan maksimal hajm "
                f"{max_bytes // (1024 * 1024)} MB."
            ),
        )

    # ------------------------------------------------------------------
    # Media processing:
    #   image → optimize + convert to WebP (smaller size, better quality)
    #   gif   → upload as-is (converting GIF to WebP kills animation in Pillow)
    #   video → upload as-is (no server-side transcoding)
    # ------------------------------------------------------------------
    upload_bytes = raw_bytes
    upload_content_type = content_type

    if media_type == "image":
        try:
            upload_bytes = await optimize_image_to_webp(raw_bytes)
            upload_content_type = "image/webp"
            logger.debug(
                "UPLOAD DEBUG — image optimized: %d → %d bytes",
                len(raw_bytes),
                len(upload_bytes),
            )
        except ValueError as exc:
            logger.warning("Image optimization failed, uploading original: %s", exc)
            # Fall back to original bytes so the upload still succeeds.
            upload_bytes = raw_bytes
            upload_content_type = content_type

    # Derive subfolder from media type so S3 stays organised.
    subfolder_map = {"image": "images", "gif": "gifs", "video": "videos"}
    sub_folder = subfolder_map[media_type]

    # Use .webp extension for optimized images; keep original ext for others.
    if media_type == "image" and upload_content_type == "image/webp":
        original_stem = (file.filename or "upload").rsplit(".", 1)[0]
        upload_filename = f"{uuid.uuid4().hex[:12]}_{original_stem}.webp"
    else:
        original_name = file.filename or f"upload.{content_type.split('/')[-1]}"
        upload_filename = f"{uuid.uuid4().hex[:12]}_{original_name}"

    s3_key = await s3_manager.upload_file(
        file_content=upload_bytes,
        file_name=upload_filename,
        telegram_id=0,
        client_code=f"adm{admin.admin_id}",
        base_folder="carousel",
        sub_folder=sub_folder,
        content_type=upload_content_type,
    )

    # Short-lived presigned URL for the upload response preview (1 hour).
    # The long-lived URL (7 days, Redis-cached) is generated when the item
    # is later fetched via GET /carousel — no need to cache here.
    preview_url = await s3_manager.generate_presigned_url(s3_key, expires_in=3600)

    logger.info(
        "Carousel media uploaded: admin=%d type=%s original_size=%d final_size=%d key=%s",
        admin.admin_id, media_type, len(raw_bytes), len(upload_bytes), s3_key,
    )

    return CarouselMediaUploadResponse(
        s3_key=s3_key,
        media_url=preview_url,
        media_type=media_type,
        size_bytes=len(upload_bytes),
    )


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=list[CarouselItemResponse],
    summary="Barcha carousel elementlari (inactive lar ham)",
)
async def list_all_carousel_items(
    admin: AdminJWTPayload = Depends(require_permission("carousel", "read")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> list[CarouselItemResponse]:
    """Return all carousel items including inactive ones for admin management."""
    items = await CarouselDAO.get_all(session)
    return [
        await _build_item_response(item, redis)  # type: ignore[misc]
        for item in items
    ]


@router.get(
    "/stats",
    response_model=list[CarouselItemStatsResponse],
    summary="Carousel elementlari ko'rish/bosish statistikasi bilan",
)
async def get_carousel_stats(
    admin: AdminJWTPayload = Depends(require_permission("carousel", "read")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> list[CarouselItemStatsResponse]:
    """Return all carousel items with their total views and clicks."""
    stats = await CarouselDAO.get_stats(session)
    return [
        await _build_item_response(  # type: ignore[misc]
            s["item"], redis,
            total_views=s["total_views"],
            total_clicks=s["total_clicks"],
            as_stats=True,
        )
        for s in stats
    ]


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=CarouselItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Yangi carousel elementi yaratish",
)
async def create_carousel_item(
    body: CarouselItemCreate,
    admin: AdminJWTPayload = Depends(require_permission("carousel", "create")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> CarouselItemResponse:
    """
    Create a new carousel item.

    **Ad type**: provide ``media_url`` or ``media_s3_key`` for the single media.

    **Feature type**: same as ad, OR provide ``media_items`` list for multi-media
    (up to 20 images, 20 GIFs, 5 videos).  Primary media fields and ``media_items``
    can both be supplied simultaneously.
    """
    # Validate feature multi-media limits before any DB write.
    if body.media_items:
        await _validate_media_limits(session, 0, body.media_items, replace_all=True)

    if body.media_s3_key:
        db_media_url = ""
        resolved_key: str | None = body.media_s3_key
    elif body.media_url:
        db_media_url = body.media_url
        resolved_key = None
    else:
        # Feature item with media_items only — no primary media required.
        db_media_url = ""
        resolved_key = None

    data = body.model_dump(exclude={"media_url", "media_s3_key", "media_items"})
    data["media_url"] = db_media_url
    data["media_s3_key"] = resolved_key

    item = await CarouselDAO.create(session, data)

    if body.media_items:
        await _save_media_items(session, item.id, body.media_items)

    await AdminAuditLogDAO.log(
        session=session,
        action="CREATED_CAROUSEL_ITEM",
        admin_id=admin.admin_id,
        role_snapshot=admin.role_name,
        details={
            "title": body.title,
            "type": body.type,
            "media_type": body.media_type,
            "has_s3_media": resolved_key is not None,
            "media_items_count": len(body.media_items) if body.media_items else 0,
        },
    )

    await session.commit()
    await session.refresh(item)
    return await _build_item_response(item, redis)  # type: ignore[return-value]


@router.put(
    "/{item_id}",
    response_model=CarouselItemResponse,
    summary="Carousel elementini yangilash",
)
async def update_carousel_item(
    item_id: int,
    body: CarouselItemUpdate,
    admin: AdminJWTPayload = Depends(require_permission("carousel", "update")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> CarouselItemResponse:
    """
    Update a carousel item.

    If ``media_s3_key`` is provided, the old S3 file (if any) is deleted and
    replaced with the new one.  Supply ``media_url`` to switch to an external
    link (the old S3 file is still deleted to avoid orphans).
    """
    item = await CarouselDAO.get_by_id(session, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{item_id} raqamli carousel elementi topilmadi.",
        )

    changes = body.model_dump(exclude_unset=True)
    old_s3_key: str | None = item.media_s3_key
    new_media_items: list[CarouselMediaItemInput] | None = changes.pop("media_items", None)

    # Validate new media_items limits before writing.
    if new_media_items is not None:
        if item.type != "feature":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="media_items faqat 'feature' tipidagi elementlar uchun.",
            )
        await _validate_media_limits(session, item.id, new_media_items, replace_all=True)

    # Determine whether the primary media source genuinely changed.
    s3_key_in_payload: str | None = changes.pop("media_s3_key", None) if "media_s3_key" in changes else None
    new_url: str | None = changes.pop("media_url", None) if "media_url" in changes else None

    s3_key_truly_changed = (
        s3_key_in_payload is not None
        and s3_key_in_payload != old_s3_key
    )
    switching_to_external_url = (
        new_url is not None
        and not s3_key_in_payload
        and new_url != item.media_url
    )

    if s3_key_truly_changed:
        changes["media_s3_key"] = s3_key_in_payload
        changes["media_url"] = ""
    elif switching_to_external_url:
        changes["media_url"] = new_url
        changes["media_s3_key"] = None

    updated = await CarouselDAO.update(session, item, changes)

    # Replace media_items list when supplied (wipe old, insert new).
    old_media_entries: list[CarouselItemMedia] = []
    if new_media_items is not None:
        old_media_entries = await CarouselItemMediaDAO.delete_all_for_item(session, item.id)
        await _save_media_items(session, item.id, new_media_items)

    await AdminAuditLogDAO.log(
        session=session,
        action="UPDATED_CAROUSEL_ITEM",
        admin_id=admin.admin_id,
        role_snapshot=admin.role_name,
        details={
            "item_id": item_id,
            "updated_fields": list(changes.keys()),
            "media_items_replaced": new_media_items is not None,
        },
    )

    await session.commit()

    # S3 cleanup after commit — orphaned primary file.
    old_file_is_orphaned = s3_key_truly_changed or switching_to_external_url
    if old_file_is_orphaned and old_s3_key:
        await redis.delete(CacheKeys.carousel_presigned_url(old_s3_key))
        await _delete_s3_media(old_s3_key)

    # S3 cleanup — orphaned media_items entries.
    for entry in old_media_entries:
        if entry.media_s3_key:
            await redis.delete(CacheKeys.carousel_presigned_url(entry.media_s3_key))
            await _delete_s3_media(entry.media_s3_key)

    await session.refresh(updated)
    return await _build_item_response(updated, redis)  # type: ignore[return-value]


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Carousel elementini o'chirish",
)
async def delete_carousel_item(
    item_id: int,
    admin: AdminJWTPayload = Depends(require_permission("carousel", "delete")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> None:
    """Hard-delete a carousel item and its associated stats.
    If the item had an S3-backed media file, it is also removed from S3.
    """
    item = await CarouselDAO.get_by_id(session, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{item_id} raqamli carousel elementi topilmadi.",
        )

    primary_s3_key: str | None = item.media_s3_key
    # Collect all media_items S3 keys before the CASCADE delete wipes them.
    media_entries_to_clean = list(item.media_items)

    deleted = await CarouselDAO.delete(session, item_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{item_id} raqamli carousel elementi topilmadi.",
        )

    await AdminAuditLogDAO.log(
        session=session,
        action="DELETED_CAROUSEL_ITEM",
        admin_id=admin.admin_id,
        role_snapshot=admin.role_name,
        details={
            "item_id": item_id,
            "had_s3_media": primary_s3_key is not None,
            "media_items_count": len(media_entries_to_clean),
        },
    )

    await session.commit()

    # Clean up primary S3 file.
    if primary_s3_key:
        await redis.delete(CacheKeys.carousel_presigned_url(primary_s3_key))
        await _delete_s3_media(primary_s3_key)

    # Clean up all media_items S3 files (CASCADE already removed DB rows).
    for entry in media_entries_to_clean:
        if entry.media_s3_key:
            await redis.delete(CacheKeys.carousel_presigned_url(entry.media_s3_key))
            await _delete_s3_media(entry.media_s3_key)


# ---------------------------------------------------------------------------
# Feature multi-media management
# ---------------------------------------------------------------------------

@router.post(
    "/{item_id}/media",
    response_model=CarouselMediaItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Feature elementiga media qo'shish",
)
async def add_media_to_feature_item(
    item_id: int,
    body: CarouselMediaItemInput,
    admin: AdminJWTPayload = Depends(require_permission("carousel", "update")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> CarouselMediaItemResponse:
    """
    Add a single media entry to a **feature** carousel item.

    Limits per item: images ≤ 20, GIFs ≤ 20, videos ≤ 5.

    Use the ``/upload`` endpoint first to get ``s3_key``, then pass it here.
    """
    item = await CarouselDAO.get_by_id(session, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{item_id} raqamli carousel elementi topilmadi.",
        )
    if item.type != "feature":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Media qo'shish faqat 'feature' tipidagi elementlar uchun.",
        )

    await _validate_media_limits(session, item_id, [body], replace_all=False)

    entry = await CarouselItemMediaDAO.create(
        session,
        carousel_item_id=item_id,
        media_type=body.media_type,
        media_s3_key=body.media_s3_key,
        media_url=body.media_url or "",
        order=body.order,
    )

    await session.commit()

    resolved_url = await _presigned_or_raw(entry.media_s3_key, entry.media_url, redis)
    return CarouselMediaItemResponse(
        id=entry.id,
        media_type=entry.media_type,  # type: ignore[arg-type]
        media_url=resolved_url,
        media_s3_key=entry.media_s3_key,
        order=entry.order,
    )


@router.delete(
    "/{item_id}/media/{media_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Feature elementidan media o'chirish",
)
async def remove_media_from_feature_item(
    item_id: int,
    media_id: int,
    admin: AdminJWTPayload = Depends(require_permission("carousel", "update")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> None:
    """
    Remove a single media entry from a feature carousel item.

    Also deletes the associated S3 object (if any) and evicts the Redis cache.
    """
    item = await CarouselDAO.get_by_id(session, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{item_id} raqamli carousel elementi topilmadi.",
        )

    deleted_entry = await CarouselItemMediaDAO.delete_entry(session, media_id, item_id)
    if deleted_entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{media_id} raqamli media elementi topilmadi.",
        )

    await session.commit()

    if deleted_entry.media_s3_key:
        await redis.delete(CacheKeys.carousel_presigned_url(deleted_entry.media_s3_key))
        await _delete_s3_media(deleted_entry.media_s3_key)
