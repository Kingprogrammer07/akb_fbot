import json
import random
from typing import Optional
from datetime import date
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status, File, UploadFile, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession

from redis.asyncio import Redis
from src.api.dependencies import get_translator, get_redis, get_admin_user
from src.api.utils.constants import resolve_region_code
from src.bot.bot_instance import bot
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.schemas.auth import ErrorResponse
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.schemas.client_api import (
    ClientResponse,
    ClientDeleteResponse,
    CodePreviewResponse
)
from src.infrastructure.schemas.flights_api import (
    PassportImagesMetadataResponse,
    PassportImageMetadata,
)
from src.api.utils.telegram import upload_passport_images_to_telegram
from src.api.services.telegram_file_service import TelegramFileService
from src.infrastructure.tools.s3_manager import s3_manager
from src.infrastructure.tools.image_optimizer import optimize_image_to_webp
from src.config import config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clients", tags=["clients"])


CONFLICT_KEYS = {
    "pinfl": "conflict-pinfl",
    "phone": "conflict-phone",
    "passport_series": "conflict-passport-series",
    "telegram_id": "conflict-telegram-id"
}

async def get_session(request: Request):
    """Dependency to get database session."""
    db_client = request.app.state.db_client

    if not db_client:
        raise RuntimeError("Database client not initialized")

    async with db_client.session_factory() as session:
        yield session


def parse_passport_file_ids(passport_images_json: Optional[str]) -> list[str]:
    """Helper to parse JSON passport_images from database."""
    if not passport_images_json:
        return []
    try:
        result = json.loads(passport_images_json)
        return result if isinstance(result, list) else [result]
    except (json.JSONDecodeError, TypeError):
        return [passport_images_json] if passport_images_json else []


# ---------------------------------------------------------------------------
#  Upload helper: S3-first → Telegram user fallback → Telegram admin fallback
# ---------------------------------------------------------------------------

async def _upload_passport_images(
    passport_images: list[UploadFile],
    telegram_id: Optional[int],
    client_code: Optional[str],
    session: AsyncSession,
) -> str:
    """
    Upload passport images with layered fallback strategy.

    Attempt order:
      1. S3 (primary)  — optimized WebP upload
      2. Telegram user chat (fallback, only if telegram_id available)
      3. Telegram admin chat (last resort)

    Returns:
        JSON-encoded list of S3 keys or Telegram file_ids.

    Raises:
        HTTPException 500 if all strategies fail.
    """
    s3_base_folders = ["passport-front-images", "passport-back-images"]

    # ── Strategy 1: S3 ───────────────────────────────────────────────────────
    try:
        s3_keys: list[str] = []
        for idx, img in enumerate(passport_images[:2]):
            await img.seek(0)
            raw_content = await img.read()
            optimized = await optimize_image_to_webp(raw_content)
            s3_key = await s3_manager.upload_file(
                file_content=optimized,
                file_name=img.filename or f"passport_{idx}.webp",
                telegram_id=telegram_id,
                client_code=client_code,
                base_folder=s3_base_folders[idx],
                sub_folder="",
                content_type="image/webp",
            )
            s3_keys.append(s3_key)

        logger.info(
            f"✅ S3 upload success: count={len(s3_keys)}, "
            f"telegram_id={telegram_id}, client_code={client_code}"
        )
        return json.dumps(s3_keys)

    except Exception as s3_err:
        logger.warning(
            f"⚠️ S3 upload failed (telegram_id={telegram_id}): {s3_err}. "
            f"Falling back to Telegram."
        )
        # Reset file positions for fallback
        for img in passport_images:
            try:
                await img.seek(0)
            except Exception:
                pass

    # ── Strategy 2: Telegram user chat ──────────────────────────────────────
    if telegram_id is not None:
        try:
            file_ids = await upload_passport_images_to_telegram(
                chat_id=telegram_id,
                passport_images=passport_images,
                bot=bot,
            )
            logger.info(
                f"✅ Telegram user upload success: count={len(file_ids)}, "
                f"telegram_id={telegram_id}"
            )
            return json.dumps(file_ids)
        except Exception as tg_user_err:
            logger.warning(
                f"⚠️ Telegram user upload failed (chat_id={telegram_id}): {tg_user_err}. "
                f"Falling back to admin chat."
            )
            for img in passport_images:
                try:
                    await img.seek(0)
                except Exception:
                    pass

    # ── Strategy 3: Telegram admin chat ─────────────────────────────────────
    from sqlalchemy import select
    from src.infrastructure.database.models.client import Client

    admin_pool = set(config.telegram.ADMIN_ACCESS_IDs or set())
    try:
        result = await session.execute(
            select(Client.telegram_id).where(
                Client.role.in_(["admin", "super-admin"]),
                Client.telegram_id.is_not(None),
            )
        )
        admin_pool.update(result.scalars().all())
    except Exception as db_err:
        logger.error(f"Error fetching DB admins: {db_err}")

    target_chat_id = (
        random.choice(list(admin_pool)) if admin_pool
        else config.telegram.TASDIQLASH_GROUP_ID
    )

    try:
        file_ids = await upload_passport_images_to_telegram(
            chat_id=target_chat_id,
            passport_images=passport_images,
            bot=bot,
        )
        logger.info(
            f"✅ Telegram admin fallback upload success: count={len(file_ids)}, "
            f"chat_id={target_chat_id}"
        )
        return json.dumps(file_ids)
    except Exception as tg_admin_err:
        logger.critical(
            f"❌ CRITICAL: All upload strategies failed! "
            f"telegram_id={telegram_id}, client_code={client_code}: {tg_admin_err}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="api-error-failed-upload-passport-images",
        )


