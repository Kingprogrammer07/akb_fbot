import logging
import json
import math
import random
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal

from src.bot.bot_instance import bot
from src.infrastructure.database.models.client import Client
from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.infrastructure.services.flight_cargo import FlightCargoService
from src.infrastructure.services.static_data import StaticDataService
from src.infrastructure.schemas.flights_api import (
    FlightListResponse,
    FlightResponse,
    PhotoUploadResponse,
    CargoPhotoResponse,
    FlightPhotosResponse,
    ClearPhotosResponse,
    FlightStatsResponse,
    CargoDeleteResponse,
    CargoUpdateResponse,
    CargoImageMetadataResponse,
    CargoPhotoMetadata,
    SinglePhotoMetadataResponse,
)
from src.api.services.telegram_file_service import TelegramFileService
from src.api.dependencies import get_redis, get_admin_from_jwt, require_permission, AdminJWTPayload
from redis.asyncio import Redis
from src.config import config
from src.infrastructure.tools.s3_manager import s3_manager
from src.infrastructure.tools.image_optimizer import optimize_image_to_webp
import uuid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/flights", tags=["flights"])

# Initialize Google Sheets checker
sheets_checker = GoogleSheetsChecker(
    spreadsheet_id=config.google_sheets.SHEETS_ID,
    api_key=config.google_sheets.API_KEY,
    last_n_sheets=5  # Last 5 sheets
)

# Initialize services
flight_cargo_service = FlightCargoService()
static_data_service = StaticDataService()


def parse_photo_file_ids(photo_file_ids_json: str) -> list[str]:
    """Helper to parse JSON photo_file_ids from database."""
    try:
        return json.loads(photo_file_ids_json)
    except (json.JSONDecodeError, TypeError):
        # Fallback for old single file_id format
        return [photo_file_ids_json] if photo_file_ids_json else []


async def get_session(request: Request):
    """Dependency to get database session from global app state."""
    db_client = request.app.state.db_client
    
    if not db_client:
        raise RuntimeError("Database client not initialized")
        
    async with db_client.session_factory() as session:
        yield session


async def get_all_admin_ids(session: AsyncSession) -> list[int]:
    """
    Fetch all admin IDs from both config and database.

    Combines config.telegram.ADMIN_ACCESS_IDs with Client records
    where role is admin/super-admin, returning a deduplicated list.
    """
    # Fetch DB admins
    result = await session.execute(
        select(Client.telegram_id).where(
            Client.role.in_(['admin', 'super-admin']),
            Client.telegram_id.is_not(None)
        )
    )
    db_admins = set(result.scalars().all())

    # Combine with config admins
    config_admins = config.telegram.ADMIN_ACCESS_IDs or set()
    all_admins = list(db_admins.union(config_admins))

    return all_admins


# ==================== Flight Endpoints (Google Sheets) ====================

@router.get("", response_model=FlightListResponse)
async def get_flights(
    last_n: int = 5,
    admin: AdminJWTPayload = Depends(require_permission("flights", "read")),
):
    """
    Get list of flights from Google Sheets worksheets.

    Two prefix groups are exposed side-by-side:
      * ``M``  — regular flights (e.g. M123-2025)
      * ``A-`` — ostatka (leftover) flights (e.g. A-2025-04)

    Args:
        last_n: Number of most recent flights to return **per group**
                (default: 5 → up to 10 total when both groups are populated).

    Returns:
        Combined flight list: last ``last_n`` M-flights followed by last
        ``last_n`` A--flights.  ``total`` reflects the combined length.
    """
    try:
        flight_names = await sheets_checker.get_flight_sheet_names(last_n=last_n)

        return FlightListResponse(
            flights=[FlightResponse(name=name) for name in flight_names],
            total=len(flight_names)
        )
    except Exception as e:
        logger.error(f"Error fetching flights: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reyslar ro'yxatini olishda xatolik yuz berdi: {str(e)}"
        )


# ==================== Export Endpoint ====================

