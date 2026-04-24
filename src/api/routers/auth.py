"""Authentication API endpoints."""

import json
import secrets
from typing import List
from aiogram.types import FSInputFile, InputMediaPhoto
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from pydantic import ValidationError

from src.api.dependencies import (
    get_db,
    get_redis,
    get_translator,
    SESSION_PREFIX,
    SESSION_TTL_SECONDS,
    get_current_user,
)
from src.api.utils.constants import UZBEKISTAN_REGIONS
from src.api.utils.telegram_auth import validate_telegram_init_data
from src.bot.bot_instance import bot
from src.bot.keyboards.user.reply_keyb.user_home_kyb import user_main_menu_kyb
from src.bot.utils.referral_cache import get_referral_data, delete_referral_data
from src.infrastructure.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    TelegramLoginRequest,
    ValidateInitDataRequest,
    ValidateInitDataResponse,
    ErrorResponse,
    AuthMeResponse,
)
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.dao.client_extra_passport import ClientExtraPassportDAO
from src.infrastructure.tools.s3_manager import s3_manager
from src.infrastructure.tools.image_optimizer import optimize_image_to_webp
from src.config import Config, BASE_DIR
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])
config = Config()


def get_effective_role(client, bot_config) -> str:
    if client.telegram_id and bot_config.ADMIN_ACCESS_IDs:
        if client.telegram_id in bot_config.ADMIN_ACCESS_IDs:
            return "super-admin"
    return getattr(client, "role", None) or "user"  # ← None bo'lsa "user" qaytaradi


CONFLICT_KEYS = {
    "pinfl": "conflict-pinfl",
    "phone": "conflict-phone",
    "passport_series": "conflict-passport-series",
    "telegram_id": "conflict-telegram-id",
}


# ─── Helper: Telegram notifications (background, never raises) ───────────────