# ---------------------------------------------------------------------------
#  Endpoints
# ---------------------------------------------------------------------------

@router.get("/preview-code", response_model=CodePreviewResponse)
async def preview_client_code_endpoint(
    region: str = Query(""),
    district: str = Query(""),
    session: AsyncSession = Depends(get_session),
    _: callable = Depends(get_translator),
    _admin=Depends(get_admin_user),
):
    """
    Frontend'da jonli (live) tarzda keyingi bo'sh kod qanaqa bo'lishini ko'rsatish uchun API.
    Bu API bazani qulflamaydi (No LOCK).
    """
    from src.api.utils.code_generator import (
        PARTNER_PREFIX,
        build_code_pattern,
        preview_client_code,
    )

    region_code = resolve_region_code(region)
    is_tashkent = region_code == "01"

    preview_code = await preview_client_code(session, region, district)

    # Reconstruct the prefix shown to the frontend (everything before "/seq").
    prefix_only = preview_code.rsplit("/", 1)[0] if "/" in preview_code else preview_code
    return CodePreviewResponse(
        preview_code=preview_code,
        prefix=prefix_only,
        is_tashkent=is_tashkent,
    )


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: int,
    session: AsyncSession = Depends(get_session),
    _: callable = Depends(get_translator),
    _admin=Depends(get_admin_user),
):
    """
    Get client by ID.

    Returns all client information including:
    - Personal details
    - Passport information
    - Client code
    - Referral information
    """
    client = await ClientDAO.get_by_id(session, client_id)

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("admin-settings-add-admin-not-found-withid", client_id=client_id)
        )
    if client.extra_code:
        client.client_code = client.extra_code

    current_balance = 0.0
    if client.client_code:
        current_balance = await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
            session, client.client_code
        )

    response = ClientResponse.model_validate(client)
    response.current_balance = current_balance
    return response


# ==================== NEW: File ID Based Endpoints (v2.0) ====================