@router.get("/{flight_name}/export", response_class=StreamingResponse)
async def export_flight_data(
    flight_name: str,
    request: Request,
    admin: AdminJWTPayload = Depends(require_permission("flights", "read")),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis)
):
    """
    Export flight cargo data as an Excel (.xlsx) file.

    Rate limited to 1 request per 60 seconds per IP per flight.
    Streams the response to avoid loading large files into memory.

    Args:
        flight_name: Flight/reys name
        request: FastAPI request (for client IP)
        session: Database session
        redis: Redis connection (for rate limiting)

    Returns:
        StreamingResponse with Excel file
    """
    # --- Rate Limiting ---
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"rate_limit:export:{client_ip}:{flight_name.upper()}"

    if await redis.exists(rate_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Iltimos, qayta yuklab olishdan oldin 1 daqiqa kuting"
        )

    await redis.set(rate_key, "1", ex=60)

    # --- Generate Excel ---
    try:
        buffer = await flight_cargo_service.generate_flight_export(session, flight_name)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Export failed for flight {flight_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Eksport faylini yaratishda xatolik yuz berdi: {str(e)}"
        )

    filename = f"{flight_name.upper()}_cargo_export.xlsx"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


# ==================== Photo Upload Endpoints (Database Storage) ====================

@router.post("/photos", response_model=PhotoUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_photos(
    flight_name: str = Form(...),
    client_id: str = Form(...),
    weight_kg: float | None = Form(None),
    price_per_kg: float | None = Form(None),
    comment: str | None = Form(None),
    photos: list[UploadFile] = File(...),
    admin: AdminJWTPayload = Depends(require_permission("flights", "create")),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis)
):
    """
    Upload cargo photos (single or multiple) with multipart/form-data.

    Supports album mode - can upload 1 or multiple photos at once.
    Photos are uploaded to Telegram and file_ids are stored in database as JSON array.

    Args:
        flight_name: Flight/Reys name
        client_id: Client code (e.g., SS123)
        weight_kg: Weight in kilograms (optional)
        price_per_kg: Price per kg (optional, falls back to static_data default)
        comment: Optional comment
        photos: Photo file uploads (1 or more)
        session: Database session

    Returns:
        Upload confirmation with photo details
    """
    # Get price_per_kg from static_data if not provided
    if price_per_kg is None:
        default_price = await static_data_service.get_price_per_kg(session)
        price_per_kg = default_price
        logger.info(f"Using default price_per_kg from static_data: {price_per_kg}")
    # Upload photos to Telegram and collect file_ids - use shared bot instance
    photo_file_ids = []

    try:
        # Load balancing: get all admin IDs and distribute uploads
        all_admin_ids = await get_all_admin_ids(session)
        telegram_service = TelegramFileService(bot, redis)

        # Upload each photo
        for idx, photo in enumerate(photos):
            raw_content = await photo.read()

            # --- Primary: S3 + WebP Optimization ---
            try:
                upload_content = await optimize_image_to_webp(raw_content)
                ext = "webp"
                unique_filename = f"cargo_{uuid.uuid4().hex[:8]}_{idx+1}.{ext}"

                s3_key = await s3_manager.upload_file(
                    file_content=upload_content,
                    file_name=unique_filename,
                    telegram_id=0,
                    client_code=client_id,
                    base_folder="cargo-photos",
                    sub_folder=flight_name,
                    content_type="image/webp"
                )
                photo_file_ids.append(s3_key)
                logger.info(f"Uploaded to S3: {s3_key}")
                continue  # Success, skip fallback
            except Exception as e:
                logger.error(f"S3 upload failed, falling back to Telegram: {e}")

            # --- Fallback: Telegram ---
            if not all_admin_ids:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="S3 xatoligi yuz berdi va Telegram zaxira uchun adminlar topilmadi"
                )

            target_admin_id = random.choice(all_admin_ids)
            file_id = await telegram_service.upload_file_to_telegram(
                file_content=raw_content,
                filename=photo.filename or f"cargo_photo_{idx+1}.jpg",
                target_chat_id=target_admin_id
            )
            photo_file_ids.append(file_id)
            logger.info(f"Fallback uploaded to Telegram: {file_id}")

        logger.info(f"Successfully uploaded {len(photo_file_ids)} photos for flight {flight_name}, client {client_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload photos: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Rasmlarni yuklashda xatolik yuz berdi: {str(e)}"
        )

    # Save to database
    result = await flight_cargo_service.add_cargo(
        session,
        flight_name=flight_name,
        client_id=client_id,
        photo_file_ids=photo_file_ids,
        weight_kg=Decimal(str(weight_kg)) if weight_kg else None,
        price_per_kg=Decimal(str(price_per_kg)) if price_per_kg else None,
        comment=comment
    )

    if not result['success']:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result['message']
        )

    cargo = result['cargo']
    await session.commit()

    # Emit analytics event for cargo upload
    from src.infrastructure.services.analytics_service import AnalyticsService
    # Note: user_id is None here as we only have client_id (client code), not telegram_id
    await AnalyticsService.emit_event(
        session=session,
        event_type='cargo_upload',
        user_id=None,  # We don't have telegram_id in this context
        payload={
            'cargo_id': cargo.id,
            'flight_name': flight_name,
            'client_id': client_id,
            'photo_count': len(photo_file_ids),
            'weight_kg': float(weight_kg) if weight_kg else None,
            'price_per_kg': float(price_per_kg) if price_per_kg else None,
            'has_comment': bool(comment)
        }
    )
    await session.commit()  # Commit analytics event (cargo was already committed in service)
    return PhotoUploadResponse(
        success=True,
        message=f"{len(photo_file_ids)} photo(s) uploaded for client {client_id} in flight {flight_name}",
        photo=CargoPhotoResponse(
            id=str(cargo.id),
            flight_name=cargo.flight_name,
            client_id=cargo.client_id,
            photo_file_ids=parse_photo_file_ids(cargo.photo_file_ids),
            weight_kg=float(cargo.weight_kg) if cargo.weight_kg else None,
            price_per_kg=float(cargo.price_per_kg) if cargo.price_per_kg else None,
            comment=cargo.comment,
            is_sent=cargo.is_sent,
            created_at=cargo.created_at,
            updated_at=cargo.updated_at
        )
    )


