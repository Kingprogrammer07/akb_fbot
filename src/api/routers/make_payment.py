"""
Make Payment API Router.

Converts the Telegram bot make_payment.py flow into stateless REST endpoints.
The frontend handles the multi-step payment flow; this API exposes:
  1. GET  /available-flights         — list flights with pending payments
  2. GET  /flight-details/{flight}   — full calculation for one flight
  3. POST /submit/wallet-only        — pay entirely from wallet
  4. POST /submit/cash               — submit cash payment request
  5. POST /submit/online             — submit online payment with receipt file
"""

import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user, get_redis, get_translator
from src.api.schemas.make_payment import (
    AvailableFlightItem,
    AvailableFlightsResponse,
    CashPaymentRequest,
    FlightPaymentDetailsResponse,
    PaymentSubmissionResponse,
    WalletOnlyPaymentRequest,
)
from src.bot.bot_instance import bot
from src.bot.handlers.admin.payment_approval import build_admin_payment_message
from src.bot.utils.currency_cache import convert_to_uzs
from src.bot.utils.sheets_cache import get_client_sheets_data
from src.config import config
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.expected_cargo import ExpectedFlightCargoDAO
from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.database.models.client import Client
from src.infrastructure.services import PaymentCardService
from src.infrastructure.tools.image_optimizer import optimize_image_to_webp
from src.infrastructure.tools.money_utils import parse_money
from src.infrastructure.tools.s3_manager import s3_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


# ============================================================================
# Helpers (ported from bot handler)
# ============================================================================


async def _calculate_flight_payment(
    session: AsyncSession,
    flight_name: str,
    client_code: str | list[str],
    redis: Redis,
) -> Optional[dict]:
    """
    Calculate payment details for a flight.

    Returns dict with total_weight, price_per_kg_usd, price_per_kg_uzs,
    total_payment, track_codes, extra_charge — or None if no sent cargo found.
    """
    cargos = await FlightCargoDAO.get_by_client(session, flight_name, client_code)
    sent_cargos = [c for c in cargos if c.is_sent_web]

    if not sent_cargos:
        return None

    # Track codes: Google Sheets first, then fall back to expected_flight_cargos DB
    track_codes: list[str] = []
    try:
        from src.bot.utils.google_sheets_checker import GoogleSheetsChecker

        checker = GoogleSheetsChecker(
            spreadsheet_id=config.google_sheets.SHEETS_ID,
            api_key=config.google_sheets.API_KEY,
            last_n_sheets=5,
        )
        track_codes = await checker.get_track_codes_by_flight_and_client(
            flight_name, client_code
        )
    except Exception as e:
        await session.rollback()
        logger.warning(f"Failed to get track codes from Google Sheets: {e}")

    # Fallback: try expected_flight_cargos DB when Sheets returned nothing
    if not track_codes:
        codes = client_code if isinstance(client_code, list) else [client_code]
        for code in codes:
            try:
                db_codes = await ExpectedFlightCargoDAO.get_track_codes_by_flight_and_client(
                    session, flight_name, code
                )
                if db_codes:
                    track_codes = db_codes
                    break
            except Exception as e:
                logger.warning(
                    "Failed to get track codes from expected_flight_cargos "
                    "(flight=%s, code=%s): %s",
                    flight_name, code, e,
                )

    # Extra charge from static_data
    static_data = await StaticDataDAO.get_first(session)
    extra_charge = float(static_data.extra_charge or 0) if static_data else 0.0

    total_weight = sum(float(c.weight_kg or 0) for c in sent_cargos)
    price_per_kg_usd = float(sent_cargos[0].price_per_kg or 0)
    price_per_kg_uzs = await convert_to_uzs(price_per_kg_usd, redis, session)

    total_payment = (total_weight * price_per_kg_uzs) + extra_charge

    return {
        "total_weight": total_weight,
        "price_per_kg_usd": price_per_kg_usd,
        "price_per_kg_uzs": price_per_kg_uzs,
        "extra_charge": extra_charge,
        "total_payment": total_payment,
        "track_codes": track_codes,
        "has_cargos": True,
    }


def _build_admin_keyboard(
    _: callable,
    client_code: str,
    flight_name: str,
    *,
    is_cash: bool = False,
) -> InlineKeyboardBuilder:
    """Build the inline keyboard sent to the admin approval group."""
    builder = InlineKeyboardBuilder()

    if is_cash:
        builder.row(
            InlineKeyboardButton(
                text=_("btn-cash-payment-confirmed"),
                callback_data=f"cash_payment_confirmed:{client_code}:{flight_name}",
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text=_("btn-approve-payment"),
                callback_data=f"approve_payment:{client_code}:{flight_name}",
            )
        )
        builder.row(
            InlineKeyboardButton(
                text=_("btn-reject-payment"),
                callback_data=f"reject_payment:{client_code}",
            )
        )
        builder.row(
            InlineKeyboardButton(
                text=_("btn-reject-with-comment"),
                callback_data=f"reject_payment_comment:{client_code}",
            )
        )

    return builder


