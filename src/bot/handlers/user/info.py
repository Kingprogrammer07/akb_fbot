"""Information handlers."""

import json
import logging
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.bot.filters.is_private_chat import IsPrivate
from src.bot.filters.is_logged_in import ClientExists, IsRegistered, IsLoggedIn
from src.bot.utils.decorators import handle_errors
from src.bot.utils.sheets_cache import get_client_sheets_data
from src.bot.utils.currency_cache import convert_to_uzs
from src.infrastructure.services import ClientService
from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.client_payment_event import ClientPaymentEventDAO
from src.infrastructure.tools.passport_image_resolver import _is_s3_key
from src.infrastructure.tools.s3_manager import s3_manager
from src.config import config

logger = logging.getLogger(__name__)

info_router = Router(name="info")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _safe_answer(callback: CallbackQuery, text: str = "", show_alert: bool = False):
    from src.bot.handlers.admin.client_verification import safe_answer_callback
    await safe_answer_callback(callback, text, show_alert)


def _build_flight_keyboard(
    matches: list[dict],
    payment_map: dict,
    _: callable,
) -> InlineKeyboardBuilder:
    """Build the flights list inline keyboard."""
    builder = InlineKeyboardBuilder()
    for match in matches:
        flight_name = match["flight_name"]
        payment_data = payment_map.get(flight_name)
        if payment_data:
            button_text = f"✈️ {flight_name} - {payment_data['total_payment']:,.2f} so'm"
        else:
            button_text = f"✈️ {flight_name} - {_('info-report-not-sent')}"
        builder.button(
            text=button_text,
            callback_data=f"info_flight:{flight_name}:{match['row_number']}",
        )
    builder.button(text=_("btn-refresh"), callback_data="refresh_info_flights")
    builder.adjust(1)
    return builder


async def _build_payment_map(
    session: AsyncSession,
    matches: list[dict],
    active_codes,
    redis: Redis,
) -> dict:
    """Calculate payment data for all flights at once, return {flight_name: payment_data}."""
    result = {}
    for match in matches:
        flight_name = match["flight_name"]
        result[flight_name] = await calculate_flight_payment(
            session, flight_name, active_codes, redis
        )
    return result


async def _resolve_photo_ref(ref: str, expires_in: int = 3600) -> str:
    """
    Return a usable photo reference.
    - If ref is an S3 key → generate presigned URL
    - Otherwise → return as-is (Telegram file_id)
    """
    if _is_s3_key(ref):
        try:
            return await s3_manager.generate_presigned_url(ref, expires_in=expires_in)
        except Exception as e:
            logger.warning(f"Failed to generate presigned URL for {ref}: {e}")
            return ref  # fallback to raw key (will likely fail, but graceful)
    return ref


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------

def format_payment_breakdown(breakdown: dict, _: callable) -> str:
    """
    Format payment breakdown for display.

    Example output:
        💳 To'lovlar:
         • Click: 900,000.00 so'm
         • Naqd: 100,000.00 so'm
        📊 Jami: 1,000,000.00 so'm
    """
    if not breakdown:
        return ""

    click_amount = breakdown.get("click", 0) or 0
    payme_amount = breakdown.get("payme", 0) or 0
    cash_amount  = breakdown.get("cash", 0) or 0
    total = click_amount + payme_amount + cash_amount

    if total <= 0:
        return ""

    lines = [_("info-payment-breakdown-header")]
    if click_amount > 0:
        lines.append(f" • Click: {click_amount:,.2f} so'm")
    if payme_amount > 0:
        lines.append(f" • Payme: {payme_amount:,.2f} so'm")
    if cash_amount > 0:
        lines.append(_("info-payment-breakdown-cash", amount=f"{cash_amount:,.2f}"))
    lines.append(_("info-payment-breakdown-total", total=f"{total:,.2f}"))

    return "\n".join(lines)