@router.get("/{flight_name}/photos", response_model=FlightPhotosResponse)
async def get_flight_photos(
    flight_name: str,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(50, ge=1, le=100, description="Items per page (max 100)"),
    search: str | None = Query(None, max_length=50, description="Filter by client ID (partial match, case-insensitive)"),
    admin: AdminJWTPayload = Depends(require_permission("flights", "read")),
    session: AsyncSession = Depends(get_session),
):
    """
    Get paginated cargo photos for a flight.

    Args:
        flight_name: Flight/reys name.
        page:        1-based page number.
        size:        Items per page (1–100).
        search:      Optional partial client-ID filter applied server-side so
                     that ``total`` and ``total_pages`` reflect the filtered set.

    Returns:
        Paginated list of cargo photos with accurate totals.
    """
    offset = (page - 1) * size
    result = await flight_cargo_service.get_flight_cargos(
        session, flight_name, limit=size, offset=offset, search=search
    )
    total_pages = max(1, math.ceil(result['total'] / size))

    return FlightPhotosResponse(
        flight_name=flight_name,
        photos=[
            CargoPhotoResponse(
                id=str(c.id),
                flight_name=c.flight_name,
                client_id=c.client_id,
                photo_file_ids=parse_photo_file_ids(c.photo_file_ids),
                weight_kg=float(c.weight_kg) if c.weight_kg else None,
                price_per_kg=float(c.price_per_kg) if c.price_per_kg else None,
                comment=c.comment,
                is_sent=c.is_sent,
                created_at=c.created_at,
                updated_at=c.updated_at
            )
            for c in result['cargos']
        ],
        total=result['total'],
        unique_clients=result['unique_clients'],
        sent_count=result['sent_count'],
        unsent_count=result['unsent_count'],
        page=page,
        size=size,
        total_pages=total_pages,
    )


@router.get("/{flight_name}/stats", response_model=FlightStatsResponse)
async def get_flight_stats(
    flight_name: str,
    admin: AdminJWTPayload = Depends(require_permission("flights", "read")),
    session: AsyncSession = Depends(get_session),
):
    """
    Get photo statistics for a flight.

    Args:
        flight_name: Flight/reys name

    Returns:
        Statistics (total photos, unique clients, sent/unsent counts)
    """
    result = await flight_cargo_service.get_flight_cargos(session, flight_name, limit=1)

    return FlightStatsResponse(
        flight_name=flight_name,
        total_photos=result['total'],
        unique_clients=result['unique_clients'],
        sent_count=result['sent_count'],
        unsent_count=result['unsent_count'],
    )


# ==================== NEW: File ID Based Endpoints (v2.0) ====================