@router.get(
    "/{client_id}/passport-images/metadata",
    response_model=PassportImagesMetadataResponse,
    summary="Get passport image metadata with file_ids",
    description="Returns file_id metadata for all passport images. "
                "Use this instead of binary streaming."
)
async def get_passport_images_metadata(
    client_id: int,
    resolve_urls: bool = Query(
        True,
        description="Whether to resolve temporary Telegram URLs"
    ),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    _: callable = Depends(get_translator),
    _admin=Depends(get_admin_user),
):
    """
    Get metadata for all passport images of a client.

    Features:
    - Returns all passport image file_ids
    - Optionally resolves temporary Telegram URLs
    - Auto-regenerates expired file_ids
    - Memory efficient (no binary streaming)

    Args:
        client_id: Client ID
        resolve_urls: If true, include temporary Telegram URLs

    Returns:
        PassportImagesMetadataResponse with image metadata
    """
    client = await ClientDAO.get_by_id(session, client_id)

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("admin-settings-add-admin-not-found-withid", client_id=client_id)
        )

    file_ids = parse_passport_file_ids(client.passport_images)

    if not file_ids:
        return PassportImagesMetadataResponse(
            client_id=client_id,
            image_count=0,
            images=[]
        )

    images: list[PassportImageMetadata] = []
    telegram_service = TelegramFileService(bot, redis)

    for idx, file_id in enumerate(file_ids):
        if resolve_urls:
            # S3 key detection: contains '/' → generate presigned URL
            if "/" in file_id:
                try:
                    presigned_url = await s3_manager.generate_presigned_url(file_id, expires_in=3600)
                    images.append(PassportImageMetadata(
                        index=idx,
                        file_id=file_id,
                        telegram_url=presigned_url,
                        is_regenerated=False,
                        error=None
                    ))
                except Exception as exc:
                    logger.error(f"Failed to generate presigned URL for {file_id}: {exc}")
                    images.append(PassportImageMetadata(
                        index=idx,
                        file_id=file_id,
                        telegram_url=None,
                        is_regenerated=False,
                        error=str(exc)
                    ))
            else:
                # Legacy Telegram file_id — use existing resolver
                result = await telegram_service.resolve_passport_file_id(
                    client_id=client_id,
                    file_id=file_id,
                    image_index=idx,
                    session=session,
                    auto_regenerate=True
                )
                images.append(PassportImageMetadata(
                    index=idx,
                    file_id=result.file_id,
                    telegram_url=result.telegram_url,
                    is_regenerated=result.is_regenerated,
                    error=result.error
                ))
        else:
            images.append(PassportImageMetadata(
                index=idx,
                file_id=file_id,
                telegram_url=None,
                is_regenerated=False,
                error=None
            ))

    return PassportImagesMetadataResponse(
        client_id=client_id,
        image_count=len(images),
        images=images
    )


@router.get(
    "/{client_id}/passport-images/resolve/{image_index}",
    summary="Resolve single passport image file_id",
    description="Resolve a specific passport image with auto-regeneration."
)
async def resolve_passport_image(
    client_id: int,
    image_index: int,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    _: callable = Depends(get_translator),
    _admin=Depends(get_admin_user),
):
    """
    Resolve a single passport image file_id.

    Use when frontend detects an expired URL and needs a fresh one.

    Args:
        client_id: Client ID
        image_index: Index of image to resolve (0-based)

    Returns:
        Resolved file_id with temporary URL
    """
    client = await ClientDAO.get_by_id(session, client_id)

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client with ID {client_id} not found"
        )

    file_ids = parse_passport_file_ids(client.passport_images)

    if not file_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client {client_id} has no passport images"
        )

    if image_index < 0 or image_index >= len(file_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid image_index {image_index}. "
                   f"Client has {len(file_ids)} image(s) (valid: 0-{len(file_ids)-1})"
        )

    telegram_service = TelegramFileService(bot, redis)

    # S3 key detection: contains '/' → generate presigned URL
    item = file_ids[image_index]
    if "/" in item:
        try:
            presigned_url = await s3_manager.generate_presigned_url(item, expires_in=3600)
            return {
                "client_id": client_id,
                "image_index": image_index,
                "file_id": item,
                "telegram_url": presigned_url,
                "is_regenerated": False
            }
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate presigned URL: {exc}"
            )

    # Legacy Telegram file_id fallback
    result = await telegram_service.resolve_passport_file_id(
        client_id=client_id,
        file_id=item,
        image_index=image_index,
        session=session,
        auto_regenerate=True
    )

    if result.error and not result.telegram_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve image: {result.error}"
        )

    return {
        "client_id": client_id,
        "image_index": image_index,
        "file_id": result.file_id,
        "telegram_url": result.telegram_url,
        "is_regenerated": result.is_regenerated
    }


# ==================== Client CRUD Operations ====================