# ============================================================================
# 1. GET /available-flights
# ============================================================================


@router.get(
    "/available-flights",
    response_model=AvailableFlightsResponse,
    summary="List flights with pending payments",
    description=(
        "Returns all flights that still require payment for the authenticated client. "
        "Flights that are fully paid are excluded."
    ),
)
async def get_available_flights(
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator),
):
    """Replaces the Telegram ``make_payment_handler``."""
    if not current_user.active_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no client code assigned",
        )

    # Discover flights from Google Sheets and expected_flight_cargos DB, then merge
    sheets_result = await get_client_sheets_data(current_user.active_codes, redis)
    sheets_matches: list[dict] = sheets_result.get("matches", []) if sheets_result.get("found") else []

    db_flight_names = await ExpectedFlightCargoDAO.get_distinct_flights_for_client(
        session, current_user.active_codes
    )

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

    if not merged_flight_names:
        return AvailableFlightsResponse(flights=[], count=0)

    available: list[AvailableFlightItem] = []

    for flight_name in merged_flight_names:
        # Check existing transaction
        existing_tx = await ClientTransactionDAO.get_by_client_code_flight(
            session, current_user.active_codes, flight_name
        )

        is_fully_paid = existing_tx and existing_tx.payment_status == "paid"
        if is_fully_paid:
            continue

        # Calculate payment from database
        payment_data = await _calculate_flight_payment(
            session, flight_name, current_user.active_codes, redis
        )

        if existing_tx and existing_tx.payment_status == "partial":
            remaining = (
                float(existing_tx.remaining_amount)
                if isinstance(existing_tx.remaining_amount, (int, float))
                else parse_money(str(existing_tx.remaining_amount))
            )
            available.append(
                AvailableFlightItem(
                    flight_name=flight_name,
                    total_payment=payment_data["total_payment"]
                    if payment_data
                    else None,
                    payment_status="partial",
                    remaining_amount=remaining,
                )
            )
        else:
            available.append(
                AvailableFlightItem(
                    flight_name=flight_name,
                    total_payment=payment_data["total_payment"]
                    if payment_data
                    else None,
                    payment_status="unpaid",
                    remaining_amount=None,
                )
            )

    return AvailableFlightsResponse(flights=available, count=len(available))


# ============================================================================
# 2. GET /flight-details/{flight_name}
# ============================================================================


@router.get(
    "/flight-details/{flight_name}",
    response_model=FlightPaymentDetailsResponse,
    summary="Get payment details for a flight",
    description=(
        "Returns the full payment calculation for a specific flight including "
        "weight, track codes, card info, wallet balance, and partial-payment eligibility."
    ),
)
async def get_flight_details(
    flight_name: str,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator),
):
    """Replaces ``payment_flight_selected`` + ``payment_type_*_selected``."""
    if not current_user.active_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no client code assigned",
        )

    payment_data = await _calculate_flight_payment(
        session, flight_name, current_user.active_codes, redis
    )

    if not payment_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No sent cargo found for this flight. "
                "The admin may not have sent the photo report yet."
            ),
        )

    # Wallet balance
    wallet_balance = (
        await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
            session, current_user.active_codes
        )
    )

    # Check existing partial payment
    existing_tx = await ClientTransactionDAO.get_by_client_code_flight(
        session, current_user.active_codes, flight_name
    )

    has_existing_partial = bool(existing_tx and existing_tx.payment_status == "partial")
    existing_paid: Optional[float] = None
    existing_remaining: Optional[float] = None

    if has_existing_partial:
        existing_paid = (
            float(existing_tx.paid_amount)
            if isinstance(existing_tx.paid_amount, (int, float))
            else parse_money(str(existing_tx.paid_amount))
        )
        existing_remaining = (
            float(existing_tx.remaining_amount)
            if isinstance(existing_tx.remaining_amount, (int, float))
            else parse_money(str(existing_tx.remaining_amount))
        )

    # Random active payment card
    card_number: Optional[str] = None
    card_owner: Optional[str] = None
    try:
        payment_card_service = PaymentCardService()
        card = await payment_card_service.get_random_active_card(session)
        if card:
            card_number = card.card_number
            card_owner = card.full_name
    except Exception as e:
        logger.warning(f"Failed to get payment card: {e}")

    total_payment = payment_data["total_payment"]

    return FlightPaymentDetailsResponse(
        flight_name=flight_name,
        client_code=current_user.primary_code,
        total_payment=total_payment,
        total_weight=payment_data["total_weight"],
        price_per_kg_usd=payment_data["price_per_kg_usd"],
        price_per_kg_uzs=payment_data["price_per_kg_uzs"],
        extra_charge=payment_data["extra_charge"],
        track_codes=payment_data["track_codes"],
        wallet_balance=wallet_balance,
        partial_allowed=total_payment >= 25000,
        has_existing_partial=has_existing_partial,
        existing_paid_amount=existing_paid,
        existing_remaining_amount=existing_remaining,
        card_number=card_number,
        card_owner=card_owner,
    )