@router.get(
    "/photos/{cargo_id}/metadata",
    response_model=CargoImageMetadataResponse,
    summary="Get cargo photo metadata with file_ids",
    description="Returns file_id metadata for all photos. Use this instead of binary streaming."
)
async def get_cargo_photo_metadata(
    cargo_id: int,
    resolve_urls: bool = Query(
        True,
        description="Whether to resolve temporary Telegram URLs (valid ~1 hour)"
    ),
    admin: AdminJWTPayload = Depends(require_permission("flights", "read")),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis)
):
    """
    Get metadata for all photos of a cargo item.

    NEW PREFERRED ENDPOINT - Returns file_ids instead of binary data.

    Features:
    - Returns all photo file_ids
    - Optionally resolves temporary Telegram URLs
    - Auto-regenerates expired file_ids
    - Memory efficient (no binary streaming)
    - Cacheable responses

    Args:
        cargo_id: Cargo photo ID
        resolve_urls: If true, include temporary Telegram URLs

    Returns:
        CargoImageMetadataResponse with photo metadata
    """
    cargo = await flight_cargo_service.get_cargo_by_id(session, cargo_id)

    if not cargo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{cargo_id} raqamli yuk topilmadi"
        )

    file_ids = parse_photo_file_ids(cargo.photo_file_ids)

    if not file_ids:
        return CargoImageMetadataResponse(
            cargo_id=cargo_id,
            flight_name=cargo.flight_name,
            client_id=cargo.client_id,
            photo_count=0,
            photos=[]
        )

    photos: list[CargoPhotoMetadata] = []
    telegram_service = TelegramFileService(bot, redis)

    for idx, stored_id in enumerate(file_ids):
        is_s3 = "/" in stored_id or "." in stored_id  # Simple heuristic for S3 keys

        if is_s3:
            if resolve_urls:
                url = await s3_manager.generate_presigned_url(stored_id)
                photos.append(CargoPhotoMetadata(
                    index=idx, file_id=stored_id, telegram_url=url,
                    is_regenerated=False, error=None if url else "S3 URL generation failed"
                ))
            else:
                photos.append(CargoPhotoMetadata(
                    index=idx, file_id=stored_id, telegram_url=None, is_regenerated=False, error=None
                ))
        else:
            # Telegram Resolution
            if resolve_urls:
                result = await telegram_service.resolve_cargo_file_id(
                    cargo_id=cargo_id, file_id=stored_id, photo_index=idx,
                    session=session, auto_regenerate=True
                )
                photos.append(CargoPhotoMetadata(
                    index=idx, file_id=result.file_id, telegram_url=result.telegram_url,
                    is_regenerated=result.is_regenerated, error=result.error
                ))
            else:
                photos.append(CargoPhotoMetadata(
                    index=idx, file_id=stored_id, telegram_url=None, is_regenerated=False, error=None
                ))

    return CargoImageMetadataResponse(
        cargo_id=cargo_id,
        flight_name=cargo.flight_name,
        client_id=cargo.client_id,
        photo_count=len(photos),
        photos=photos
    )


@router.get(
    "/photos/{cargo_id}/resolve",
    response_model=SinglePhotoMetadataResponse,
    summary="Resolve single photo file_id",
    description="Resolve a specific photo with auto-regeneration if expired."
)
async def resolve_cargo_photo(
    cargo_id: int,
    photo_index: int = Query(
        0,
        ge=0,
        description="Photo index (0-based)"
    ),
    admin: AdminJWTPayload = Depends(require_permission("flights", "read")),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis)
):
    """
    Resolve a single cargo photo file_id.

    Use this when frontend detects an expired URL and needs a fresh one.
    Automatically regenerates the file_id if it has expired.

    Args:
        cargo_id: Cargo photo ID
        photo_index: Index of photo to resolve

    Returns:
        SinglePhotoMetadataResponse with resolved file_id and URL
    """
    cargo = await flight_cargo_service.get_cargo_by_id(session, cargo_id)

    if not cargo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{cargo_id} raqamli yuk topilmadi"
        )

    file_ids = parse_photo_file_ids(cargo.photo_file_ids)

    if not file_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{cargo_id} raqamli yuk uchun rasmlar topilmadi"
        )

    if photo_index >= len(file_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Noto'g'ri photo_index: {photo_index}. "
                   f"Yukda {len(file_ids)} ta rasm mavjud (to'g'ri: 0–{len(file_ids)-1})"
        )

    stored_id = file_ids[photo_index]
    is_s3 = "/" in stored_id or "." in stored_id

    if is_s3:
        url = await s3_manager.generate_presigned_url(stored_id)
        if not url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="S3 vaqtinchalik URL yaratishda xatolik yuz berdi"
            )
        return SinglePhotoMetadataResponse(
            cargo_id=cargo_id, photo_index=photo_index, file_id=stored_id,
            telegram_url=url, is_regenerated=False
        )
    else:
        # Telegram Resolution
        telegram_service = TelegramFileService(bot, redis)
        result = await telegram_service.resolve_cargo_file_id(
            cargo_id=cargo_id, file_id=stored_id, photo_index=photo_index,
            session=session, auto_regenerate=True
        )
        if result.error and not result.telegram_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Rasmni hal qilishda xatolik yuz berdi: {result.error}"
            )
        return SinglePhotoMetadataResponse(
            cargo_id=cargo_id, photo_index=photo_index, file_id=result.file_id,
            telegram_url=result.telegram_url, is_regenerated=result.is_regenerated
        )


