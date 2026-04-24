"""Make payment handler."""

import logging
from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.bot.filters.is_private_chat import IsPrivate
from src.bot.filters.is_logged_in import ClientExists, IsRegistered, IsLoggedIn
from src.bot.keyboards.inline_kb.auth import auth_login_kb
from src.bot.utils.decorators import handle_errors
from src.bot.utils.sheets_cache import get_client_sheets_data
from src.bot.utils.currency_cache import convert_to_uzs
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.expected_cargo import ExpectedFlightCargoDAO
from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.services import (
    ClientService,
    PaymentCardService,
    ClientTransactionService,
)
from src.infrastructure.tools.money_utils import parse_money
from src.infrastructure.tools.s3_manager import s3_manager
from src.infrastructure.tools.image_optimizer import optimize_image_to_webp
from src.config import config


logger = logging.getLogger(__name__)

make_payment_router = Router(name="make_payment")


# ---------------------------------------------------------------------------
# FSM States
# ---------------------------------------------------------------------------

class PaymentStates(StatesGroup):
    waiting_for_payment_proof = State()
    waiting_for_cash_confirmation = State()
    waiting_for_partial_amount = State()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _get_client_safe(telegram_id: int, session: AsyncSession, client_service: ClientService):
    """Return client or None (with rollback on error)."""
    try:
        return await client_service.get_client(telegram_id, session)
    except Exception:
        await session.rollback()
        return None


async def _get_wallet_balance(session: AsyncSession, active_codes: str | list[str]) -> float:
    return await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
        session, active_codes
    )


async def _get_random_card(session: AsyncSession, callback_or_message, _: callable):
    """Return active card or answer with error and return None."""
    card = await PaymentCardService().get_random_active_card(session)
    if not card:
        if isinstance(callback_or_message, CallbackQuery):
            await callback_or_message.answer(_("payment-no-cards"), show_alert=True)
        else:
            await callback_or_message.answer(_("payment-no-cards"))
    return card


async def _get_existing_tx(session: AsyncSession, active_codes, flight_name: str):
    return await ClientTransactionDAO.get_by_client_code_flight(
        session, active_codes, flight_name
    )


