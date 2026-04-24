"""
User Delivery Request ("Zayavka") API endpoints.

Replicates the Telegram bot's multi-step delivery request flow
as stateless REST endpoints for the frontend.
"""


import contextlib
import json
import logging
import math
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Form,
    Query,
    UploadFile,
    File,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.api.dependencies import get_db, get_current_user, get_redis
from src.api.schemas.delivery import (
    PaidFlightsResponse,
    FlightItem,
    CalculateUzpostRequest,
    CalculateUzpostResponse,
    CardInfo,
    StandardDeliveryRequest,
    DeliverySuccessResponse,
    DeliveryHistoryResponse,
    DeliveryRequestHistoryItem,
)
from src.api.utils.constants import UZBEKISTAN_REGIONS
from src.bot.bot_instance import bot
from src.config import config, BASE_DIR
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.delivery_request import DeliveryRequestDAO
from src.infrastructure.database.dao.expected_cargo import ExpectedFlightCargoDAO
from src.infrastructure.services.payment_card import PaymentCardService

router = APIRouter(prefix="/user/delivery", tags=["user-delivery"])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (mirrored from bot handler)
# ---------------------------------------------------------------------------
special_regions = ["Qoraqalpog'iston", "Surxondaryo", "Xorazm"]

DELIVERY_TYPES = {
    "uzpost": "UzPost",
    "yandex": "Yandex",
    "akb": "AKB",
    "bts": "BTS",
}

# ---------------------------------------------------------------------------
# Helper functions (reused from bot handler)
# ---------------------------------------------------------------------------


def calculate_price(total_weight: float, region: str) -> int:
    """Calculate delivery price based on weight and region."""
    if total_weight <= 0:
        return 0

    is_special = region in special_regions

    if is_special:
        base_price = 18000
        step_price = 7000
    else:
        base_price = 15000
        step_price = 3000

    if total_weight <= 1:
        return base_price

    extra_kg = math.ceil(total_weight - 1)
    return base_price + extra_kg * step_price


async def calculate_total_weight(
    session: AsyncSession,
    flight_name: str,
    client_code: str | list[str],
) -> float:
    """Calculate total weight for a client in a flight."""
    transactions = await ClientTransactionDAO.get_by_client_code_and_flight(
        session, client_code, flight_name
    )
    valid = [
        t
        for t in transactions
        if t.payment_status == "paid" and (t.remaining_amount or 0) <= 0
    ]
    return sum(float(t.vazn or 0) for t in valid)


async def get_cached_sheets_data(client_code: str, redis: Redis) -> dict:
    """Get cached sheets data or fetch from Google Sheets API."""
    from src.bot.utils.google_sheets_checker import GoogleSheetsChecker

    cache_key = f"sheets_data:{client_code}"

    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    checker = GoogleSheetsChecker(
        spreadsheet_id=config.google_sheets.SHEETS_ID,
        api_key=config.google_sheets.API_KEY,
        last_n_sheets=5,
    )
    result = await checker.find_client_group(client_code)

    if result["found"]:
        await redis.setex(cache_key, 300, json.dumps(result, ensure_ascii=False))

    return result


def _validate_profile(client) -> None:
    """Raise 400 if the client profile is incomplete."""
    if not all([client.full_name, client.phone, client.region, client.address]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile is incomplete. Please fill in your full name, phone, region, and address first.",
        )


def _build_admin_text(
    delivery_request_id: int,
    client,
    delivery_type: str,
    flight_names: list[str],
) -> str:
    """Build plain-text admin notification (Uzbek, matches bot format)."""
    region_str = UZBEKISTAN_REGIONS.get(client.region, client.region)

    # Load district translations
    try:
        with open(
            BASE_DIR / "locales" / "district_uz.json", "r", encoding="utf-8"
        ) as f:
            district_data = json.load(f).get("districts", {}).get(client.region, {})
    except Exception:
        district_data = {}

    district_str = district_data.get(client.district, client.district or "")
    full_region = f"{region_str}, {district_str}" if district_str else region_str

    return (
        f"📦 <b>YANGI YETKAZIB BERISH SO'ROVI</b>\n\n"
        f"🔢 <b>ID:</b> {delivery_request_id}\n"
        f"👤 <b>Mijoz:</b> {client.full_name} ({client.client_code})\n"
        f"📱 <b>Tel:</b> {client.phone}\n"
        f"🚚 <b>Turi:</b> {DELIVERY_TYPES.get(delivery_type, delivery_type)}\n"
        f"✈️ <b>Reyslar:</b> {', '.join(flight_names)}\n"
        f"📍 <b>Manzil:</b> {full_region}, {client.address}"
    )