@router.put("/photos/{cargo_id}", response_model=CargoUpdateResponse)
async def update_cargo_photo(
    cargo_id: int,
    flight_name: str | None = Form(None),
    client_id: str | None = Form(None),
    weight_kg: float | None = Form(None),
    price_per_kg: float | None = Form(None),
    comment: str | None = Form(None),
    photos: list[UploadFile] | None = File(None),
    admin: AdminJWTPayload = Depends(require_permission("flights", "update")),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis)
):
    """
    Update cargo photo details.

    Can update flight name, client code, weight, price_per_kg, comment, and/or replace photos.

    Args:
        cargo_id: Cargo photo ID
        flight_name: New flight name (optional)
        client_id: New client code (optional)
        weight_kg: New weight in kilograms (optional)
        price_per_kg: New price per kg (optional)
        comment: New comment (optional)
        photos: New photo files (optional, replaces ALL existing photos)
        session: Database session

    Returns:
        Update confirmation with updated photo details
    """
    # Get existing cargo
    cargo = await flight_cargo_service.get_cargo_by_id(session, cargo_id)

    if not cargo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{cargo_id} raqamli yuk rasmi topilmadi"
        )

    new_file_ids = parse_photo_file_ids(cargo.photo_file_ids)

    # If new photos are provided, upload with S3-Primary + Telegram-Fallback
    if photos:
        new_file_ids = []

        try:
            # Load balancing: get all admin IDs and distribute uploads
            all_admin_ids = await get_all_admin_ids(session)
            telegram_service = TelegramFileService(bot, redis)

            # Upload each new photo
            for idx, photo in enumerate(photos):
                raw_content = await photo.read()

                # --- Primary: S3 + WebP Optimization ---
                try:
                    upload_content = await optimize_image_to_webp(raw_content)
                    ext = "webp"
                    unique_filename = f"cargo_{uuid.uuid4().hex[:8]}_{idx+1}.{ext}"

                    s3_key = await s3_manager.upload_file(
                        file_content=upload_content,
                        file_name=unique_filename,
                        telegram_id=0,
                        client_code=client_id or cargo.client_id,
                        base_folder="cargo-photos",
                        sub_folder=flight_name or cargo.flight_name,
                        content_type="image/webp"
                    )
                    new_file_ids.append(s3_key)
                    logger.info(f"Uploaded updated photo to S3: {s3_key}")
                    continue  # Success, skip fallback
                except Exception as e:
                    logger.error(f"S3 upload failed, falling back to Telegram: {e}")

                # --- Fallback: Telegram ---
                if not all_admin_ids:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="S3 xatoligi yuz berdi va Telegram zaxira uchun adminlar topilmadi"
                    )

                target_admin_id = random.choice(all_admin_ids)
                file_id = await telegram_service.upload_file_to_telegram(
                    file_content=raw_content,
                    filename=photo.filename or f"updated_cargo_{idx+1}.jpg",
                    target_chat_id=target_admin_id
                )
                new_file_ids.append(file_id)
                logger.info(f"Fallback uploaded updated photo to Telegram: {file_id}")

            logger.info(f"Successfully uploaded {len(new_file_ids)} new photos for cargo {cargo_id}")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to upload new photos: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Yangi rasmlarni yuklashda xatolik yuz berdi: {str(e)}"
            )

    # Update in database
    try:
        cargo.photo_file_ids = json.dumps(new_file_ids)
        if flight_name is not None:
            cargo.flight_name = flight_name.upper()
        if client_id is not None:
            cargo.client_id = client_id.upper()
        if weight_kg is not None:
            cargo.weight_kg = Decimal(str(weight_kg))
        if price_per_kg is not None:
            cargo.price_per_kg = Decimal(str(price_per_kg))
        if comment is not None:
            cargo.comment = comment

        await session.commit()
        await session.refresh(cargo)

        return CargoUpdateResponse(
            success=True,
            message=f"Cargo {cargo_id} updated successfully",
            photo=CargoPhotoResponse(
                id=str(cargo.id),
                flight_name=cargo.flight_name,
                client_id=cargo.client_id,
                photo_file_ids=parse_photo_file_ids(cargo.photo_file_ids),
                weight_kg=float(cargo.weight_kg) if cargo.weight_kg else None,
                price_per_kg=float(cargo.price_per_kg) if cargo.price_per_kg else None,
                comment=cargo.comment,
                is_sent=cargo.is_sent,
                created_at=cargo.created_at,
                updated_at=cargo.updated_at
            )
        )
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to update cargo: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Yukni yangilashda xatolik yuz berdi: {str(e)}"
        )