def _parse_decimal(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return parse_money(str(value))


async def _safe_edit_text(callback: CallbackQuery, text: str, reply_markup=None):
    """Edit message text, silently ignore 'not modified' errors."""
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            logger.warning(f"Ignored 'message not modified' for {callback.data}")
            return
        raise


async def _cache_payment_meta(
    redis: Redis,
    client_code: str,
    worksheet: str,
    payment_mode: str,
    wallet_used: float = 0,
    partial_amount: float | None = None,
    s3_key: str | None = None,
    card_id: int | None = None,
):
    """Store all payment-related Redis keys in one place."""
    TTL = 86400
    if s3_key:
        await redis.setex(f"payment_receipt:{client_code}:{worksheet}", TTL, s3_key)
    await redis.setex(f"payment_mode:{client_code}:{worksheet}", TTL, payment_mode)
    if wallet_used > 0:
        await redis.setex(f"wallet_used:{client_code}:{worksheet}", TTL, str(wallet_used))
    if partial_amount is not None and payment_mode in ("partial", "full_remaining"):
        await redis.setex(f"payment_amount:{client_code}:{worksheet}", TTL, str(partial_amount))
    if card_id is not None:
        await redis.setex(f"payment_card_id:{client_code}:{worksheet}", TTL, str(card_id))


def _build_wallet_amounts(
    selected_amount: float,
    wallet_balance: float,
    use_wallet: bool,
) -> tuple[float, float]:
    """Return (wallet_used, final_payable_amount)."""
    if use_wallet and wallet_balance > 0:
        wallet_used = min(wallet_balance, selected_amount)
        return wallet_used, selected_amount - wallet_used
    return 0.0, selected_amount


def _resolve_selected_amount(data: dict, total_payment: float) -> float:
    payment_mode = data.get("payment_mode", "full")
    if payment_mode == "partial":
        return data.get("partial_amount", total_payment)
    if payment_mode == "full_remaining":
        return data.get("remaining_amount", total_payment)
    return total_payment


def _add_wallet_toggle_button(
    builder: InlineKeyboardBuilder,
    wallet_balance: float,
    use_wallet: bool,
    flight_name: str,
    _: callable,
):
    if wallet_balance > 0:
        label = _("btn-payment-wallet-enabled") if use_wallet else _("btn-payment-use-wallet")
        builder.button(text=label, callback_data=f"payment_wallet_toggle:{flight_name}")


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
    sent_cargos = [c for c in cargos if c.is_sent or c.is_sent_web]
    if not sent_cargos:
        return None

    track_codes: list[str] = []
    try:
        from src.bot.utils.google_sheets_checker import GoogleSheetsChecker

        checker = GoogleSheetsChecker(
            spreadsheet_id=config.google_sheets.SHEETS_ID,
            api_key=config.google_sheets.API_KEY,
            last_n_sheets=5,
        )
        track_codes = await checker.get_track_codes_by_flight_and_client(flight_name, client_code)
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


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@make_payment_router.message(
    IsPrivate(),
    ClientExists(),
    IsRegistered(),
    IsLoggedIn(),
    F.text.in_(["💳 To'lov qilish", "💳 Оплатить"]),
)
@handle_errors
async def make_payment_handler(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    redis: Redis,
    state: FSMContext,
):
    """Show available flights for payment."""
    await state.clear()

    client = await client_service.get_client(message.from_user.id, session)
    if not client:
        await message.answer(_("error-occurred"))
        return

    sheets_result = await get_client_sheets_data(client.active_codes, redis)
    sheets_matches: list[dict] = sheets_result.get("matches", []) if sheets_result.get("found") else []

    # Merge with flights from expected_flight_cargos DB so DB-only flights are also offered
    db_flight_names = await ExpectedFlightCargoDAO.get_distinct_flights_for_client(
        session, client.active_codes
    )
    seen_keys: set[str] = set()
    merged_matches: list[dict] = []
    for match in sheets_matches:
        key = match["flight_name"].strip().upper()
        if key not in seen_keys:
            seen_keys.add(key)
            merged_matches.append(match)
    for flight_name in db_flight_names:
        key = flight_name.strip().upper()
        if key not in seen_keys:
            seen_keys.add(key)
            # row_number is stored but never rendered — use 0 as sentinel for DB-sourced flights
            merged_matches.append({"flight_name": flight_name, "row_number": 0})

    if not merged_matches:
        await message.answer(_("payment-no-orders"))
        return

    available_flights = []
    for match in merged_matches:
        flight_name = match["flight_name"]
        existing_tx = await _get_existing_tx(session, client.active_codes, flight_name)

        if existing_tx and existing_tx.payment_status == "paid":
            continue  # Skip fully paid flights

        payment_data = await calculate_flight_payment(session, flight_name, client.active_codes, redis)
        available_flights.append({
            "flight_name": flight_name,
            "row_number": match["row_number"],
            "total_payment": payment_data["total_payment"] if payment_data else None,
            "existing_tx": existing_tx,
        })

    if not available_flights:
        await message.answer(_("payment-all-paid"))
        return

    builder = InlineKeyboardBuilder()
    for flight in available_flights:
        flight_name = flight["flight_name"]
        total_payment = flight["total_payment"]
        existing_tx = flight["existing_tx"]

        if total_payment is not None:
            if existing_tx and existing_tx.payment_status == "partial":
                remaining = _parse_decimal(existing_tx.remaining_amount)
                label = _("payment-partial-remaining")
                button_text = f"✈️ {flight_name} - {remaining:,.2f} so'm ({label})"
            else:
                button_text = f"✈️ {flight_name} - {total_payment:,.2f} so'm"
        elif existing_tx and existing_tx.total_amount:
            # Flight from expected-cargo DB — use the recorded transaction amount
            if existing_tx.payment_status == "partial":
                remaining = _parse_decimal(existing_tx.remaining_amount)
                label = _("payment-partial-remaining")
                button_text = f"✈️ {flight_name} - {remaining:,.2f} so'm ({label})"
            else:
                button_text = f"✈️ {flight_name} - {float(existing_tx.total_amount):,.2f} so'm"
        else:
            label = _("info-report-not-sent")
            button_text = f"✈️ {flight_name} - {label}"

        builder.button(text=button_text, callback_data=f"pay_flight:{flight_name}")

    builder.adjust(1)
    await message.answer(_("payment-select-flight"), reply_markup=builder.as_markup())


@make_payment_router.callback_query(F.data.startswith("pay_flight:"))
async def payment_flight_selected(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    redis: Redis,
):
    """Handle flight selection for payment."""
    client = await _get_client_safe(callback.from_user.id, session, client_service)
    if not client:
        await callback.message.answer(
            _("start") + "\n\n" + "Iltimos, Tizimga kiring!",
            reply_markup=auth_login_kb(_),
        )
        return

    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    flight_name = parts[1]

    payment_data = await calculate_flight_payment(session, flight_name, client.active_codes, redis)

    if not payment_data:
        no_report_text = (
            f"⚠️ <b>Hisobot yuborilmagan</b>\n\n"
            f"✈️ Reys: <b>{flight_name}</b>\n"
            f"👤 Mijoz kodi: <b>{client.client_code}</b>\n\n"
            f"Ushbu reys uchun hali admin tomonidan foto hisobot yuborilmagan. "
            f"Iltimos, admin bilan bog'laning yoki keyinroq qayta urinib ko'ring."
        )
        try:
            await callback.message.edit_text(no_report_text, parse_mode="HTML")
        except TelegramBadRequest:
            try:
                await callback.message.edit_caption(no_report_text, parse_mode="HTML")
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise
        await callback.answer()
        return

    trek_kodlari = ", ".join(payment_data["track_codes"]) if payment_data["track_codes"] else "N/A"

    await state.update_data(
        worksheet=flight_name,
        row_number=0,
        summa=f"{payment_data['total_payment']:,.2f}",
        vazn=f"{payment_data['total_weight']:.2f}",
        trek_kodlari=trek_kodlari,
        use_wallet=False,
        wallet_used=0,
        final_payable_amount=0,
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=_("btn-payment-online"), callback_data=f"payment_type:online:{flight_name}")
    builder.button(text=_("btn-payment-cash"), callback_data=f"payment_type:cash:{flight_name}")
    builder.adjust(1)

    await callback.message.answer(_("payment-select-type"), reply_markup=builder.as_markup())
    await callback.answer()


@make_payment_router.callback_query(F.data.startswith("payment_type:online:"))
async def payment_type_online_selected(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    state: FSMContext,
):
    """Handle online payment type selection - show full or partial payment options."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    flight_name = parts[2]

    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    data = await state.get_data()
    if not data:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    total_payment = parse_money(data.get("summa", "0"))
    existing_tx = await _get_existing_tx(session, client.active_codes, flight_name)

    builder = InlineKeyboardBuilder()

    if existing_tx and existing_tx.payment_status == "partial":
        remaining = _parse_decimal(existing_tx.remaining_amount)
        message_text = _("payment-online-partial", remaining=f"{remaining:,.2f}")
        builder.button(
            text=_("btn-pay-full-remaining", amount=f"{remaining:,.2f}"),
            callback_data=f"pay_full_remaining:{flight_name}",
        )
        builder.button(text=_("btn-cancel"), callback_data="payment_cancel")
    else:
        message_text = _("payment-online-options")
        builder.button(text=_("btn-pay-full"), callback_data=f"pay_full:{flight_name}")
        if total_payment >= 25000:
            builder.button(text=_("btn-pay-partial"), callback_data=f"pay_partial:{flight_name}")
        builder.button(text=_("btn-cancel"), callback_data="payment_cancel")

    builder.adjust(1)
    await _safe_edit_text(callback, message_text, reply_markup=builder.as_markup())
    await callback.answer()


@make_payment_router.callback_query(F.data.startswith("payment_type:cash:"))
async def payment_type_cash_selected(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
):
    """Handle cash payment type selection."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    flight_name = parts[2]

    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    data = await state.get_data()
    if not data:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    wallet_balance = await _get_wallet_balance(session, client.active_codes)
    await state.update_data(
        payment_mode="cash",
        wallet_balance=wallet_balance,
        use_wallet=False,
        wallet_used=0,
        final_payable_amount=0,
    )

    confirmation_text = _(
        "payment-cash-confirmation",
        flight_name=flight_name,
        summa=data["summa"],
        vazn=data["vazn"],
        trek_kodlari=data.get("trek_kodlari", "N/A"),
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=_("btn-confirm"), callback_data=f"cash_confirm:{flight_name}")
    _add_wallet_toggle_button(builder, wallet_balance, False, flight_name, _)
    builder.button(text=_("btn-cancel"), callback_data="cash_cancel")
    builder.adjust(1)

    await _safe_edit_text(callback, confirmation_text, reply_markup=builder.as_markup())
    await callback.answer()


@make_payment_router.callback_query(F.data.startswith("pay_full:"))
async def pay_full_handler(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
):
    """Handle full payment selection."""
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    flight_name = parts[1]

    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    data = await state.get_data()
    if not data:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    card = await _get_random_card(session, callback, _)
    if not card:
        return

    wallet_balance = await _get_wallet_balance(session, client.active_codes)
    await state.update_data(
        payment_mode="full",
        wallet_balance=wallet_balance,
        use_wallet=False,
        wallet_used=0,
        final_payable_amount=0,
        shown_card_id=card.id,
    )

    payment_info = _(
        "payment-info",
        client_code=client.primary_code,
        worksheet=flight_name,
        summa=data["summa"],
        vazn=data["vazn"],
        trek_kodlari=data.get("trek_kodlari", "N/A"),
        card_number=card.card_number,
        card_owner=card.full_name,
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=_("btn-send-payment-proof"), callback_data="send_payment_proof")
    _add_wallet_toggle_button(builder, wallet_balance, False, flight_name, _)
    builder.adjust(1)

    await callback.message.edit_text(payment_info, reply_markup=builder.as_markup())
    await callback.answer()


@make_payment_router.callback_query(F.data.startswith("pay_full_remaining:"))
async def pay_full_remaining_handler(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    state: FSMContext,
):
    """Handle full remaining payment selection."""
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    flight_name = parts[1]

    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    existing_tx = await _get_existing_tx(session, client.active_codes, flight_name)
    if not existing_tx or existing_tx.payment_status != "partial":
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    card = await _get_random_card(session, callback, _)
    if not card:
        return

    data = await state.get_data()
    if not data:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    remaining = _parse_decimal(existing_tx.remaining_amount)
    wallet_balance = await _get_wallet_balance(session, client.active_codes)

    await state.update_data(
        payment_mode="full_remaining",
        remaining_amount=remaining,
        wallet_balance=wallet_balance,
        use_wallet=False,
        wallet_used=0,
        final_payable_amount=0,
        shown_card_id=card.id,
    )

    payment_info = _(
        "payment-info-remaining",
        client_code=client.primary_code,
        worksheet=flight_name,
        summa=f"{remaining:,.2f}",
        vazn=data["vazn"],
        trek_kodlari=data.get("trek_kodlari", "N/A"),
        card_number=card.card_number,
        card_owner=card.full_name,
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=_("btn-send-payment-proof"), callback_data="send_payment_proof")
    _add_wallet_toggle_button(builder, wallet_balance, False, flight_name, _)
    builder.adjust(1)

    await callback.message.edit_text(payment_info, reply_markup=builder.as_markup())
    await callback.answer()


@make_payment_router.callback_query(F.data.startswith("pay_partial:"))
async def pay_partial_handler(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    state: FSMContext,
):
    """Handle partial payment selection - show information screen."""
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    flight_name = parts[1]

    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    data = await state.get_data()
    if not data:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    total_amount = parse_money(data["summa"])
    existing_tx = await _get_existing_tx(session, client.active_codes, flight_name)

    if existing_tx and existing_tx.payment_status == "partial":
        paid_amount = _parse_decimal(existing_tx.paid_amount)
        remaining_amount = _parse_decimal(existing_tx.remaining_amount)
        deadline_text = (
            existing_tx.payment_deadline.strftime("%Y-%m-%d %H:%M")
            if existing_tx.payment_deadline
            else _("not-set")
        )
    else:
        from datetime import datetime, timedelta, timezone

        paid_amount = 0.0
        remaining_amount = total_amount
        deadline_text = (datetime.now(timezone.utc) + timedelta(days=15)).strftime("%Y-%m-%d %H:%M")

    info_text = _(
        "payment-partial-info",
        flight=flight_name,
        client_code=client.primary_code,
        total=total_amount,
        paid=paid_amount,
        remaining=remaining_amount,
        deadline=deadline_text,
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=_("btn-enter-amount"), callback_data=f"enter_partial_amount:{flight_name}")
    builder.button(text=_("btn-cancel"), callback_data="payment_cancel")
    builder.adjust(1)

    await callback.message.edit_text(info_text, reply_markup=builder.as_markup())
    await callback.answer()


@make_payment_router.callback_query(F.data.startswith("enter_partial_amount:"))
async def enter_partial_amount_handler(
    callback: CallbackQuery, _: callable, state: FSMContext
):
    """Activate state to receive partial payment amount."""
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    flight_name = parts[1]
    await state.update_data(payment_mode="partial", partial_flight=flight_name, partial_row=0)
    await state.set_state(PaymentStates.waiting_for_partial_amount)
    await callback.message.answer(_("payment-partial-enter-amount"))
    await callback.answer()


@make_payment_router.message(PaymentStates.waiting_for_partial_amount, F.text)
async def partial_amount_received(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    state: FSMContext,
):
    """Process received partial payment amount."""
    data = await state.get_data()
    if not data:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    flight_name = data.get("partial_flight")
    if not flight_name:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    client = await client_service.get_client(message.from_user.id, session)
    if not client:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    try:
        amount = parse_money(message.text)
    except ValueError:
        await session.rollback()
        await message.answer(_("payment-partial-invalid-amount"))
        return

    total_amount = parse_money(data.get("summa", "0"))
    existing_tx = await _get_existing_tx(session, client.active_codes, flight_name)
    remaining_amount = (
        _parse_decimal(existing_tx.remaining_amount)
        if existing_tx and existing_tx.payment_status == "partial"
        else total_amount
    )

    if amount < 1000:
        await message.answer(_("payment-partial-min-amount", min=1000))
        return
    if amount > remaining_amount:
        await message.answer(_("payment-partial-max-amount", max=remaining_amount))
        return
    if amount > total_amount:
        await message.answer(_("payment-partial-exceeds-total", total=total_amount))
        return

    wallet_balance = await _get_wallet_balance(session, client.active_codes)
    await state.update_data(
        partial_amount=amount,
        wallet_balance=wallet_balance,
        use_wallet=False,
        wallet_used=0,
        final_payable_amount=0,
    )

    card = await _get_random_card(session, message, _)
    if not card:
        await state.clear()
        return
    await state.update_data(shown_card_id=card.id)

    payment_info = _(
        "payment-info-partial",
        client_code=client.primary_code,
        worksheet=flight_name,
        summa=f"{amount:,.2f}",
        vazn=data.get("vazn", "N/A"),
        trek_kodlari=data.get("trek_kodlari", "N/A"),
        card_number=card.card_number,
        card_owner=card.full_name,
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=_("btn-send-payment-proof"), callback_data="send_payment_proof")
    _add_wallet_toggle_button(builder, wallet_balance, False, flight_name, _)
    builder.adjust(1)

    await message.answer(payment_info, reply_markup=builder.as_markup())


@make_payment_router.callback_query(F.data.startswith("payment_wallet_toggle:"))
async def payment_wallet_toggle_handler(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    redis: Redis,
):
    """Toggle wallet usage for payment."""
    await callback.answer()

    parts = callback.data.split(":")
    if len(parts) != 2:
        return

    flight_name = parts[1]
    data = await state.get_data()
    if not data:
        return

    client = await _get_client_safe(callback.from_user.id, session, client_service)
    if not client:
        return

    use_wallet = not data.get("use_wallet", False)
    wallet_balance = await _get_wallet_balance(session, client.active_codes)

    total_payment = parse_money(data.get("summa", "0"))
    selected_amount = _resolve_selected_amount(data, total_payment)
    wallet_used, final_payable_amount = _build_wallet_amounts(selected_amount, wallet_balance, use_wallet)

    await state.update_data(
        use_wallet=use_wallet,
        wallet_balance=wallet_balance,
        wallet_used=wallet_used,
        final_payable_amount=final_payable_amount,
    )

    payment_mode = data.get("payment_mode", "full")
    builder = InlineKeyboardBuilder()

    if payment_mode == "cash":
        if use_wallet and wallet_used > 0 and final_payable_amount <= 0:
            message_text = _(
                "payment-select-type-with-wallet",
                total=f"{selected_amount:,.2f}",
                wallet_deduction=f"{wallet_used:,.2f}",
                final="0",
            )
            builder.button(text=_("btn-payment-wallet-only"), callback_data=f"payment_wallet_only:{flight_name}")
        else:
            message_text = _(
                "payment-cash-confirmation",
                flight_name=flight_name,
                summa=f"{final_payable_amount:,.2f}" if (use_wallet and wallet_used > 0) else data.get("summa", "0"),
                vazn=data.get("vazn", "N/A"),
                trek_kodlari=data.get("trek_kodlari", "N/A"),
            )
            if use_wallet and wallet_used > 0:
                message_text += f"\n\n💰 Hamyondan: {wallet_used:,.2f} so'm\n💵 Naqd to'lanadi: {final_payable_amount:,.2f} so'm"
            builder.button(text=_("btn-confirm"), callback_data=f"cash_confirm:{flight_name}")
    else:
        card = await PaymentCardService().get_random_active_card(session)
        if not card:
            await callback.answer(_("payment-no-cards"), show_alert=True)
            return
        await state.update_data(shown_card_id=card.id)

        if use_wallet and wallet_used > 0 and final_payable_amount <= 0:
            message_text = _(
                "payment-select-type-with-wallet",
                total=f"{selected_amount:,.2f}",
                wallet_deduction=f"{wallet_used:,.2f}",
                final="0",
            )
            builder.button(text=_("btn-payment-wallet-only"), callback_data=f"payment_wallet_only:{flight_name}")
        else:
            template_key = {
                "partial": "payment-info-partial",
                "full_remaining": "payment-info-remaining",
            }.get(payment_mode, "payment-info")

            if use_wallet and wallet_used > 0:
                message_text = _(
                    "payment-info-with-wallet",
                    client_code=client.primary_code,
                    worksheet=flight_name,
                    summa=f"{selected_amount:,.2f}",
                    wallet_used=f"{wallet_used:,.2f}",
                    final_payable=f"{final_payable_amount:,.2f}",
                    vazn=data.get("vazn", "N/A"),
                    trek_kodlari=data.get("trek_kodlari", "N/A"),
                    card_number=card.card_number,
                    card_owner=card.full_name,
                )
            else:
                message_text = _(
                    template_key,
                    client_code=client.primary_code,
                    worksheet=flight_name,
                    summa=f"{selected_amount:,.2f}",
                    vazn=data.get("vazn", "N/A"),
                    trek_kodlari=data.get("trek_kodlari", "N/A"),
                    card_number=card.card_number,
                    card_owner=card.full_name,
                )
            builder.button(text=_("btn-send-payment-proof"), callback_data="send_payment_proof")

    _add_wallet_toggle_button(builder, wallet_balance, use_wallet, flight_name, _)
    builder.adjust(1)

    await _safe_edit_text(callback, message_text, reply_markup=builder.as_markup())


@make_payment_router.callback_query(F.data.startswith("payment_wallet_only:"))
async def payment_wallet_only_handler(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    bot: Bot,
    redis: Redis,
):
    """Handle payment fully covered by wallet balance."""
    await callback.answer()

    parts = callback.data.split(":")
    if len(parts) != 2:
        return

    flight_name = parts[1]

    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        return

    data = await state.get_data()
    total_payment = parse_money(data.get("summa", "0"))
    wallet_balance = data.get("wallet_balance", 0)
    vazn = data.get("vazn", "N/A")

    selected_amount = _resolve_selected_amount(data, total_payment)

    if wallet_balance < selected_amount:
        await callback.message.answer(_("error-occurred"))
        return

    wallet_used = selected_amount
    final_payable_amount = 0.0

    await state.update_data(wallet_used=wallet_used, final_payable_amount=final_payable_amount, use_wallet=True)
    await _cache_payment_meta(redis, client.primary_code, flight_name, "wallet_only", wallet_used=wallet_used)

    payment_data = await calculate_flight_payment(session, flight_name, client.primary_code, redis)
    track_codes = payment_data.get("track_codes", []) if payment_data else []
    if (not vazn or vazn == "N/A") and payment_data:
        vazn = f"{payment_data['total_weight']:.2f}"

    from src.bot.handlers.admin.payment_approval import build_admin_payment_message

    caption = build_admin_payment_message(
        _=_,
        client_code=client.primary_code,
        worksheet=flight_name,
        payment_provider="wallet",
        payment_status="paid",
        summa=float(total_payment),
        full_name=callback.from_user.full_name,
        phone=client.phone or "N/A",
        telegram_id=str(callback.from_user.id),
        vazn=str(vazn),
        track_codes=track_codes,
        wallet_used=wallet_used,
        final_payable=final_payable_amount,
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=_("btn-approve-payment"),
        callback_data=f"approve_payment:{client.primary_code}:{flight_name}",
    ))
    builder.row(InlineKeyboardButton(
        text=_("btn-reject-payment"),
        callback_data=f"reject_payment:{client.primary_code}",
    ))

    try:
        await bot.send_message(
            chat_id=config.telegram.TOLOVLARNI_TASDIQLASH_GROUP_ID,
            text=caption,
            reply_markup=builder.as_markup(),
        )
        await callback.message.edit_text(_(
            "payment-wallet-only-submitted",
            flight=flight_name,
            amount=f"{total_payment:,.2f}",
        ))
    except Exception as e:
        await session.rollback()
        logger.error(f"Error sending wallet-only payment to admin group: {e}")
        await callback.message.edit_text(_("error-occurred"))
    finally:
        await state.clear()