async def calculate_flight_payment(
    session: AsyncSession,
    flight_name: str,
    client_code: str | list[str],
    redis: Redis,
) -> dict | None:
    """
    Calculate payment details for a flight.

    Returns dict with total_weight, price_per_kg_usd, price_per_kg_uzs,
    total_payment, track_codes, extra_charge — or None if no sent cargo found.
    """
    cargos = await FlightCargoDAO.get_by_client(session, flight_name, client_code)
    sent_cargos = [c for c in cargos if c.is_sent]
    if not sent_cargos:
        return None

    track_codes = []
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
        logger.warning(
            f"Failed to get track codes from Google Sheets for {client_code}/{flight_name}: {e}"
        )

    static_data  = await StaticDataDAO.get_first(session)
    extra_charge = float(static_data.extra_charge or 0) if static_data else 0.0

    total_weight     = sum(float(c.weight_kg or 0) for c in sent_cargos)
    price_per_kg_usd = float(sent_cargos[0].price_per_kg or 0)
    price_per_kg_uzs = await convert_to_uzs(price_per_kg_usd, redis, session)
    total_payment    = (total_weight * price_per_kg_uzs) + extra_charge

    return {
        "total_weight":     total_weight,
        "price_per_kg_usd": price_per_kg_usd,
        "price_per_kg_uzs": price_per_kg_uzs,
        "extra_charge":     extra_charge,
        "total_payment":    total_payment,
        "track_codes":      track_codes,
        "has_cargos":       True,
        "cargo_ids":        [c.id for c in sent_cargos],
    }


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@info_router.message(
    IsPrivate(),
    ClientExists(),
    IsRegistered(),
    IsLoggedIn(),
    F.text.in_(["📊 Ma'lumotlarni ko'rish", "📊 Просмотр информации"]),
)
@handle_errors
async def info_handler(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    redis: Redis,
    state: FSMContext,
):
    """Show user's flights information from Google Sheets."""
    await state.clear()

    client = await client_service.get_client(message.from_user.id, session)
    if not client:
        await message.answer(_("error-occurred"))
        return

    result = await get_client_sheets_data(client.active_codes, redis)
    if not result["found"]:
        await message.answer(_("info-no-orders"))
        return

    payment_map = await _build_payment_map(session, result["matches"], client.active_codes, redis)
    builder     = _build_flight_keyboard(result["matches"], payment_map, _)

    await message.answer(_("info-flights-list"), reply_markup=builder.as_markup())


