import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.api.dependencies import get_db, get_redis, get_current_user, get_translator, SESSION_PREFIX
from src.infrastructure.database.models.client import Client
from src.api.schemas.profile import (
    ProfileResponse,
    UpdateProfileRequest,
    SessionHistoryResponse,
    SessionLogItem
)

router = APIRouter(prefix="/profile", tags=["Profile"])

# Region constants (reused from legacy code logic, but ideally should be shared)
UZBEKISTAN_REGIONS = {
    "toshkent_city": "region-toshkent-city",
    "toshkent": "region-toshkent",
    "andijan": "region-andijan",
    "bukhara": "region-bukhara",
    "fergana": "region-fergana",
    "jizzakh": "region-jizzakh",
    "kashkadarya": "region-qashqadarya",
    "navoi": "region-navoiy",
    "namangan": "region-namangan",
    "samarkand": "region-samarkand",
    "sirdarya": "region-sirdarya",
    "surkhandarya": "region-surkhandarya",
    "karakalpakstan": "region-karakalpakstan",
    "khorezm": "region-khorezm"
}

EVENT_TYPE_KEYS = {
    "LOGIN": "event-login",
    "RELINK": "event-relink",
    "LOGOUT": "event-logout"
}


def _get_language_from_header(accept_language: str | None) -> str:
    """Extract language code from Accept-Language header."""
    if accept_language:
        lang = accept_language.strip().lower()[:2]
        if lang in ("ru", "uz"):
            return lang
    return "uz"


def _get_district_display(region_key: str | None, district_key: str | None, language: str) -> str | None:
    """Load district translation from JSON file based on language."""
    if not district_key or not region_key:
        return None
    file_path = "locales/district_ru.json" if language == "ru" else "locales/district_uz.json"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("districts", {}).get(region_key, {}).get(district_key, district_key)
    except Exception:
        return district_key

@router.get("/me", response_model=ProfileResponse)
async def get_profile(
    client: Client = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    accept_language: str | None = Header(None, alias="Accept-Language")
):
    """
    Get current user profile.
    """
    language = _get_language_from_header(accept_language)

    # 1. Count referrals
    from src.infrastructure.database.dao.client import ClientDAO
    referral_count = await ClientDAO.count_referrals(session, client.telegram_id)

    # 2. Parse passport images and resolve S3 keys to presigned URLs
    passport_images = []
    if client.passport_images:
        try:
            images = json.loads(client.passport_images)
            if isinstance(images, list):
                passport_images = images
            else:
                passport_images = [images]
        except json.JSONDecodeError:
            pass
    if passport_images:
        from src.infrastructure.tools.passport_image_resolver import resolve_passport_items
        passport_images = await resolve_passport_items(passport_images)

    # 3. Format Region
    region_display = client.region
    # Try to find translation key if it's a raw key
    if client.region in UZBEKISTAN_REGIONS:
        region_display = _(UZBEKISTAN_REGIONS[client.region])
    else:
        key = UZBEKISTAN_REGIONS.get(client.region, client.region)
        region_display = _(key)

    # 4. Format District
    district_display = _get_district_display(client.region, client.district, language)

    return ProfileResponse(
        full_name=client.full_name or _("not-provided"),
        phone=client.phone or _("not-provided"),
        client_code=client.primary_code or _("not-provided"),
        extra_code=client.primary_code or _("not-provided"),
        passport_series=client.passport_series or _("not-provided"),
        pinfl=client.pinfl or _("not-provided"),
        date_of_birth=client.date_of_birth.strftime("%d.%m.%Y") if client.date_of_birth else _("not-provided"),
        region=region_display,
        district=district_display,
        address=client.address or _("not-provided"),
        created_at=client.created_at.strftime("%d.%m.%Y %H:%M") if client.created_at else _("not-provided"),
        referral_count=referral_count,
        passport_images=passport_images,
        telegram_id=client.telegram_id
    )