@make_payment_router.callback_query(F.data == "send_payment_proof")
async def send_payment_proof_callback(
    callback: CallbackQuery, _: callable, state: FSMContext
):
    """Activate state to receive payment proof."""
    await state.set_state(PaymentStates.waiting_for_payment_proof)
    await callback.message.answer(_("payment-send-proof-single"))
    await callback.answer()


@make_payment_router.message(
    PaymentStates.waiting_for_payment_proof,
    F.content_type.in_(["photo", "document"]),
)
async def payment_proof_received(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    bot: Bot,
    redis: Redis,
):
    """Process received payment proof (single photo or document)."""
    data = await state.get_data()
    if not data:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    client = await client_service.get_client(message.from_user.id, session)
    if not client:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    worksheet = data["worksheet"]
    summa = data["summa"]
    vazn = data.get("vazn", "N/A")

    payment_data = await calculate_flight_payment(session, worksheet, client.primary_code, redis)
    track_codes = payment_data.get("track_codes", []) if payment_data else []
    if (not vazn or vazn == "N/A") and payment_data:
        vazn = f"{payment_data['total_weight']:.2f}"

    # --- Download, (optionally) optimize, upload to S3 ---
    file_id_for_admin = None
    upload_content = None
    content_type = "application/octet-stream"
    ext = "file"

    if message.photo:
        file_id_for_admin = message.photo[-1].file_id
        raw = (await bot.download(message.photo[-1])).read()
        try:
            upload_content = await optimize_image_to_webp(raw)
            content_type, ext = "image/webp", "webp"
        except Exception:
            upload_content, content_type, ext = raw, "image/jpeg", "jpg"
    elif message.document:
        file_id_for_admin = message.document.file_id
        upload_content = (await bot.download(message.document)).read()
        content_type = message.document.mime_type or "application/octet-stream"
        ext = (
            message.document.file_name.rsplit(".", 1)[-1]
            if message.document.file_name and "." in message.document.file_name
            else "file"
        )

    if not file_id_for_admin:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    try:
        s3_key = await s3_manager.upload_file(
            file_content=upload_content,
            file_name=f"receipt_{worksheet}.{ext}",
            telegram_id=message.from_user.id,
            client_code=client.primary_code,
            base_folder="payment-receipts",
            sub_folder="",
            content_type=content_type,
        )
    except Exception as e:
        logger.error(f"Failed to upload payment proof to S3: {e}")
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    # --- Cache payment metadata ---
    payment_mode = data.get("payment_mode", "full")
    wallet_used = data.get("wallet_used", 0)
    partial_amount = data.get("partial_amount") or data.get("remaining_amount")

    await _cache_payment_meta(
        redis,
        client.primary_code,
        worksheet,
        payment_mode,
        wallet_used=wallet_used,
        partial_amount=partial_amount,
        s3_key=s3_key,
        card_id=data.get("shown_card_id"),
    )

    # --- Build admin caption ---
    is_partial = payment_mode in ("partial", "full_remaining")
    payment_status = "partial" if is_partial else "paid"

    existing_tx = await _get_existing_tx(session, client.active_codes, worksheet)

    paid_amount = remaining_amount = total_amount = None
    if is_partial and payment_data:
        total_amount = payment_data["total_payment"]
        if existing_tx and existing_tx.payment_status == "partial":
            paid_amount = float(existing_tx.paid_amount)
            remaining_amount = float(existing_tx.remaining_amount)
        else:
            paid_amount = 0.0
            remaining_amount = float(total_amount)

    from src.bot.handlers.admin.payment_approval import build_admin_payment_message

    caption = build_admin_payment_message(
        _=_,
        client_code=client.primary_code,
        worksheet=worksheet,
        payment_provider="online",
        payment_status=payment_status,
        summa=parse_money(summa) if isinstance(summa, str) else float(summa),
        full_name=message.from_user.full_name,
        phone=client.phone or "N/A",
        telegram_id=str(message.from_user.id),
        vazn=str(vazn),
        track_codes=track_codes,
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        total_amount=total_amount,
        deadline=None,
        wallet_used=wallet_used,
        final_payable=data.get("final_payable_amount"),
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=_("btn-approve-payment"),
        callback_data=f"approve_payment:{client.primary_code}:{worksheet}",
    ))
    builder.row(InlineKeyboardButton(
        text=_("btn-reject-payment"),
        callback_data=f"reject_payment:{client.primary_code}",
    ))
    builder.row(InlineKeyboardButton(
        text=_("btn-reject-with-comment"),
        callback_data=f"reject_payment_comment:{client.primary_code}",
    ))

    try:
        group_id = config.telegram.TOLOVLARNI_TASDIQLASH_GROUP_ID
        if message.photo:
            await bot.send_photo(chat_id=group_id, photo=file_id_for_admin, caption=caption, reply_markup=builder.as_markup())
        elif message.document:
            await bot.send_document(chat_id=group_id, document=file_id_for_admin, caption=caption, reply_markup=builder.as_markup())

        await message.answer(_("payment-submitted"))
    except Exception as e:
        await session.rollback()
        logger.error(f"Error sending payment to admin group: {e}")
        await message.answer(_("error-occurred"))
    finally:
        await state.clear()