# ============================================================================
# 3. POST /submit/wallet-only
# ============================================================================


@router.post(
    "/submit/wallet-only",
    response_model=PaymentSubmissionResponse,
    summary="Pay fully from wallet balance",
    description="Deducts the full amount from the client wallet and sends approval request to admin.",
)
async def submit_wallet_only(
    body: WalletOnlyPaymentRequest,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator),
):
    """Replaces ``payment_wallet_only_handler``."""
    if not current_user.active_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no client code assigned",
        )

    # Verify wallet balance
    wallet_balance = (
        await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
            session, current_user.active_codes
        )
    )

    if wallet_balance < body.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient wallet balance ({wallet_balance:,.2f} UZS)",
        )

    # Calculate payment to get track codes & weight
    payment_data = await _calculate_flight_payment(
        session, body.flight_name, current_user.active_codes, redis
    )

    # Validate amount against actual payment
    if payment_data:
        total_payment = payment_data["total_payment"]

        # For partial / full_remaining, also check existing tx
        if body.payment_mode == "full_remaining":
            existing_tx = await ClientTransactionDAO.get_by_client_code_flight(
                session, current_user.active_codes, body.flight_name
            )
            if not existing_tx or existing_tx.payment_status != "partial":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No existing partial payment found for full_remaining mode",
                )

    track_codes = payment_data.get("track_codes", []) if payment_data else []
    vazn = f"{payment_data['total_weight']:.2f}" if payment_data else "N/A"
    total_payment_value = payment_data["total_payment"] if payment_data else body.amount

    wallet_used = body.amount

    # Cache wallet info in Redis for admin approval
    wallet_cache_key = f"wallet_used:{current_user.primary_code}:{body.flight_name}"
    await redis.setex(wallet_cache_key, 86400, str(wallet_used))

    cache_mode_key = f"payment_mode:{current_user.primary_code}:{body.flight_name}"
    await redis.setex(cache_mode_key, 86400, "wallet_only")

    # Build admin notification
    caption = build_admin_payment_message(
        _=_,
        client_code=current_user.primary_code,
        worksheet=body.flight_name,
        payment_provider="wallet",
        payment_status="paid",
        summa=float(total_payment_value),
        full_name=current_user.full_name or "N/A",
        phone=current_user.phone or "N/A",
        telegram_id=str(current_user.telegram_id),
        vazn=vazn,
        track_codes=track_codes,
        wallet_used=wallet_used,
        final_payable=0,
    )

    keyboard = _build_admin_keyboard(_, current_user.primary_code, body.flight_name)
    group_id = config.telegram.TOLOVLARNI_TASDIQLASH_GROUP_ID

    try:
        await bot.send_message(
            chat_id=group_id,
            text=caption,
            reply_markup=keyboard.as_markup(),
        )
    except Exception as e:
        logger.error(f"Failed to send wallet-only payment to admin group: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send notification to admin group",
        )

    return PaymentSubmissionResponse(
        message="Wallet payment submitted for admin approval",
        flight_name=body.flight_name,
        amount=wallet_used,
        wallet_used=wallet_used,
        payment_mode=body.payment_mode,
    )


# ============================================================================
# 4. POST /submit/cash
# ============================================================================