def _build_admin_keyboard(delivery_request_id: int):
    """Build approve/reject inline keyboard for admin notifications."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash",
                    callback_data=f"approve_delivery:{delivery_request_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Rad etish",
                    callback_data=f"reject_delivery:{delivery_request_id}",
                )
            ],
        ]
    )


async def _send_admin_notification(
    chat_id: int,
    text: str,
    delivery_request_id: int,
    document=None,
):
    """
    Send admin notification with approve/reject inline keyboard.

    If a document (BufferedInputFile) is provided, sends it as a document
    with the text as caption — all in one message. Otherwise sends a text message.

    Returns the sent Telegram Message object.
    """
    keyboard = _build_admin_keyboard(delivery_request_id)

    if document is not None:
        return await bot.send_document(
            chat_id=chat_id,
            document=document,
            caption=text,
            reply_markup=keyboard,
        )
    else:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/history", response_model=DeliveryHistoryResponse)
async def get_delivery_history(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=50, description="Items per page"),
    client=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    Fetch the paginated delivery request history for the authenticated client.
    """
    offset = (page - 1) * size
    requests = await DeliveryRequestDAO.get_by_client_paginated(
        session, client.id, size, offset
    )
    total_count = await DeliveryRequestDAO.count_by_client(session, client.id)

    return DeliveryHistoryResponse(
        requests=requests,
        total_count=total_count,
        page=page,
        size=size,
        has_next=(offset + size) < total_count,
    )