@info_router.callback_query(F.data.startswith("info_flight:"))
@handle_errors
async def flight_details_handler(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service,
    redis: Redis,
):
    """Show flight details when user selects a flight."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await _safe_answer(callback, _("error-occurred"), show_alert=True)
        return

    flight_name = parts[1]
    row_number  = int(parts[2])

    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await _safe_answer(callback, _("error-occurred"), show_alert=True)
        return

    payment_data = await calculate_flight_payment(
        session, flight_name, client.active_codes, redis
    )

    # No cargo yet — show "report not sent" message
    if not payment_data:
        result = await get_client_sheets_data(client.active_codes, redis)
        track_info = "N/A"
        if result["found"] and result["matches"]:
            codes = result["matches"][0].get("track_codes", [])
            track_info = "\n".join(f"• {c}" for c in codes) if codes else "N/A"

        await callback.message.edit_text(
            _(
                "info-report-not-sent-message",
                flight_name=flight_name,
                client_code=client.primary_code,
                track_codes=_("admin-leftover-column-track-code") + ": " + track_info,
            ),
            reply_markup=InlineKeyboardBuilder()
            .button(text=_("btn-back-to-flights"), callback_data="back_to_flights")
            .as_markup(),
        )
        await _safe_answer(callback)
        return

    trek_kodlari_text = (
        ", ".join(payment_data["track_codes"]) if payment_data["track_codes"] else "N/A"
    )

    transaction = await ClientTransactionDAO.get_by_client_code_flight_row(
        session, client.client_code, flight_name, row_number
    )

    is_paid    = bool(transaction and transaction.payment_status == "paid")
    is_partial = bool(transaction and transaction.payment_status == "partial")

    payment_status_text = (
        _("info-status-paid")    if is_paid
        else _("info-status-partial") if is_partial
        else _("info-status-unpaid")
    )

    payment_breakdown = {}
    if transaction and transaction.payment_status in ("paid", "partial"):
        payment_breakdown = await ClientPaymentEventDAO.get_payment_breakdown_by_transaction_id(
            session, transaction.id
        )

    # Build details text
    if is_partial:
        total_amount     = float(transaction.total_amount or payment_data["total_payment"])
        paid_amount      = float(transaction.paid_amount or 0)
        remaining_amount = float(transaction.remaining_amount or 0)
        deadline = (
            transaction.payment_deadline.strftime("%Y-%m-%d %H:%M")
            if transaction.payment_deadline else _("not-set")
        )
        details_text = _(
            "info-flight-details-partial",
            client_code=client.primary_code,
            worksheet=flight_name,
            total=f"{total_amount:,.2f}",
            paid=f"{paid_amount:,.2f}",
            remaining=f"{remaining_amount:,.2f}",
            deadline=deadline,
            vazn=f"{payment_data['total_weight']:.2f}",
            trek_kodlari=trek_kodlari_text,
        )
    else:
        details_text = _(
            "info-flight-details-with-status",
            client_code=client.primary_code,
            worksheet=flight_name,
            summa=f"{payment_data['total_payment']:,.2f}",
            vazn=f"{payment_data['total_weight']:.2f}",
            trek_kodlari=trek_kodlari_text,
            payment_status=payment_status_text,
        )

    breakdown_text = format_payment_breakdown(payment_breakdown, _)
    if breakdown_text:
        details_text += "\n\n" + breakdown_text

    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("btn-view-cargo-photos"),
        callback_data=f"view_cargo_photos:{flight_name}",
    )
    if not transaction or transaction.payment_status in ("partial", "pending"):
        builder.button(
            text=_("btn-make-payment-now"),
            callback_data=f"pay_flight:{flight_name}",
        )
    builder.button(text=_("btn-back-to-flights"), callback_data="back_to_flights")
    builder.adjust(1)

    await callback.message.edit_text(details_text, reply_markup=builder.as_markup())
    await _safe_answer(callback)


@info_router.callback_query(F.data == "back_to_flights")
@handle_errors
async def back_to_flights_callback(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    redis: Redis,
):
    """Go back to flights list."""
    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await _safe_answer(callback, _("error-occurred"), show_alert=True)
        return

    result = await get_client_sheets_data(client.active_codes, redis)
    if not result["found"]:
        await _safe_answer(callback, _("info-no-orders"), show_alert=True)
        return

    payment_map = await _build_payment_map(session, result["matches"], client.active_codes, redis)
    builder     = _build_flight_keyboard(result["matches"], payment_map, _)

    await callback.message.edit_text(_("info-flights-list"), reply_markup=builder.as_markup())
    await _safe_answer(callback)


@info_router.callback_query(F.data == "refresh_info_flights")
@handle_errors
async def refresh_info_flights_callback(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    redis: Redis,
):
    """Refresh flights list (clears cache first)."""
    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await _safe_answer(callback, _("error-occurred"), show_alert=True)
        return

    await redis.delete(f"sheets_data:{client.primary_code}")

    result = await get_client_sheets_data(client.active_codes, redis)
    if not result["found"]:
        await _safe_answer(callback, _("info-no-orders"), show_alert=True)
        return

    payment_map = await _build_payment_map(session, result["matches"], client.active_codes, redis)
    builder     = _build_flight_keyboard(result["matches"], payment_map, _)

    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

    await callback.message.answer(_("info-flights-list"), reply_markup=builder.as_markup())
    await _safe_answer(callback, _("info-flights-refreshed"))


@info_router.callback_query(F.data.startswith("view_cargo_photos:"))
@handle_errors
async def view_cargo_photos_handler(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
):
    """Show cargo photos for a specific flight.

    Priority:
      1. S3 key → presigned URL
      2. Telegram file_id → sent directly (fallback)
    """
    parts = callback.data.split(":")
    if len(parts) != 2:
        await _safe_answer(callback, _("error-occurred"), show_alert=True)
        return

    flight_name = parts[1]

    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await _safe_answer(callback, _("error-occurred"), show_alert=True)
        return

    cargos = await FlightCargoDAO.get_by_client(session, flight_name, client.active_codes)
    if not cargos:
        await _safe_answer(callback, _("info-no-cargo-photos"), show_alert=True)
        return

    await _safe_answer(callback)

    total_sent = 0

    for cargo in cargos:
        try:
            raw_ids: list = json.loads(cargo.photo_file_ids)
            if not raw_ids:
                continue

            # Resolve each ref: S3 key → presigned URL, file_id → as-is
            resolved = []
            for ref in raw_ids[:10]:
                resolved.append(await _resolve_photo_ref(ref))

            if len(resolved) > 1:
                await callback.message.answer_media_group(
                    [InputMediaPhoto(media=r) for r in resolved]
                )
            else:
                await callback.message.answer_photo(photo=resolved[0])

            total_sent += len(resolved)

        except Exception as e:
            await session.rollback()
            logger.error(f"Error sending cargo photos for {flight_name}: {e}")
            continue

    await callback.message.answer(
        _(
            "info-cargo-photos-summary",
            total=total_sent,
            flight_name=flight_name,
            client_code=client.primary_code,
        )
    )