@router.post(
    "/submit/cash",
    response_model=PaymentSubmissionResponse,
    summary="Submit cash payment request",
    description="Records a cash payment intent and sends approval request to admin.",
)
async def submit_cash(
    body: CashPaymentRequest,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator),
):
    """Replaces ``cash_payment_confirmed``."""
    if not current_user.active_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no client code assigned",
        )

    # Calculate payment
    payment_data = await _calculate_flight_payment(
        session, body.flight_name, current_user.active_codes, redis
    )

    if not payment_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No sent cargo found for this flight",
        )

    total_payment = payment_data["total_payment"]
    track_codes = payment_data.get("track_codes", [])
    vazn = f"{payment_data['total_weight']:.2f}"

    # Validate wallet usage
    wallet_used = body.wallet_used
    if wallet_used > 0:
        wallet_balance = (
            await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
                session, current_user.active_codes
            )
        )
        if wallet_used > wallet_balance:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"wallet_used ({wallet_used:,.2f}) exceeds balance ({wallet_balance:,.2f})",
            )

        # Cache wallet info for admin approval — key must match bot handler lookup format
        wallet_cache_key = f"wallet_used:{current_user.primary_code}:{body.flight_name}"
        await redis.setex(wallet_cache_key, 86400, str(wallet_used))

    # Cache payment mode so _process_approved_payment resolves provider="cash" correctly
    await redis.setex(
        f"payment_mode:{current_user.primary_code}:{body.flight_name}", 86400, "cash"
    )

    final_payable = total_payment - wallet_used

    # Build admin message
    caption = build_admin_payment_message(
        _=_,
        client_code=current_user.primary_code,
        worksheet=body.flight_name,
        payment_provider="cash",
        payment_status="paid",
        summa=float(total_payment),
        full_name=current_user.full_name or "N/A",
        phone=current_user.phone or "N/A",
        telegram_id=str(current_user.telegram_id),
        vazn=vazn,
        track_codes=track_codes,
        wallet_used=wallet_used,
        final_payable=final_payable if wallet_used > 0 else None,
    )

    keyboard = _build_admin_keyboard(
        _, current_user.primary_code, body.flight_name, is_cash=True
    )
    group_id = config.telegram.TOLOVLARNI_TASDIQLASH_GROUP_ID

    try:
        await bot.send_message(
            chat_id=group_id,
            text=caption,
            reply_markup=keyboard.as_markup(),
        )
    except Exception as e:
        logger.error(f"Failed to send cash payment to admin group: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send notification to admin group",
        )

    return PaymentSubmissionResponse(
        message="Cash payment submitted for admin approval",
        flight_name=body.flight_name,
        amount=total_payment,
        wallet_used=wallet_used,
        payment_mode="cash",
    )


# ============================================================================
# 5. POST /submit/online
# ============================================================================