@router.post(
    "",
    response_model=ClientResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid data or self-referral"},
        404: {"model": ErrorResponse, "description": "Referrer not found"},
        409: {"model": ErrorResponse, "description": "Conflict - duplicate data"}
    }
)
async def create_client(
    telegram_id: Optional[int] = Form(None),
    full_name: str = Form(...),
    phone: Optional[str] = Form(None),
    passport_series: Optional[str] = Form(None),
    pinfl: Optional[str] = Form(None),
    date_of_birth: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    district: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    client_code: Optional[str] = Form(None),
    # --- Referal maydonlari ---
    referrer_telegram_id: Optional[int] = Form(None),
    referrer_client_code: Optional[str] = Form(None),
    # --------------------------
    passport_images: list[UploadFile] = File(default=[]),
    session: AsyncSession = Depends(get_session),
    _: callable = Depends(get_translator),
    _admin=Depends(get_admin_user),
):
    """
    Create a new client.

    Includes checks for unique fields and referrer validation logic.
    """

    # 1. Telegram ID bo'yicha tekshirish (faqat berilgan bo'lsa)
    if telegram_id is not None:
        existing_client = await ClientDAO.get_by_telegram_id(session, telegram_id)
        if existing_client:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_("api-error-duplicate-data", field=_("telegram-id"))
            )

    # 2. Boshqa unikal maydonlarni tekshirish
    conflicts = await ClientDAO.check_unique_fields(
        session=session,
        phone=phone,
        pinfl=pinfl,
        passport_series=passport_series
    )

    if any(conflicts.values()):
        conflict_fields = [field for field, exists in conflicts.items() if exists]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("api-error-duplicate-data", fields=', '.join([_(CONFLICT_KEYS[field]) for field in conflict_fields]))
        )

    # 3. Referrer (Taklif qiluvchi) Logikasi
    final_referrer_telegram_id = None
    final_referrer_client_code = None

    # A) Agar Referrer Code berilgan bo'lsa (Prioritet yuqori)
    if referrer_client_code:
        ref_code_clean = referrer_client_code.strip().upper()

        referrer_user = await ClientDAO.get_by_client_code(session, ref_code_clean)
        if not referrer_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_("api-error-refferer-code-not-found", referrer_client_code=ref_code_clean)
            )

        # O'zini o'zi taklif qilolmasligi kerak (Telegram ID orqali tekshiramiz)
        if telegram_id is not None and referrer_user.telegram_id == telegram_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("api-error-cannot-refer-self")
            )

        final_referrer_telegram_id = referrer_user.telegram_id
        final_referrer_client_code = referrer_user.client_code

    # B) Agar faqat Telegram ID berilgan bo'lsa
    elif referrer_telegram_id:
        if telegram_id is not None and referrer_telegram_id == telegram_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("api-error-cannot-refer-self")
            )

        referrer_user = await ClientDAO.get_by_telegram_id(session, referrer_telegram_id)

        final_referrer_telegram_id = referrer_telegram_id
        # Agar user bazada bo'lsa, kodini ham saqlaymiz
        if referrer_user:
            final_referrer_client_code = referrer_user.client_code

    # 4. Sana formatini tekshirish
    dob = None
    if date_of_birth:
        try:
            dob = date.fromisoformat(date_of_birth)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("date-of-birth-incorrect-format")
            )

    # 5. Client kodi: manual yoki auto
    if client_code:
        # Manual mode: validate uniqueness
        code_clean = client_code.strip().upper()
        existing_with_code = await ClientDAO.get_by_client_code(session, code_clean)
        if existing_with_code:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_("api-error-duplicate-data", fields=_("client-code"))
            )
        final_client_code = code_clean
    else:
        # Auto mode: generate unique code
        from src.api.utils.code_generator import generate_client_code
        final_client_code = await generate_client_code(session, region, district)

    # 6. Rasmlarni yuklash: S3 → Telegram user → Telegram admin
    passport_images_data = None
    if passport_images:
        passport_images_data = await _upload_passport_images(
            passport_images=passport_images,
            telegram_id=telegram_id,
            client_code=final_client_code,
            session=session,
        )

    # 7. Bazaga yozish
    client_data = {
        "telegram_id": telegram_id,
        "full_name": full_name,
        "phone": phone,
        "passport_series": passport_series,
        "pinfl": pinfl,
        "date_of_birth": dob,
        "region": region,
        "district": district,
        "address": address,
        "client_code": final_client_code,
        # Referrer ma'lumotlari
        "referrer_telegram_id": final_referrer_telegram_id,
        "referrer_client_code": final_referrer_client_code,
        # Rasmlar
        "passport_images": passport_images_data,
        "is_logged_in": False,
        "role": "user",
    }

    new_client = await ClientDAO.create(session, client_data)
    await session.commit()
    await session.refresh(new_client)

    return new_client