async def _notify_login_telegram(
    telegram_id: int,
    full_name: str,
    phone: str,
    client_code: str,
    translator: callable,
) -> None:
    """Send welcome message + China address images. Never raises."""
    if not telegram_id:
        logger.warning("_notify_login_telegram: telegram_id is None, skipping")
        return

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=translator("start")
            + "\n\n"
            + translator(
                "start-registered",
                full_name=full_name,
                phone=phone or translator("not-provided"),
                client_code=client_code,
            ),
            reply_markup=user_main_menu_kyb(translator=translator),
        )
    except Exception as e:
        logger.error("Login welcome message failed for %s: %s", telegram_id, e)

    try:
        from pathlib import Path

        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        image_path_pindoudou = (
            base_dir / "src" / "assets" / "images" / "pindoudou_temp.jpg"
        )
        image_path_taobao = base_dir / "src" / "assets" / "images" / "taobao_temp.jpg"

        media = [
            InputMediaPhoto(
                media=FSInputFile(str(image_path_pindoudou)),
                caption=(
                    f"{client_code} 18161955318\n"
                    "陕西省咸阳市渭城区 北杜街道\n"
                    f"昭容南街东航物流园内中京仓{client_code}号仓库"
                ),
            ),
            InputMediaPhoto(media=FSInputFile(str(image_path_taobao))),
        ]
        await bot.send_media_group(chat_id=telegram_id, media=media)
        await bot.send_message(
            chat_id=telegram_id,
            text=translator("china-address-warning"),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("China address images failed for %s: %s", telegram_id, e)


# ─── Helper: Register notifications (background, never raises) ───────────────


async def _notify_register_telegram(
    telegram_id: int,
    full_name: str,
    passport_series: str,
    date_of_birth: str,
    region: str,
    address: str,
    phone: str,
    pinfl: str,
    s3_keys: list[str],
    success_message: str,
) -> None:
    """Send registration approval notification + waiting message. Never raises."""
    from src.api.utils import (
        send_registration_to_approval_group,
        send_waiting_message_to_user,
    )

    try:
        await send_registration_to_approval_group(
            telegram_id=telegram_id,
            full_name=full_name,
            passport_series=passport_series,
            date_of_birth=date_of_birth,
            region=region,
            address=address,
            phone=phone,
            pinfl=pinfl,
            s3_keys=s3_keys,
            bot=bot,
        )
    except Exception as e:
        logger.error(
            "send_registration_to_approval_group failed for %s: %s", telegram_id, e
        )

    try:
        await send_waiting_message_to_user(
            telegram_id=telegram_id,
            bot=bot,
            message=success_message,
        )
    except Exception as e:
        logger.error("send_waiting_message_to_user failed for %s: %s", telegram_id, e)


async def _notify_relink_telegram(
    telegram_id: int,
    full_name: str,
    client_code: str,
    phone: str,
    translator: callable,
) -> None:
    """Send security relink alert. Never raises."""
    if not telegram_id:
        return
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=translator(
                "security-alert-relink",
                full_name=full_name or translator("not-provided"),
                client_code=client_code or "-",
                phone=phone or translator("not-provided"),
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("Relink security alert failed for %s: %s", telegram_id, e)


@router.post(
    "/telegram-login",
    response_model=LoginResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid initData"},
        404: {"model": ErrorResponse, "description": "Client not found"},
        403: {"model": ErrorResponse, "description": "Registration pending approval"},
    },
)
async def telegram_login(
    request: TelegramLoginRequest,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _: callable = Depends(get_translator),
) -> LoginResponse:
    """
    Telegram auto-login endpoint.

    Validates Telegram Web App initData, looks up the client by telegram_id,
    and issues a session token without requiring client_code + phone.
    """
    user_data = validate_telegram_init_data(
        init_data=request.init_data, bot_token=config.telegram.TOKEN.get_secret_value()
    )

    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("api-error-invalid-init-data"),
        )

    user_id = user_data.get("id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("api-error-invalid-init-data"),
        )

    client = await ClientDAO.get_by_telegram_id(session, user_id)

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("api-error-client-not-found"),
        )

    if not client.client_code:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("api-error-registration-pending"),
        )
    if not client.is_logged_in:
        raise HTTPException(status_code=403, detail=_("api-error-not-logged-in"))

    if not client.region or not client.district:
        raise HTTPException(status_code=403, detail=_("api-error-address-required"))

    session_token = secrets.token_urlsafe(32)
    await redis.setex(
        f"{SESSION_PREFIX}{session_token}",
        SESSION_TTL_SECONDS,
        str(client.id),
    )

    return LoginResponse(
        client_code=client.client_code,
        full_name=client.full_name,
        phone=client.phone,
        telegram_id=client.telegram_id,
        created_at=client.created_at,
        access_token=session_token,
        token_type="Bearer",
        role=get_effective_role(client, config.telegram),
    )