@router.delete("/photos/{cargo_id}", response_model=CargoDeleteResponse)
async def delete_cargo(
    cargo_id: int,
    admin: AdminJWTPayload = Depends(require_permission("flights", "delete")),
    session: AsyncSession = Depends(get_session),
):
    """
    Delete a single cargo photo by ID and remove associated S3 objects.

    Args:
        cargo_id: Cargo ID

    Returns:
        Deletion confirmation
    """
    # Fetch the cargo BEFORE deletion so we can extract S3 keys afterward.
    # The service commits inside its own method, leaving no ORM object to inspect.
    cargo_to_delete = await flight_cargo_service.get_cargo_by_id(session, cargo_id)
    s3_keys_to_clean: list[str] = []
    if cargo_to_delete:
        s3_keys_to_clean = [
            fid for fid in parse_photo_file_ids(cargo_to_delete.photo_file_ids)
            if "/" in fid or "." in fid  # S3 key heuristic (not a Telegram file_id)
        ]

    result = await flight_cargo_service.delete_cargo(session, cargo_id)

    if not result['success']:
        if result['error'] == 'cargo_not_found':
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result['message']
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result['message']
        )

    # Fire-and-forget S3 cleanup after the DB commit.  Failures are logged but
    # never surfaced as HTTP errors — the record is already gone from the DB.
    for s3_key in s3_keys_to_clean:
        deleted = await s3_manager.delete_file(s3_key)
        if not deleted:
            logger.warning("S3 cleanup failed for key %s (cargo %d)", s3_key, cargo_id)

    return CargoDeleteResponse(
        success=True,
        message=f"Cargo photo {cargo_id} deleted successfully",
        deleted_cargo_id=str(cargo_id)
    )


@router.delete("/{flight_name}/photos", response_model=ClearPhotosResponse)
async def clear_flight_photos(
    flight_name: str,
    admin: AdminJWTPayload = Depends(require_permission("flights", "delete")),
    session: AsyncSession = Depends(get_session),
):
    """
    Clear all photos for a flight and remove associated S3 objects.

    Args:
        flight_name: Flight/reys name

    Returns:
        Confirmation message with deleted count
    """
    # Collect all S3 keys BEFORE the bulk DELETE query runs, because the DAO
    # uses a single DELETE statement that returns no ORM objects.
    prefetch = await flight_cargo_service.get_flight_cargos(session, flight_name)
    s3_keys_to_clean: list[str] = [
        fid
        for cargo in prefetch['cargos']
        for fid in parse_photo_file_ids(cargo.photo_file_ids)
        if "/" in fid or "." in fid  # S3 key heuristic (not a Telegram file_id)
    ]

    result = await flight_cargo_service.delete_flight_cargos(session, flight_name)

    if not result['success']:
        if result['error'] == 'no_cargos_found':
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result['message']
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result['message']
        )

    # Fire-and-forget S3 cleanup after the DB commit.
    for s3_key in s3_keys_to_clean:
        deleted = await s3_manager.delete_file(s3_key)
        if not deleted:
            logger.warning("S3 cleanup failed for key %s (flight %s)", s3_key, flight_name)

    return ClearPhotosResponse(
        success=True,
        message=f"All photos cleared for flight {flight_name}",
        flight_name=flight_name,
        deleted_count=result['deleted_count']
    )