@router.patch("/me", response_model=ProfileResponse)
async def update_profile(
    request: UpdateProfileRequest,
    client: Client = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    accept_language: str | None = Header(None, alias="Accept-Language")
):
    """
    Update profile fields.
    """
    language = _get_language_from_header(accept_language)
    update_data = {}
    if request.full_name:
        update_data["full_name"] = request.full_name
    if request.phone:
        update_data["phone"] = request.phone
    if request.region:
        if request.region in UZBEKISTAN_REGIONS:
             update_data["region"] = _(UZBEKISTAN_REGIONS[request.region])
        else:
             update_data["region"] = request.region

    if request.district is not None:
        update_data["district"] = request.district

    if request.address:
        update_data["address"] = request.address

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("api-error-no-data-to-update")
        )

    
    from src.infrastructure.database.dao.client import ClientDAO
    updated_client = await ClientDAO.update(session, client, update_data)
    await session.commit()
    
    
    # ... (same logic as get_profile for formatting)
    referral_count = await ClientDAO.count_referrals(session, updated_client.telegram_id)
    
    passport_images = []
    if updated_client.passport_images:
        try:
             images = json.loads(updated_client.passport_images)
             passport_images = images if isinstance(images, list) else [images]
        except: pass
    if passport_images:
        from src.infrastructure.tools.passport_image_resolver import resolve_passport_items
        passport_images = await resolve_passport_items(passport_images)

    region_key = UZBEKISTAN_REGIONS.get(updated_client.region, updated_client.region)
    region_display = _(region_key)

    # Format district
    district_display = _get_district_display(updated_client.region, updated_client.district, language)

    return ProfileResponse(
        full_name=updated_client.full_name or _("not-provided"),
        phone=updated_client.phone or _("not-provided"),
        client_code=updated_client.primary_code or _("not-provided"),
        extra_code=updated_client.primary_code or _("not-provided"),
        passport_series=updated_client.passport_series or _("not-provided"),
        pinfl=updated_client.pinfl or _("not-provided"),
        date_of_birth=updated_client.date_of_birth.strftime("%d.%m.%Y") if updated_client.date_of_birth else _("not-provided"),
        region=region_display,
        district=district_display,
        address=updated_client.address or _("not-provided"),
        created_at=updated_client.created_at.strftime("%d.%m.%Y %H:%M") if updated_client.created_at else _("not-provided"),
        referral_count=referral_count,
        passport_images=passport_images,
        telegram_id=updated_client.telegram_id
    )


@router.post("/logout")
async def logout(
    request: Request,
    client: Client = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _: callable = Depends(get_translator)
):
    """
    Log out the user (set is_logged_in = False) and revoke session token.
    """
    from src.infrastructure.database.dao.client import ClientDAO

    await ClientDAO.update(session, client, {"is_logged_in": False})

    # Revoke the session token in Redis (if present)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
        await redis.delete(f"{SESSION_PREFIX}{token}")

    # Log the logout event
    from src.infrastructure.database.dao.session_log import SessionLogDAO
    await SessionLogDAO.add_log(
        session=session,
        client_id=client.id,
        telegram_id=client.telegram_id,
        event_type="LOGOUT",
        client_code=client.primary_code or _("not-provided"),
        phone=client.phone
    )

    await session.commit()
    return {"message": _("profile-logged-out")}


@router.get("/sessions", response_model=SessionHistoryResponse)
async def get_session_history(
    page: int = 1,
    limit: int = 10,
    client: Client = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator)
):
    """
    Get session history (login/logout events).
    """
    offset = (page - 1) * limit
    
    from src.infrastructure.database.dao.session_log import SessionLogDAO
    from src.infrastructure.tools.datetime_utils import to_tashkent
    
    # 20 is hard limit in DAO logic, but we can query with pagination
    logs = await SessionLogDAO.get_by_client_id(session, client.id, limit=limit, offset=offset)
    
    response_logs = []
    for log in logs:
        local_dt = to_tashkent(log.created_at) if log.created_at else None
        date_str = local_dt.strftime("%d.%m.%Y %H:%M") if local_dt else "-"
        
        # Translate event type
        event_label = log.event_type
        if log.event_type in EVENT_TYPE_KEYS:
             event_label = _(EVENT_TYPE_KEYS[log.event_type])
        
        response_logs.append(SessionLogItem(
            date=date_str,
            client_code=log.client_code or "-",
            event_type=event_label,
            username=log.username
        ))
        
    return SessionHistoryResponse(logs=response_logs)