@make_payment_router.callback_query(F.data.startswith("cash_confirm:"))
async def cash_payment_confirmed(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    bot: Bot,
    redis: Redis,
):
    """Handle cash payment confirmation."""
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    flight_name = parts[1]

    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    data = await state.get_data()
    if not data:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    payment_data = await calculate_flight_payment(session, flight_name, client.primary_code, redis)
    track_codes = payment_data.get("track_codes", []) if payment_data else []
    vazn = data.get("vazn", "N/A")
    if (not vazn or vazn == "N/A") and payment_data:
        vazn = f"{payment_data['total_weight']:.2f}"

    wallet_used = data.get("wallet_used", 0)
    # Always cache payment_mode="cash" so _process_approved_payment resolves provider correctly,
    # even when wallet is not used (wallet_used=0 means no wallet deduction, not a different mode)
    await _cache_payment_meta(redis, client.primary_code, flight_name, "cash", wallet_used=wallet_used)

    from src.bot.handlers.admin.payment_approval import build_admin_payment_message

    caption = build_admin_payment_message(
        _=_,
        client_code=client.primary_code,
        worksheet=flight_name,
        payment_provider="cash",
        payment_status="paid",
        summa=float(data["summa"].replace(",", "")),
        full_name=callback.from_user.full_name,
        phone=client.phone or "N/A",
        telegram_id=str(callback.from_user.id),
        vazn=str(vazn),
        track_codes=track_codes,
        wallet_used=wallet_used,
        final_payable=data.get("final_payable_amount"),
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=_("btn-cash-payment-confirmed"),
        callback_data=f"cash_payment_confirmed:{client.primary_code}:{flight_name}",
    ))

    try:
        await bot.send_message(
            chat_id=config.telegram.TOLOVLARNI_TASDIQLASH_GROUP_ID,
            text=caption,
            reply_markup=builder.as_markup(),
        )
        await callback.message.edit_text(_("payment-cash-submitted"))
        await callback.answer()
    except Exception as e:
        await session.rollback()
        logger.error(f"Error sending cash payment to admin group: {e}")
        await callback.message.edit_text(_("error-occurred"))
        await callback.answer()
    finally:
        await state.clear()


@make_payment_router.callback_query(F.data == "payment_cancel")
async def payment_cancelled(callback: CallbackQuery, _: callable, state: FSMContext):
    """Handle payment cancellation."""
    await state.clear()
    await callback.message.edit_text(_("payment-cancelled"))
    await callback.answer()


@make_payment_router.callback_query(F.data == "cash_cancel")
async def cash_payment_cancelled(callback: CallbackQuery, _: callable, state: FSMContext):
    """Handle cash payment cancellation."""
    await state.clear()
    await callback.message.edit_text(_("payment-cancelled"))
    await callback.answer()