@router.put(
    "/{client_id}",
    response_model=ClientResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Client or Referrer not found"},
        409: {"model": ErrorResponse, "description": "Conflict - duplicate data"},
        400: {"model": ErrorResponse, "description": "Invalid referrer (e.g. self-referral)"}
    }
)
async def update_client(
    client_id: int,
    full_name: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    passport_series: Optional[str] = Form(None),
    pinfl: Optional[str] = Form(None),
    date_of_birth: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    district: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    client_code: Optional[str] = Form(None),
    telegram_id: Optional[int] = Form(None),
    referrer_client_code: Optional[str] = Form(None),
    referrer_telegram_id: Optional[int] = Form(None),
    passport_images: list[UploadFile] = File(default=[]),
    adjustment_amount: Optional[float] = Form(None, description="Absolute amount to add or deduct"),
    adjustment_reason: Optional[str] = Form(None, description="Reason for adjustment"),
    adjustment_type: Optional[str] = Form(None, description="Must be 'bonus', 'penalty', or 'silent'"),
    session: AsyncSession = Depends(get_session),
    _: callable = Depends(get_translator),
    _admin=Depends(get_admin_user),
):
    """
    Update an existing client.
    Supports updating referrer by client_code OR telegram_id.
    Supports updating client_code (must be unique) and telegram_id (auto-relink).
    Supports balance adjustments: bonus (visible), penalty (visible), silent (hidden SYS_ADJ).
    """

    # 1. Asosiy clientni topish
    client = await ClientDAO.get_by_id(session, client_id)

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("admin-settings-add-admin-not-found-withid", client_id=client_id)
        )

    phone_to_check = phone if phone and phone != client.phone else None
    pinfl_to_check = pinfl if pinfl and pinfl != client.pinfl else None
    passport_to_check = passport_series if passport_series and passport_series != client.passport_series else None

    # Faqat O'ZGARGAN (yoki yangi kiritilgan) noyob ma'lumotlarnigina tekshiramiz
    if phone_to_check or pinfl_to_check or passport_to_check:
        conflicts = await ClientDAO.check_unique_fields_for_update(
            session=session,
            exclude_client_id=client_id,
            phone=phone_to_check,
            pinfl=pinfl_to_check,
            passport_series=passport_to_check
        )

        if any(conflicts.values()):
            conflict_fields = [field for field, exists in conflicts.items() if exists]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_("api-error-duplicate-data", fields=', '.join([_(CONFLICT_KEYS[field]) for field in conflict_fields]))
            )

    # 3. Update Data lug'atini tayyorlash
    update_data = {}

    # --- CLIENT CODE LOGIC (Smart: routes to client_code or extra_code) ---
    if client_code is not None:
        code_clean = client_code.strip().upper()
        # Check if code is used by ANY other user in either client_code or extra_code
        existing_with_code = await ClientDAO.get_by_client_code(session, code_clean)
        if existing_with_code and existing_with_code.id != client_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_("api-error-duplicate-data", fields=_("client-code"))
            )
        # Route: if extra_code is empty → update client_code; otherwise → update extra_code
        if not client.extra_code:
            update_data["client_code"] = code_clean
        else:
            update_data["extra_code"] = code_clean

    # --- TELEGRAM ID LOGIC (Auto-relink) ---
    if telegram_id is not None:
        # Only update if different from current
        if telegram_id != client.telegram_id:
            # Check if ID belongs to another user
            existing_owner = await ClientDAO.get_by_telegram_id(session, telegram_id)
            if existing_owner and existing_owner.id != client_id:
                # Auto-relink: unlink from old owner
                existing_owner.telegram_id = None
                existing_owner.is_logged_in = False
                session.add(existing_owner)
            update_data["telegram_id"] = telegram_id

    # --- REFERRER LOGIKASI ---

    # A) Agar Admin Referrer Kodini yuborgan bo'lsa (Prioritet yuqori)
    if referrer_client_code:
        ref_code_clean = referrer_client_code.strip().upper()

        # O'zini o'zi referal qilolmasligi kerak
        if client.client_code and ref_code_clean == client.client_code.upper():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("api-error-cannot-refer-self")
            )

        referrer_user = await ClientDAO.get_by_client_code(session, ref_code_clean)
        if not referrer_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_("api-error-refferer-code-not-found", referrer_client_code=ref_code_clean)
            )

        update_data["referrer_telegram_id"] = referrer_user.telegram_id
        update_data["referrer_client_code"] = referrer_user.client_code

    # B) Agar faqat Telegram ID yuborgan bo'lsa
    elif referrer_telegram_id:
        # O'zini o'zi ID orqali referal qilolmasligi kerak
        if client.telegram_id and referrer_telegram_id == client.telegram_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("api-error-cannot-refer-self")
            )

        referrer_user = await ClientDAO.get_by_telegram_id(session, referrer_telegram_id)

        update_data["referrer_telegram_id"] = referrer_telegram_id
        if referrer_user:
            update_data["referrer_client_code"] = referrer_user.client_code

    # 4. Rasmlarni yuklash: S3 → Telegram user → Telegram admin
    if passport_images:
        # Priority: new telegram_id (if being updated) > existing client.telegram_id
        client_chat_id = telegram_id if telegram_id is not None else client.telegram_id
        effective_code = (
            update_data.get("client_code")
            or update_data.get("extra_code")
            or client.extra_code
            or client.client_code
        )
        update_data["passport_images"] = await _upload_passport_images(
            passport_images=passport_images,
            telegram_id=client_chat_id,
            client_code=effective_code,
            session=session,
        )

    # 5. Qolgan maydonlar
    if full_name is not None:
        update_data["full_name"] = full_name
    if phone is not None:
        update_data["phone"] = phone
    if passport_series is not None:
        update_data["passport_series"] = passport_series
    if pinfl is not None:
        update_data["pinfl"] = pinfl
    if date_of_birth is not None:
        try:
            update_data["date_of_birth"] = date.fromisoformat(date_of_birth)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("date-of-birth-incorrect-format")
            )
    if region is not None:
        update_data["region"] = region
    if district is not None:
        update_data["district"] = district
    if address is not None:
        update_data["address"] = address

    # 6. Yakuniy yangilash
    updated_client = await ClientDAO.update(session, client, update_data)

    # 7. Balance Adjustment (Bonus / Penalty / Silent)
    if adjustment_amount is not None and adjustment_type is not None:
        if adjustment_type not in ("bonus", "penalty", "silent"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="adjustment_type must be 'bonus', 'penalty', or 'silent'"
            )

        reason = (adjustment_reason or "").strip()
        adj_client_code = updated_client.extra_code or updated_client.client_code

        if adjustment_type == "bonus":
            balance_diff = abs(adjustment_amount)
            reys_value = f"BONUS:{reason}"
        elif adjustment_type == "penalty":
            balance_diff = -abs(adjustment_amount)
            reys_value = f"PENALTY:{reason}"
        else:  # silent
            balance_diff = adjustment_amount
            reys_value = f"SYS_ADJ:{reason}"

        await ClientTransactionDAO.create(session, {
            "telegram_id": updated_client.telegram_id,
            "client_code": adj_client_code,
            "qator_raqami": 0,
            "summa": 0,
            "vazn": "0",
            "reys": reys_value,
            "payment_type": "online",
            "payment_status": "paid",
            "paid_amount": 0,
            "remaining_amount": 0,
            "is_taken_away": True,
            "payment_balance_difference": balance_diff,
        })

    await session.commit()
    await session.refresh(updated_client)

    # Calculate current balance for response
    current_balance = 0.0
    response_client_code = updated_client.extra_code or updated_client.client_code
    if response_client_code:
        current_balance = await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
            session, response_client_code
        )

    response = ClientResponse.model_validate(updated_client)
    response.current_balance = current_balance
    return response


@router.delete("/{client_id}", response_model=ClientDeleteResponse)
async def delete_client(
    client_id: int,
    session: AsyncSession = Depends(get_session),
    _: callable = Depends(get_translator),
    _admin=Depends(get_admin_user),
):
    """
    Delete a client by ID.

    This is a hard delete - the client record will be permanently removed.
    """
    client = await ClientDAO.get_by_id(session, client_id)

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("admin-settings-add-admin-not-found-withid", client_id=client_id)
        )

    await ClientDAO.delete(session, client)
    await session.commit()

    return ClientDeleteResponse(
        message=f"Client {client_id} deleted successfully",
        deleted_client_id=client_id
    )