# ─── Main login endpoint ──────────────────────────────────────────────────────
@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Client not found"},
        400: {
            "model": ErrorResponse,
            "description": "Invalid request or credentials mismatch",
        },
        403: {"model": ErrorResponse, "description": "Registration pending approval"},
        409: {
            "model": ErrorResponse,
            "description": "Conflict - client already logged in",
        },
        428: {"model": ErrorResponse, "description": "Address required"},
    },
)
async def login(
    request: LoginRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _: callable = Depends(get_translator),
) -> LoginResponse:
    """
    Login endpoint - authenticate client by client_code + phone_number.

    Critical path  : DB lookup → update → flush → commit → Redis token → return
    Non-critical   : Telegram notifications run in BackgroundTasks (never break login)
    """

    # ── 1. Lookup ────────────────────────────────────────────────────────────
    client = await ClientDAO.get_by_client_code_and_phone(
        session=session,
        client_code=request.client_code,
        phone=request.phone_number,
    )
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("api-error-client-not-found"),
        )

    if not client.client_code:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("api-error-registration-pending"),
        )

    # ── 2. Address logic ─────────────────────────────────────────────────────
    is_address_newly_provided = False
    if request.region is not None and request.district is not None:
        if not client.region or not client.district:
            is_address_newly_provided = True
        client.region = request.region
        client.district = request.district

    if not client.region or not client.district:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED, detail="address_required"
        )

    if is_address_newly_provided and not client.extra_code:
        from src.api.utils.code_generator import generate_client_code

        client.extra_code = await generate_client_code(
            session, client.region, client.district
        )

    # ── 3. Telegram relink ───────────────────────────────────────────────────
    client.is_logged_in = True
    event_type = "LOGIN"
    relink_notify_id: int | None = None  # for background notification

    if request.telegram_id:
        old_owner = await ClientDAO.get_by_telegram_id(session, request.telegram_id)
        if old_owner and old_owner.id != client.id:
            # Save info for background notification BEFORE unlinking
            relink_notify_id = client.telegram_id or old_owner.telegram_id
            # Unlink old owner
            old_owner.telegram_id = None
            old_owner.is_logged_in = False
            event_type = "RELINK"
            await session.flush()  # free unique constraint

        client.telegram_id = request.telegram_id

    # ── 4. DB commit (CRITICAL) ───────────────────────────────────────────────
    try:
        await session.flush()

        from src.infrastructure.database.dao.session_log import SessionLogDAO

        await SessionLogDAO.add_log(
            session=session,
            client_id=client.id,
            telegram_id=request.telegram_id or client.telegram_id,
            event_type=event_type,
            client_code=client.primary_code,
            phone=client.phone,
            username=client.username,
        )
        await session.commit()

    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("api-error-telegram-id-already-exists"),
        )

    # ── 5. Redis session token (CRITICAL) ────────────────────────────────────
    session_token = secrets.token_urlsafe(32)
    await redis.setex(
        f"{SESSION_PREFIX}{session_token}",
        SESSION_TTL_SECONDS,
        str(client.id),
    )

    # ── 6. Telegram notifications → BackgroundTasks (NON-CRITICAL) ───────────
    effective_chat_id: int | None = request.telegram_id or client.telegram_id
    effective_code = client.primary_code

    if relink_notify_id:
        background_tasks.add_task(
            _notify_relink_telegram,
            relink_notify_id,
            client.full_name,
            effective_code,
            client.phone,
            _,
        )

    if effective_chat_id:
        background_tasks.add_task(
            _notify_login_telegram,
            effective_chat_id,
            client.full_name,
            client.phone or "",
            effective_code,
            _,
        )
    else:
        logger.warning(
            "Login succeeded but no telegram_id to notify (client_code=%s)",
            effective_code,
        )

    # ── 7. Return response ────────────────────────────────────────────────────
    return LoginResponse(
        client_code=client.client_code,
        full_name=client.full_name,
        phone=client.phone,
        telegram_id=request.telegram_id or client.telegram_id,
        created_at=client.created_at,
        access_token=session_token,
        token_type="Bearer",
        role=get_effective_role(client, config.telegram),
    )