@router.get("/flights", response_model=PaidFlightsResponse)
async def get_paid_flights(
    client=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """
    Fetch available paid flights for the authenticated user.

    Returns deduplicated flight names where payment has been verified.
    Checks both Google Sheets and the expected_flight_cargos DB table.
    """
    sheets_result = await get_cached_sheets_data(client.client_code, redis)
    sheets_matches: list[dict] = (
        sheets_result.get("matches", []) if sheets_result.get("found") else []
    )

    # Also discover flights from the expected_flight_cargos DB table
    db_flight_names = await ExpectedFlightCargoDAO.get_distinct_flights_for_client(
        session, client.active_codes
    )

    # Merge: Sheets first (preserve order), then DB-only flights
    seen_keys: set[str] = set()
    merged_flight_names: list[str] = []
    for match in sheets_matches:
        key = match["flight_name"].strip().upper()
        if key not in seen_keys:
            seen_keys.add(key)
            merged_flight_names.append(match["flight_name"])
    for flight_name in db_flight_names:
        key = flight_name.strip().upper()
        if key not in seen_keys:
            seen_keys.add(key)
            merged_flight_names.append(flight_name)

    paid_flights: list[FlightItem] = []

    for flight_name in merged_flight_names:
        is_paid = await ClientTransactionDAO.check_payment_exists(
            session=session,
            client_code=client.active_codes,
            reys=flight_name,
        )
        if is_paid:
            paid_flights.append(FlightItem(flight_name=flight_name))

    return PaidFlightsResponse(flights=paid_flights)


@router.post("/calculate-uzpost", response_model=CalculateUzpostResponse)
async def calculate_uzpost(
    body: CalculateUzpostRequest,
    client=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    Calculate UzPost delivery details: weight, price, wallet balance, card info.

    Returns a warning (with no card info) if total weight exceeds 20 kg.
    """
    total_weight = 0.0
    for flight_name in body.flight_names:
        weight = await calculate_total_weight(session, flight_name, client.active_codes)
        total_weight += weight

    price_per_kg = 18000 if client.region in special_regions else 15000
    total_amount = calculate_price(total_weight, client.region)

    # Weight limit warning
    if total_weight > 20:
        return CalculateUzpostResponse(
            total_weight=round(total_weight, 2),
            price_per_kg=price_per_kg,
            total_amount=total_amount,
            wallet_balance=0,
            card=None,
            warning=(
                f"Umumiy og'irlik {total_weight:.2f} kg — 20 kg dan oshmoqda. "
                "Iltimos, reyslarni kamaytirib qaytadan urinib ko'ring."
            ),
        )

    wallet_balance = (
        await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
            session, client.active_codes
        )
    )

    payment_card_service = PaymentCardService()
    card = await payment_card_service.get_random_active_card(session)

    card_info = None
    if card:
        card_info = CardInfo(card_number=card.card_number, card_owner=card.full_name)

    return CalculateUzpostResponse(
        total_weight=round(total_weight, 2),
        price_per_kg=price_per_kg,
        total_amount=total_amount,
        wallet_balance=wallet_balance,
        card=card_info,
    )


async def _check_rate_limit(session: AsyncSession, client_id: int, requesting_flights: list[str]):
    """Check if the user requested any of these flights within the last hour."""
    recent_requests = await DeliveryRequestDAO.get_recent_requests_by_client(session, client_id, hours=1)

    for req in recent_requests:
        if not req.flight_names:
            continue
        with contextlib.suppress(json.JSONDecodeError):
            req_flights = json.loads(req.flight_names)
            if overlap := set(requesting_flights).intersection(
                set(req_flights)
            ):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Siz {', '.join(overlap)} reys(lar)i uchun so'nggi 1 soat ichida zayavka yuborgansiz. Iltimos biroz kuting."
                )


@router.post("/request/standard", response_model=DeliverySuccessResponse)
async def submit_standard_delivery(
    body: StandardDeliveryRequest,
    client=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    Submit a Yandex, AKB, or BTS delivery request.

    Validates the client profile, creates the delivery record,
    and notifies the corresponding admin Telegram channel.
    """
    _validate_profile(client)
    await _check_rate_limit(session, client.id, body.flight_names)

    delivery_request = await DeliveryRequestDAO.create(
        session=session,
        client_id=client.id,
        client_code=client.client_code,
        telegram_id=client.telegram_id,
        delivery_type=body.delivery_type,
        flight_names=json.dumps(body.flight_names, ensure_ascii=False),
        full_name=client.full_name,
        phone=client.phone,
        region=client.region,
        address=client.address,
    )
    await session.commit()

    # Send to the delivery-type-specific admin channel
    channel_attr = f"{body.delivery_type.upper()}_DELIVERY_REQUEST_CHANNEL_ID"
    if admin_group_id := getattr(config.telegram, channel_attr, None):
        admin_text = _build_admin_text(
            delivery_request.id, client, body.delivery_type, body.flight_names
        )
        try:
            await _send_admin_notification(
                admin_group_id, admin_text, delivery_request.id
            )
        except Exception as e:
            logger.error(f"Failed to send admin notification: {e}")

    return DeliverySuccessResponse(
        message="Zayavka muvaffaqiyatli yuborildi!",
        delivery_request_id=delivery_request.id,
    )


@router.post("/request/uzpost", response_model=DeliverySuccessResponse)
async def submit_uzpost_delivery(
    flight_names: str = Form(
        ..., description='JSON string of flight names, e.g. ["MC-1044"]'
    ),
    wallet_used: float = Form(0.0, description="Amount of wallet balance applied"),
    receipt_file: Optional[UploadFile] = File(
        None, description="Payment receipt image/document"
    ),
    client=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """
    Submit an UzPost delivery request with optional receipt upload and wallet usage.

    Accepts multipart/form-data. If wallet_used covers the full amount, receipt_file
    can be omitted.
    """
    _validate_profile(client)

    # Parse flight names
    try:
        flight_names_list: list[str] = json.loads(flight_names)
        if not flight_names_list:
            raise ValueError
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="flight_names must be a non-empty JSON array string.",
        ) from e

    await _check_rate_limit(session, client.id, flight_names_list)

    # Validate wallet usage
    if wallet_used > 0:
        actual_balance = (
            await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
                session, client.active_codes
            )
        )
        if wallet_used > actual_balance:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"wallet_used ({wallet_used}) exceeds actual wallet balance ({actual_balance}).",
            )

    # Store wallet_used in Redis for admin approval flow
    primary_flight = flight_names_list[0] if flight_names_list else "UZPOST"
    if wallet_used > 0:
        wallet_cache_key = (
            f"wallet_used:{client.telegram_id}:{client.client_code}:{primary_flight}"
        )
        await redis.setex(wallet_cache_key, 86400, str(wallet_used))

    # Prepare receipt file (read bytes but don't send yet)
    tg_file = None
    admin_group_id = config.telegram.UZPOST_TOLOVLARNI_TASDIQLASH_GROUP_ID

    if receipt_file and receipt_file.filename:
        from aiogram.types import BufferedInputFile

        file_bytes = await receipt_file.read()
        tg_file = BufferedInputFile(file_bytes, filename=receipt_file.filename)

    # Create delivery request record first (to get ID for keyboard callback data)
    delivery_request = await DeliveryRequestDAO.create(
        session=session,
        client_id=client.id,
        client_code=client.client_code,
        telegram_id=client.telegram_id,
        delivery_type="uzpost",
        flight_names=json.dumps(flight_names_list, ensure_ascii=False),
        full_name=client.full_name,
        phone=client.phone,
        region=client.region,
        address=client.address,
        prepayment_receipt_file_id=None,
    )
    await session.commit()

    # Build admin notification text
    admin_text = _build_admin_text(
        delivery_request.id, client, "uzpost", flight_names_list
    )

    # Append wallet info
    if wallet_used > 0:
        total_weight = 0.0
        for fn in flight_names_list:
            total_weight += await calculate_total_weight(
                session, fn, client.client_code
            )
        total_amount = calculate_price(total_weight, client.region)
        final_payable = max(total_amount - wallet_used, 0)

        admin_text += (
            f"\n\n💰 Hamyondan: {wallet_used:,.0f} so'm"
            f"\n💵 Qo'shimcha to'lov: {final_payable:,.0f} so'm"
        )
        if final_payable <= 0:
            admin_text += "\n⚠️ Faqat hamyon hisobidan to'lov"

    # Send single Telegram message: document+caption+keyboard or text+keyboard
    try:
        msg = await _send_admin_notification(
            chat_id=admin_group_id,
            text=admin_text,
            delivery_request_id=delivery_request.id,
            document=tg_file,
        )

        # Backfill file_id from the sent message if a document was attached
        if tg_file is not None and msg and msg.document:
            delivery_request.prepayment_receipt_file_id = msg.document.file_id
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to send admin notification: {e}")
        if tg_file is not None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload receipt file.",
            ) from e

    return DeliverySuccessResponse(
        message="Zayavka muvaffaqiyatli yuborildi!",
        delivery_request_id=delivery_request.id,
    )