@router.post(
    "/submit/online",
    response_model=PaymentSubmissionResponse,
    summary="Submit online payment with receipt",
    description=(
        "Upload a receipt image/document and submit online payment for admin approval. "
        "Supports full, partial, and full_remaining payment modes."
    ),
)
async def submit_online(
    flight_name: str = Form(...),
    payment_mode: str = Form("full"),
    paid_amount: float = Form(..., gt=0),
    wallet_used: float = Form(0, ge=0),
    receipt_file: UploadFile = File(..., description="Payment receipt (image or PDF)"),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator),
):
    """Replaces ``payment_proof_received`` + ``partial_amount_received`` + ``pay_full``."""
    if not current_user.active_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no client code assigned",
        )

    if payment_mode not in ("full", "partial", "full_remaining"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="payment_mode must be one of: full, partial, full_remaining",
        )

    # Calculate flight payment
    payment_data = await _calculate_flight_payment(
        session, flight_name, current_user.active_codes, redis
    )

    if not payment_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No sent cargo found for this flight",
        )

    total_payment = payment_data["total_payment"]
    track_codes = payment_data.get("track_codes", [])
    vazn = f"{payment_data['total_weight']:.2f}"

    # ---- Amount validations ----
    remaining_for_partial = total_payment
    existing_tx = await ClientTransactionDAO.get_by_client_code_flight(
        session, current_user.active_codes, flight_name
    )

    if payment_mode == "full_remaining":
        if not existing_tx or existing_tx.payment_status != "partial":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No existing partial payment found for full_remaining mode",
            )
        remaining_for_partial = (
            float(existing_tx.remaining_amount)
            if isinstance(existing_tx.remaining_amount, (int, float))
            else parse_money(str(existing_tx.remaining_amount))
        )

    elif payment_mode == "partial":
        if existing_tx and existing_tx.payment_status == "partial":
            remaining_for_partial = (
                float(existing_tx.remaining_amount)
                if isinstance(existing_tx.remaining_amount, (int, float))
                else parse_money(str(existing_tx.remaining_amount))
            )
        if paid_amount < 1000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Minimum partial payment is 1,000 UZS",
            )
        if paid_amount > remaining_for_partial:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"paid_amount ({paid_amount:,.2f}) exceeds remaining ({remaining_for_partial:,.2f})",
            )

    # Validate wallet usage
    if wallet_used > 0:
        wallet_balance = (
            await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
                session, current_user.active_codes
            )
        )
        if wallet_used > wallet_balance:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"wallet_used ({wallet_used:,.2f}) exceeds balance ({wallet_balance:,.2f})",
            )

    # ---- Read receipt file ----
    file_content = await receipt_file.read()
    if not file_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty receipt file",
        )

    # ---- Optimize and Upload to S3 ----
    s3_content_type = receipt_file.content_type or "application/octet-stream"
    s3_filename = receipt_file.filename or "receipt.jpg"
    ext = s3_filename.rsplit(".", 1)[-1] if "." in s3_filename else "jpg"

    upload_content = file_content
    if s3_content_type.startswith("image/"):
        try:
            upload_content = await optimize_image_to_webp(file_content)
            s3_content_type = "image/webp"
            ext = "webp"
        except Exception:
            pass  # Fallback to original if optimization fails

    try:
        s3_key = await s3_manager.upload_file(
            file_content=upload_content,
            file_name=f"receipt_{flight_name}.{ext}",
            telegram_id=current_user.telegram_id,
            client_code=current_user.primary_code,
            base_folder="payment-receipts",
            sub_folder="",
            content_type=s3_content_type,
        )
    except Exception as e:
        logger.error(f"Failed to upload API payment receipt to S3: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload receipt to storage.",
        )

    # ---- Determine payment status ----
    is_partial = payment_mode in ("partial", "full_remaining")
    payment_status_label = "partial" if is_partial else "paid"

    # Calculate amounts for partial payments
    partial_paid_amount: Optional[float] = None
    partial_remaining: Optional[float] = None
    total_amount_for_msg: Optional[float] = None

    if is_partial:
        total_amount_for_msg = total_payment
        partial_paid_amount = paid_amount
        # FIXED: Subtract paid_amount from the current remaining balance, not the original total
        partial_remaining = remaining_for_partial - paid_amount

    final_payable = paid_amount - wallet_used if wallet_used > 0 else None

    # ---- Build admin caption ----
    caption = build_admin_payment_message(
        _=_,
        client_code=current_user.primary_code,
        worksheet=flight_name,
        payment_provider="online",
        payment_status=payment_status_label,
        summa=float(total_payment),
        full_name=current_user.full_name or "N/A",
        phone=current_user.phone or "N/A",
        telegram_id=str(current_user.telegram_id),
        vazn=vazn,
        track_codes=track_codes,
        paid_amount=partial_paid_amount,
        remaining_amount=partial_remaining,
        total_amount=total_amount_for_msg,
        deadline=None,
        wallet_used=wallet_used,
        final_payable=final_payable,
    )

    keyboard = _build_admin_keyboard(_, current_user.primary_code, flight_name)
    group_id = config.telegram.TOLOVLARNI_TASDIQLASH_GROUP_ID

    # ---- Send receipt to Telegram admin group ----
    content_type = receipt_file.content_type or ""
    filename = receipt_file.filename or "receipt"
    sent_message = None

    try:
        if content_type.startswith("image/"):
            input_file = BufferedInputFile(file_content, filename=filename)
            sent_message = await bot.send_photo(
                chat_id=group_id,
                photo=input_file,
                caption=caption,
                reply_markup=keyboard.as_markup(),
            )
        else:
            input_file = BufferedInputFile(file_content, filename=filename)
            sent_message = await bot.send_document(
                chat_id=group_id,
                document=input_file,
                caption=caption,
                reply_markup=keyboard.as_markup(),
            )
    except Exception as e:
        logger.error(f"Failed to send online payment receipt to admin group: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send receipt to admin group",
        )

    # ---- Cache S3 key in Redis (instead of Telegram file_id) ----
    cache_key = f"payment_receipt:{current_user.primary_code}:{flight_name}"
    await redis.setex(cache_key, 86400, s3_key)

    # Payment mode cache
    cache_mode_key = f"payment_mode:{current_user.primary_code}:{flight_name}"
    await redis.setex(cache_mode_key, 86400, payment_mode)

    # Wallet cache
    if wallet_used > 0:
        wallet_cache_key = f"wallet_used:{current_user.primary_code}:{flight_name}"
        await redis.setex(wallet_cache_key, 86400, str(wallet_used))

    # Partial amount cache
    if payment_mode in ("partial", "full_remaining"):
        cache_amount_key = f"payment_amount:{current_user.primary_code}:{flight_name}"
        await redis.setex(cache_amount_key, 86400, str(paid_amount))

    return PaymentSubmissionResponse(
        message="Payment receipt submitted for admin approval",
        flight_name=flight_name,
        amount=paid_amount,
        wallet_used=wallet_used,
        payment_mode=payment_mode,
    )