@router.post(
    "/register",
    response_model=RegisterResponse,
    responses={
        409: {"model": ErrorResponse, "description": "Conflict - duplicate data"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
    },
)
async def register(
    full_name: str = Form(...),
    passport_series: str = Form(...),
    pinfl: str = Form(...),
    region: str = Form(...),
    district: str = Form(...),
    address: str = Form(...),
    phone_number: str = Form(...),
    date_of_birth: str = Form(...),
    telegram_id: int = Form(...),
    passport_images: List[UploadFile] = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _: callable = Depends(get_translator),
) -> RegisterResponse:
    """
    Register new client with passport images.

    Critical path  : validate → check conflicts → S3 upload → DB create → commit → return
    Non-critical   : Telegram notifications run in BackgroundTasks (never break register)
    """

    # ── 1. Validate request data ─────────────────────────────────────────────
    try:
        from datetime import date

        dob = date.fromisoformat(date_of_birth)
        register_data = RegisterRequest(
            full_name=full_name,
            passport_series=passport_series,
            pinfl=pinfl,
            region=region,
            district=district,
            address=address,
            phone_number=phone_number,
            date_of_birth=dob,
        )
    except (ValidationError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("api-error-invalid-data", error=str(e)),
        )

    # ── 2. Check unique constraints (main Client table) ───────────────────────
    conflicts = await ClientDAO.check_unique_fields(
        session=session,
        telegram_id=telegram_id,
        phone=register_data.phone_number,
        pinfl=register_data.pinfl,
        passport_series=register_data.passport_series,
    )
    if any(conflicts.values()):
        conflict_fields = [f for f, exists in conflicts.items() if exists]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_(
                "api-error-duplicate-data",
                fields=", ".join([_(CONFLICT_KEYS[f]) for f in conflict_fields]),
            ),
        )

    # ── 3. Check unique constraints (extra passports table) ───────────────────
    extra_conflicts = await ClientExtraPassportDAO.check_duplicate_passport(
        session=session,
        passport_series=register_data.passport_series,
        pinfl=register_data.pinfl,
        telegram_id=telegram_id,
    )
    if any(extra_conflicts.values()):
        conflict_fields = []
        if extra_conflicts.get("passport_series"):
            conflict_fields.append("passport_series")
        if extra_conflicts.get("pinfl"):
            conflict_fields.append("pinfl")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_(
                "api-error-duplicate-extra-passport", fields=", ".join(conflict_fields)
            ),
        )

    # ── 4. S3 upload (CRITICAL — before DB create) ────────────────────────────
    s3_keys: list[str] = []
    s3_base_folders = ["passport-front-images", "passport-back-images"]

    try:
        for idx, img in enumerate(passport_images[:2]):
            await img.seek(0)
            raw_content = await img.read()
            optimized = await optimize_image_to_webp(raw_content)
            s3_key = await s3_manager.upload_file(
                file_content=optimized,
                file_name=img.filename or f"passport_{idx}.webp",
                telegram_id=telegram_id,
                client_code=None,
                base_folder=s3_base_folders[idx],
                sub_folder="",
                content_type="image/webp",
            )
            s3_keys.append(s3_key)
    except Exception as e:
        # Clean up any partial uploads
        for key in s3_keys:
            try:
                await s3_manager.delete_file(key)
            except Exception:
                pass
        logger.error(
            "S3 upload failed for telegram_id=%s: %s", telegram_id, e, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("api-error-registration-failed", error=str(e)),
        )

    # ── 5. Referral data from Redis ───────────────────────────────────────────
    referral_data = await get_referral_data(redis=redis, telegram_id=telegram_id)

    # ── 6. DB create (CRITICAL) ───────────────────────────────────────────────
    client_data = {
        "telegram_id": telegram_id,
        "full_name": register_data.full_name,
        "phone": register_data.phone_number,
        "passport_series": register_data.passport_series,
        "pinfl": register_data.pinfl,
        "date_of_birth": register_data.date_of_birth,
        "region": register_data.region,
        "district": register_data.district,
        "address": register_data.address,
        "passport_images": json.dumps(s3_keys),
        "client_code": None,
        "is_logged_in": False,
        "referrer_telegram_id": referral_data.get("referrer_telegram_id")
        if referral_data
        else None,
        "referrer_client_code": referral_data.get("referrer_client_code")
        if referral_data
        else None,
    }

    try:
        client = await ClientDAO.create(session=session, data=client_data)
        await session.commit()
    except Exception as e:
        await session.rollback()
        # Clean up S3 files — DB failed, no orphan files
        for key in s3_keys:
            try:
                await s3_manager.delete_file(key)
            except Exception:
                pass
        logger.error(
            "DB create failed for telegram_id=%s: %s", telegram_id, e, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("api-error-registration-failed", error=str(e)),
        )

    # ── 7. Analytics event (CRITICAL — but non-blocking on failure) ───────────
    try:
        from src.infrastructure.services.analytics_service import AnalyticsService

        await AnalyticsService.emit_event(
            session=session,
            event_type="client_registration",
            user_id=telegram_id,
            payload={
                "client_id": client.id,
                "full_name": client.full_name,
                "phone": client.phone,
                "region": client.region,
                "has_referrer": bool(referral_data),
                "referrer_telegram_id": referral_data.get("referrer_telegram_id")
                if referral_data
                else None,
            },
        )
        await session.commit()
    except Exception as e:
        logger.warning("Analytics emit failed for telegram_id=%s: %s", telegram_id, e)
        # Don't break registration — analytics is non-critical

    # ── 8. Referral cleanup ───────────────────────────────────────────────────
    if referral_data:
        try:
            await delete_referral_data(redis=redis, telegram_id=telegram_id)
        except Exception as e:
            logger.warning(
                "Referral cache cleanup failed for telegram_id=%s: %s", telegram_id, e
            )

    # ── 9. Build region string (sync, no bot — safe here) ────────────────────
    try:
        with open(
            BASE_DIR / "locales" / "district_uz.json", "r", encoding="utf-8"
        ) as f:
            district_map = json.load(f).get("districts", {}).get(client.region, {})
        region_str = UZBEKISTAN_REGIONS.get(client.region, client.region)
        full_region_string = (
            f"{region_str}, {district_map.get(client.district, client.district)}"
        )
    except Exception as e:
        logger.warning("Region string build failed: %s", e)
        full_region_string = f"{client.region}, {client.district}"

    # ── 10. Telegram notifications → BackgroundTasks (NON-CRITICAL) ──────────
    background_tasks.add_task(
        _notify_register_telegram,
        telegram_id=telegram_id,
        full_name=client.full_name,
        passport_series=client.passport_series,
        date_of_birth=str(client.date_of_birth),
        region=full_region_string,
        address=client.address,
        phone=client.phone,
        pinfl=client.pinfl,
        s3_keys=s3_keys,
        success_message=_("api-success-registration"),
    )

    # ── 11. Return response ───────────────────────────────────────────────────
    return RegisterResponse(
        client_code=None,
        full_name=client.full_name,
        phone=client.phone,
        passport_series=client.passport_series,
        pinfl=client.pinfl,
        telegram_id=client.telegram_id,
        message=_("api-success-registration"),
    )


