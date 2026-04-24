"""
Extra Passports API Router.

Exposes CRUD operations for managing additional passports (family members, etc.).
Replicates the validation logic from src/bot/handlers/passport/add_passport.py.
"""
import json
import logging
import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db
from src.api.schemas.extra_passports import (
    ExtraPassportDeleteResponse,
    ExtraPassportListResponse,
    ExtraPassportResponse,
)
from src.bot.utils.validators import UZBEKISTAN_NATIVE_PASSPORT_SERIES
from src.infrastructure.database.dao.client_extra_passport import ClientExtraPassportDAO
from src.infrastructure.database.models.client import Client
from src.infrastructure.tools.datetime_utils import get_current_time
from src.infrastructure.tools.image_optimizer import optimize_image_to_webp
from src.infrastructure.tools.s3_manager import s3_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/passports", tags=["extra-passports"])

# S3 layout constants
S3_BASE_FOLDER = "extra-passports"
SUB_FOLDERS = ("passport_front", "passport_back")


# ==================== Validation Helpers ====================

def _validate_passport_series(value: str) -> str:
    """Validate and normalize passport series."""
    cleaned = value.strip().upper().replace(" ", "")
    pattern = re.compile(r"^([A-Za-z]{2})(\d{7})$", re.IGNORECASE)
    match = pattern.match(cleaned)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passport series must match format: 2 letters + 7 digits (e.g. AA1234567)",
        )
    series = match.group(1).upper()
    if series not in UZBEKISTAN_NATIVE_PASSPORT_SERIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown passport series: {series}",
        )
    return cleaned.upper()


def _validate_pinfl(value: str) -> str:
    """Validate and normalize PINFL."""
    cleaned = value.strip().replace(" ", "")
    if not re.match(r"^\d{14}$", cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PINFL must be exactly 14 digits",
        )
    if int(cleaned[0]) not in (3, 4, 5, 6):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PINFL first digit must be 3, 4, 5, or 6",
        )
    return cleaned


def _validate_date_of_birth(value: str) -> date:
    """Validate and parse date of birth string."""
    # Try ISO format first (YYYY-MM-DD), then common formats
    formats = ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"]
    birth_date: Optional[date] = None
    for fmt in formats:
        try:
            from datetime import datetime as dt
            birth_date = dt.strptime(value.strip(), fmt).date()
            break
        except ValueError:
            continue

    if birth_date is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Use YYYY-MM-DD, DD.MM.YYYY, DD/MM/YYYY, or DD-MM-YYYY",
        )

    today = get_current_time().date()
    if birth_date > today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Date of birth cannot be in the future",
        )

    # Calculate age
    age = today.year - birth_date.year
    if today.month < birth_date.month or (
        today.month == birth_date.month and today.day < birth_date.day
    ):
        age -= 1

    if age < 16:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must be at least 16 years old",
        )
    if age > 150:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date of birth",
        )

    return birth_date


async def _build_response(passport) -> ExtraPassportResponse:
    """
    Build an ExtraPassportResponse from a DB model instance.

    Deserialises the stored S3 keys from ``passport_images`` and generates
    temporary presigned URLs so the frontend can display them.
    """
    image_urls: list[str] = []
    if passport.passport_images:
        try:
            s3_keys: list[str] = json.loads(passport.passport_images)
        except (json.JSONDecodeError, TypeError):
            s3_keys = []

        for key in s3_keys:
            try:
                url = await s3_manager.generate_presigned_url(key)
                image_urls.append(url)
            except Exception as exc:
                logger.warning("Failed to generate presigned URL for %s: %s", key, exc)

    return ExtraPassportResponse(
        id=passport.id,
        passport_series=passport.passport_series,
        pinfl=passport.pinfl,
        date_of_birth=passport.date_of_birth,
        image_urls=image_urls,
        created_at=passport.created_at,
    )


# ==================== 1. List Passports ====================

@router.get(
    "/",
    response_model=ExtraPassportListResponse,
    summary="List extra passports",
    description="Returns a paginated list of the user's extra passports.",
)
async def list_passports(
    page: int = 1,
    size: int = 10,
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    """List all extra passports for the authenticated user."""
    if page < 1:
        page = 1
    if size < 1:
        size = 10
    if size > 100:
        size = 100

    offset = (page - 1) * size
    telegram_id = current_user.telegram_id

    passports = await ClientExtraPassportDAO.get_by_telegram_id(
        session, telegram_id, limit=size, offset=offset
    )
    total = await ClientExtraPassportDAO.count_by_telegram_id(session, telegram_id)

    items = [await _build_response(p) for p in passports]

    return ExtraPassportListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
    )


# ==================== 2. Add Passport ====================

@router.post(
    "/",
    response_model=ExtraPassportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an extra passport",
    description="Upload a new extra passport with images (multipart/form-data).",
)
async def add_passport(
    passport_series: str = Form(..., description="Passport series, e.g. AA1234567"),
    pinfl: str = Form(..., description="14-digit PINFL"),
    date_of_birth: str = Form(..., description="Date of birth (YYYY-MM-DD or DD.MM.YYYY)"),
    images: list[UploadFile] = File(..., description="Passport images (1-2 photos)"),
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    """Add a new extra passport for the authenticated user."""
    telegram_id = current_user.telegram_id

    # --- Validate fields ---
    validated_series = _validate_passport_series(passport_series)
    validated_pinfl = _validate_pinfl(pinfl)
    validated_dob = _validate_date_of_birth(date_of_birth)

    # --- Validate image count ---
    if len(images) > 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 2 images allowed (front and back)",
        )

    # --- Check for duplicate in extra passports ---
    conflicts_extra = await ClientExtraPassportDAO.check_duplicate_passport(
        session=session,
        passport_series=validated_series,
        pinfl=validated_pinfl,
        telegram_id=telegram_id,
    )

    # --- Check for duplicate in main Client table ---
    conflicts_main = await ClientExtraPassportDAO.check_duplicate_in_main_passport(
        session=session,
        passport_series=validated_series,
        pinfl=validated_pinfl,
        telegram_id=telegram_id,
    )

    # Merge and report conflicts
    has_conflicts = any(conflicts_extra.values()) or any(conflicts_main.values())
    if has_conflicts:
        detail_parts = []
        if conflicts_extra.get("passport_series") or conflicts_main.get("passport_series"):
            detail_parts.append("Passport series already exists")
        if conflicts_extra.get("pinfl") or conflicts_main.get("pinfl"):
            detail_parts.append("PINFL already exists")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="; ".join(detail_parts),
        )

    # --- Optimize & upload images to S3 ---
    client_code = current_user.client_code
    s3_keys: list[str] = []

    for idx, image in enumerate(images):
        sub_folder = SUB_FOLDERS[idx] if idx < len(SUB_FOLDERS) else SUB_FOLDERS[-1]
        raw_content = await image.read()
        if not raw_content:
            continue

        # Convert to optimized WEBP (CPU work runs in a thread)
        try:
            optimized_content = await optimize_image_to_webp(raw_content)
        except ValueError:
            # Clean up anything already uploaded in this batch
            for key in s3_keys:
                await s3_manager.delete_file(key)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid image file (image {idx + 1})",
            )

        file_name = f"image_{idx}.webp"
        content_type = "image/webp"

        try:
            s3_key = await s3_manager.upload_file(
                file_content=optimized_content,
                file_name=file_name,
                telegram_id=telegram_id,
                client_code=current_user.extra_code or client_code,
                base_folder=S3_BASE_FOLDER,
                sub_folder=sub_folder,
                content_type=content_type,
            )
            s3_keys.append(s3_key)
        except Exception as exc:
            logger.error("S3 upload failed for image %d: %s", idx, exc, exc_info=True)
            # Clean up any keys already uploaded in this request
            for key in s3_keys:
                await s3_manager.delete_file(key)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload passport image",
            )

    if not s3_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one valid image is required",
        )

    # --- Create DB record ---
    passport_data = {
        "telegram_id": telegram_id,
        "client_code": client_code,
        "passport_series": validated_series,
        "pinfl": validated_pinfl,
        "date_of_birth": validated_dob,
        "passport_images": json.dumps(s3_keys),
    }

    try:
        new_passport = await ClientExtraPassportDAO.create(session, passport_data)
        await session.commit()
    except Exception as e:
        logger.error(f"Error saving extra passport: {e}", exc_info=True)
        # Clean up uploaded S3 objects on DB failure
        for key in s3_keys:
            await s3_manager.delete_file(key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save passport",
        )

    return await _build_response(new_passport)


# ==================== 3. Get Single Passport ====================

@router.get(
    "/{passport_id}",
    response_model=ExtraPassportResponse,
    summary="Get a single extra passport",
    description="Retrieve details of a specific extra passport by ID.",
)
async def get_passport(
    passport_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    """Get a single extra passport by ID (ownership check)."""
    passport = await ClientExtraPassportDAO.get_by_id(session, passport_id)

    if not passport or passport.telegram_id != current_user.telegram_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport not found",
        )

    return await _build_response(passport)


# ==================== 4. Delete Passport ====================

@router.delete(
    "/{passport_id}",
    response_model=ExtraPassportDeleteResponse,
    summary="Delete an extra passport",
    description="Delete a specific extra passport by ID.",
)
async def delete_passport(
    passport_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    """Delete an extra passport by ID (ownership check). Removes S3 objects first."""
    passport = await ClientExtraPassportDAO.get_by_id(session, passport_id)

    if not passport or passport.telegram_id != current_user.telegram_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport not found",
        )

    # --- Delete images from S3 ---
    if passport.passport_images:
        try:
            s3_keys = json.loads(passport.passport_images)
        except (json.JSONDecodeError, TypeError):
            s3_keys = []

        for key in s3_keys:
            await s3_manager.delete_file(key)

    # --- Delete DB record ---
    try:
        await ClientExtraPassportDAO.delete(session, passport)
        await session.commit()
    except Exception as e:
        logger.error(f"Error deleting extra passport: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete passport",
        )

    return ExtraPassportDeleteResponse()