@router.post(
    "/validate-init-data",
    response_model=ValidateInitDataResponse,
    responses={400: {"model": ErrorResponse, "description": "Invalid initData"}},
)
async def validate_init_data(
    request: ValidateInitDataRequest, _: callable = Depends(get_translator)
) -> ValidateInitDataResponse:
    """
    Validate Telegram Web App initData using HMAC SHA256.

    Returns user data if valid, error otherwise.
    """
    user_data = validate_telegram_init_data(
        init_data=request.init_data, bot_token=config.telegram.TOKEN.get_secret_value()
    )

    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("api-error-invalid-init-data"),
        )

    return ValidateInitDataResponse(
        valid=True,
        user_id=user_data.get("id"),
        username=user_data.get("username"),
        first_name=user_data.get("first_name"),
        last_name=user_data.get("last_name"),
        message=_("api-success-init-data"),
    )


@router.get(
    "/me",
    response_model=AuthMeResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized or session expired"}
    },
)
async def get_me(
    current_client=Depends(get_current_user),
) -> AuthMeResponse:
    """
    Get current authenticated user profile and role securely via Session Token.
    This is used by the frontend for Role-Based Access Control (RBAC).

    If client has no region/district → 401 (force re-login to fill address).
    """
    if not current_client.region or not current_client.district:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="address_required_relogin",
        )

    return AuthMeResponse(
        id=current_client.id,
        client_code=current_client.client_code,
        full_name=current_client.full_name,
        phone=current_client.phone,
        telegram_id=current_client.telegram_id,
        role=get_effective_role(current_client, config.telegram),
    )
