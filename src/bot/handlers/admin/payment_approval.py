"""Payment approval handlers for admins."""


import contextlib
import re
import logging
from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.bot.filters.is_admin import IsAdmin
from src.bot.keyboards.user.reply_keyb.user_home_kyb import user_main_menu_kyb
from src.bot.utils.i18n import i18n
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.client_payment_event import ClientPaymentEventDAO
from src.infrastructure.services import (
    ClientService,
    ClientTransactionService,
    PaymentAllocationService,
)
from src.infrastructure.tools.money_utils import parse_money
from src.infrastructure.tools.passport_image_resolver import _is_s3_key
from src.infrastructure.tools.s3_manager import s3_manager
from src.config import config


logger = logging.getLogger(__name__)

payment_approval_router = Router(name="payment_approval")


class RejectCommentState(StatesGroup):
    waiting_for_comment = State()


class PaymentApprovalState(StatesGroup):
    waiting_for_amount = State()


class CashPaymentApprovalState(StatesGroup):
    waiting_for_amount = State()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def safe_answer_callback(
    callback: CallbackQuery, text: str = "", show_alert: bool = False
) -> None:
    """Safely answer callback query, handling timeouts."""
    try:
        if callback.bot:
            await callback.bot.answer_callback_query(
                callback_query_id=callback.id, text=text, show_alert=show_alert
            )
    except Exception as e:
        logger.warning(f"Failed to answer callback safely: {e}")


async def _remove_buttons(callback: CallbackQuery) -> None:
    """Remove inline keyboard. Silently ignore errors."""
    with contextlib.suppress(Exception):
        await callback.message.edit_reply_markup(reply_markup=None)


def _extract_flight_name(text: str | None) -> str:
    """Extract flight/worksheet name from admin message text or caption."""
    if not text:
        return ""
    for pattern in [
        r"Reys:\s*<b>([^<]+)</b>",
        r"Reys:\s*(.+)",
        r"Worksheet:\s*(.+)",
    ]:
        if m := re.search(pattern, text, re.IGNORECASE):
            return m[1].strip()
    return ""


def _user_translator(client, lang_fallback: str = "uz") -> callable:
    lang = client.language_code if client and client.language_code else lang_fallback
    return lambda key, **kw: i18n.get(lang, key, **kw)


async def _get_redis_str(redis: Redis, key: str) -> str | None:
    """Get a Redis value as a plain string (handles bytes)."""
    raw = await redis.get(key)
    if raw is None:
        return None
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)


async def _get_redis_float(redis: Redis, key: str, default: float = 0.0) -> float:
    raw = await _get_redis_str(redis, key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


async def _resolve_receipt(
    redis: Redis,
    client_code: str,
    worksheet: str,
) -> str | None:
    """Return a usable receipt reference (presigned URL or file_id), or None."""
    raw = await _get_redis_str(redis, f"payment_receipt:{client_code}:{worksheet}")
    if not raw:
        return None
    if _is_s3_key(raw):
        return await s3_manager.generate_presigned_url(raw, expires_in=3600)
    return raw


def _build_breakdown_line(breakdown: dict) -> str:
    labels = {"click": "Click", "payme": "Payme", "card": "Karta", "cash": "Naqd"}
    parts = [
        f"{label}: {breakdown[key]:,.2f} so'm"
        for key, label in labels.items()
        if breakdown.get(key, 0) > 0
    ]
    return "💳 To'lov turlari: " + " | ".join(parts) if parts else ""


async def _notify_user(
    bot: Bot,
    telegram_id: int,
    text: str,
    user_text: callable,
) -> None:
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            reply_markup=user_main_menu_kyb(translator=user_text),
        )
    except Exception as e:
        logger.warning(f"Failed to notify user {telegram_id}: {e}")


async def _send_to_channel(
    bot: Bot,
    channel_id: int,
    text: str,
    receipt=None,
    parse_mode: str | None = None,
) -> None:
    """Send notification to channel, falling back to text if photo fails."""
    try:
        if receipt:
            await bot.send_photo(
                chat_id=channel_id, photo=receipt, caption=text, parse_mode=parse_mode
            )
        else:
            await bot.send_message(chat_id=channel_id, text=text, parse_mode=parse_mode)
    except Exception as e:
        logger.warning(f"Failed to send receipt to channel, retrying as text: {e}")
        try:
            await bot.send_message(chat_id=channel_id, text=text, parse_mode=parse_mode)
        except Exception as e2:
            logger.error(f"Failed to send to channel entirely: {e2}")


async def _stamp_admin_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    stamp_text: str,
) -> None:
    """Remove inline keyboard and reply with a confirmation stamp."""
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=None
        )
        await bot.send_message(
            chat_id=chat_id, text=stamp_text, reply_to_message_id=message_id
        )
    except Exception as e:
        logger.warning(f"Failed to update admin message: {e}")


# ---------------------------------------------------------------------------
# Business logic helpers
# ---------------------------------------------------------------------------


def get_payment_provider_label(_, payment_provider: str, payment_status: str) -> str:
    if payment_provider == "cash":
        return _("payment-label-cash")
    if payment_provider == "wallet":
        return "💰 Hamyon"
    if payment_provider in {"click", "payme", "card"}:
        provider_name = {"click": "Click", "payme": "Payme", "card": "Karta"}.get(
            payment_provider, payment_provider.title()
        )
        base = (
            _("payment-label-online-partial")
            if payment_status == "partial"
            else _("payment-label-online-full")
        )
        return f"{base} - {provider_name}"
    # Fallback for legacy/unknown
    return (
        _("payment-label-online-partial")
        if payment_status == "partial"
        else _("payment-label-online-full")
    )


def build_admin_payment_message(
    _: callable,
    client_code: str,
    worksheet: str,
    payment_provider: str,
    payment_status: str,
    summa: float,
    full_name: str,
    phone: str,
    telegram_id: str,
    vazn: str | None = None,
    track_codes: list[str] | None = None,
    paid_amount: float | None = None,
    remaining_amount: float | None = None,
    total_amount: float | None = None,
    deadline: str | None = None,
    wallet_used: float = 0,
    final_payable: float | None = None,
) -> str:
    payment_label = get_payment_provider_label(_, payment_provider, payment_status)
    track_codes_text = ", ".join(track_codes) if track_codes else "N/A"
    vazn_text = vazn or "N/A"

    wallet_info = ""
    if wallet_used > 0:
        wallet_info = f"\n💰 Hamyondan: {wallet_used:,.2f} so'm"
        if final_payable is not None:
            wallet_info += (
                f"\n💵 Qo'shimcha to'lov: {final_payable:,.2f} so'm"
                if final_payable > 0
                else "\n⚠️ Faqat hamyon hisobidan to'lov"
            )

    if (
        payment_status == "partial"
        and paid_amount is not None
        and remaining_amount is not None
    ):
        base_msg = _(
            "payment-admin-notification-partial",
            payment_label=payment_label,
            client_code=client_code,
            worksheet=worksheet,
            total=f"{total_amount or summa:.2f}",
            paid=f"{paid_amount:.2f}",
            remaining=f"{remaining_amount:.2f}",
            deadline=deadline or _("not-set"),
            vazn=vazn_text,
            track_codes=track_codes_text,
            full_name=full_name,
            phone=phone,
            telegram_id=telegram_id,
        )
    else:
        base_msg = _(
            "payment-admin-notification-full",
            payment_label=payment_label,
            client_code=client_code,
            worksheet=worksheet,
            summa=f"{summa:.2f}",
            vazn=vazn_text,
            track_codes=track_codes_text,
            full_name=full_name,
            phone=phone,
            telegram_id=telegram_id,
        )

    return base_msg + wallet_info if wallet_info else base_msg


# ---------------------------------------------------------------------------
# Shared processing helper for online payment approval
# ---------------------------------------------------------------------------


async def _process_approved_payment(
    *,
    amount: float,
    data: dict,
    session: AsyncSession,
    bot: Bot,
    redis: Redis,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    approver_id: int,
    approver_name: str,
    answer_func,
    _: callable,
    state: FSMContext,
) -> None:    # sourcery skip: low-code-quality
    """
    Finalise an online payment approval.

    Shared by both the manual-amount text handler and the one-click
    "To'liq to'landi" button callback so the business logic lives in
    exactly one place.

    Args:
        amount:           Amount the admin confirmed as received.
        data:             FSM state data containing approval_* keys.
        session:          Async DB session.
        bot:              Bot instance.
        redis:            Redis client.
        client_service:   ClientService instance.
        transaction_service: ClientTransactionService instance (reserved for future use).
        approver_id:      Telegram ID of the approving admin.
        approver_name:    Display name of the approving admin.
        answer_func:      Callable that sends a reply to the admin (message.answer or
                          callback.message.answer).
        _:                i18n translator for the current locale.
        state:            FSM context.
    """
    telegram_id = data["approval_telegram_id"]
    worksheet = data["approval_worksheet"]
    client_code = data["approval_client_code"]
    expected_amount = data.get("approval_expected_amount", 0)
    is_wallet_only = data.get("approval_is_wallet_only", False)

    if not client_code or not worksheet:
        await answer_func(_("error-occurred"))
        await state.clear()
        return

    client = await client_service.get_client_by_code(client_code, session)
    if not client:
        await answer_func(_("error-occurred"))
        await state.clear()
        return

    # --- Redis lookups ---
    wallet_used = await _get_redis_float(redis, f"wallet_used:{client_code}:{worksheet}")
    payment_mode = (
        await _get_redis_str(redis, f"payment_mode:{client_code}:{worksheet}") or "full"
    )
    payment_provider_raw = await _get_redis_str(
        redis, f"payment_provider:{client_code}:{worksheet}"
    )
    payment_card_id_str = await _get_redis_str(redis, f"payment_card_id:{client_code}:{worksheet}")
    payment_card_id = int(payment_card_id_str) if payment_card_id_str else None

    if payment_mode == "wallet_only":
        payment_provider = "wallet"
    elif payment_mode == "cash":
        # Cash payments never store a provider key in Redis — derive directly from mode
        payment_provider = "cash"
    else:
        payment_provider = payment_provider_raw or "click"
        if payment_provider not in ("cash", "click", "payme", "card"):
            payment_provider = "click"

    # --- Recalculate expected amounts ---
    from src.bot.handlers.user.make_payment import calculate_flight_payment

    payment_data = await calculate_flight_payment(
        session=session,
        flight_name=worksheet,
        client_code=client.active_codes,
        redis=redis,
    )
    total_payment = (
        payment_data["total_payment"]
        if payment_data
        else (amount if is_wallet_only else expected_amount)
    )
    vazn = payment_data["total_weight"] if payment_data else "N/A"
    track_codes = payment_data.get("track_codes", []) if payment_data else []

    existing_tx = await ClientTransactionDAO.get_by_client_code_flight(
        session, client.active_codes, worksheet
    )

    # Guard against double-approval
    if existing_tx and existing_tx.payment_status == "paid":
        await answer_func(
            "⚠️ Bu reys uchun to'lov allaqachon tasdiqlangan. Takroriy tasdiqlash bekor qilindi."
        )
        await state.clear()
        return

    # --- Persist payment ---
    from datetime import timedelta

    if existing_tx and existing_tx.payment_status == "partial":
        await ClientPaymentEventDAO.create(
            session=session,
            transaction_id=existing_tx.id,
            payment_provider=payment_provider,
            amount=amount,
            approved_by_admin_id=approver_id,
            payment_type="online",
            payment_card_id=payment_card_id,
        )
        await PaymentAllocationService.recalculate_transaction_balance(
            session, existing_tx.id
        )
    else:
        total_paid = wallet_used + amount
        remaining = total_payment - total_paid
        payment_status = "paid" if remaining <= 0 else "partial"
        pbd = amount - float(total_payment)

        deadline = None
        from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO

        # Resolve the authoritative client code from flight_cargos.
        # A user may have extra_code='STCH3' and client_code='SS9999', but their
        # cargo was registered under 'SS9999'. Using flight_cargos as the source
        # of truth ensures the transaction is stored under the same key as the
        # cargo, preventing duplicates when different subsystems use different codes.
        cargo_client_code = (
            await FlightCargoDAO.get_registered_client_code(
                session, worksheet, client.active_codes
            )
            or client.client_code
        )

        if remaining > 0:
            from src.infrastructure.tools.datetime_utils import (
                ensure_timezone_aware,
                get_current_time,
            )

            earliest = await FlightCargoDAO.get_earliest_created_at(
                session, worksheet, cargo_client_code, only_sent=True
            )
            if earliest:
                deadline = ensure_timezone_aware(earliest, assume_utc=True) + timedelta(
                    days=15
                )
            else:
                deadline = get_current_time() + timedelta(days=15)

        receipt_file_id = await _get_redis_str(redis, f"payment_receipt:{client_code}:{worksheet}")

        # Re-use a pending-debt row (written by bulk_cargo_sender) if one exists so that
        # the approval never creates a second transaction for the same user+flight.
        from src.infrastructure.tools.datetime_utils import get_current_time as _now
        _fully_paid_at = _now() if payment_status == "paid" else None

        if existing_tx and existing_tx.payment_status == "pending":
            existing_tx.client_code = cargo_client_code
            existing_tx.summa = float(total_payment)
            existing_tx.vazn = str(vazn)
            existing_tx.payment_receipt_file_id = receipt_file_id
            existing_tx.payment_type = "online"
            existing_tx.payment_status = payment_status
            existing_tx.paid_amount = amount
            existing_tx.total_amount = float(total_payment)
            existing_tx.remaining_amount = float(max(0, remaining))
            existing_tx.payment_deadline = deadline
            existing_tx.payment_balance_difference = pbd
            if _fully_paid_at and not existing_tx.fully_paid_date:
                existing_tx.fully_paid_date = _fully_paid_at
            new_tx = existing_tx
            await session.flush()
        else:
            new_tx = await ClientTransactionDAO.create(
                session,
                {
                    "telegram_id": client.telegram_id,
                    "client_code": cargo_client_code,
                    "qator_raqami": 0,
                    "reys": worksheet,
                    "summa": float(total_payment),
                    "vazn": str(vazn),
                    "payment_receipt_file_id": receipt_file_id,
                    "payment_type": "online",
                    "payment_status": payment_status,
                    "paid_amount": amount,
                    "total_amount": float(total_payment),
                    "remaining_amount": float(max(0, remaining)),
                    "payment_deadline": deadline,
                    "payment_balance_difference": pbd,
                    "fully_paid_date": _fully_paid_at,
                },
            )

        if amount > 0:
            await ClientPaymentEventDAO.create(
                session=session,
                transaction_id=new_tx.id,
                payment_provider=(
                    payment_provider
                    if payment_provider != "wallet"
                    else "click"
                ),
                amount=amount,
                approved_by_admin_id=approver_id,
                payment_type="online",
                payment_card_id=payment_card_id,
            )

    await session.commit()
    # --- Fetch receipt BEFORE cleaning Redis ---
    receipt = await _resolve_receipt(redis, client_code, worksheet)

    # --- Clean up Redis ---
    for key in (
        f"payment_receipt:{client_code}:{worksheet}",
        f"payment_mode:{client_code}:{worksheet}",
        f"payment_provider:{client_code}:{worksheet}",
        f"payment_amount:{client_code}:{worksheet}",
        f"wallet_used:{client_code}:{worksheet}",
        f"payment_card_id:{client_code}:{worksheet}",
    ):
        await redis.delete(key)

    # --- Build final state for notifications ---
    final_tx = await ClientTransactionDAO.get_by_client_code_flight(
        session, client.active_codes, worksheet
    )
    is_partial = bool(final_tx and final_tx.payment_status == "partial")
    final_paid = (
        float(final_tx.paid_amount)
        if final_tx and final_tx.paid_amount is not None
        else amount
    )
    final_remaining = (
        float(final_tx.remaining_amount)
        if final_tx and final_tx.remaining_amount is not None
        else 0.0
    )
    final_total = (
        float(final_tx.total_amount)
        if final_tx and final_tx.total_amount is not None
        else amount
    )
    deadline_text = (
        final_tx.payment_deadline.strftime("%Y-%m-%d %H:%M")
        if final_tx and final_tx.payment_deadline
        else None
    )

    # --- Analytics ---
    from src.infrastructure.services.analytics_service import AnalyticsService

    await AnalyticsService.emit_event(
        session=session,
        event_type="payment_approval",
        user_id=telegram_id,
        payload={
            "client_code": client.client_code,
            "flight_name": worksheet,
            "row_number": 0,
            "payment_provider": payment_provider,
            "payment_status": final_tx.payment_status if final_tx else "paid",
            "amount": amount,
            "is_partial": is_partial,
            "paid_amount": final_paid if is_partial else None,
            "remaining_amount": final_remaining if is_partial else None,
            "total_amount": final_total if is_partial else None,
            "approved_by_admin_id": approver_id,
        },
    )
    await session.commit()

    # --- Notify user ---
    user_text = _user_translator(client)
    is_fully_paid = (final_remaining <= 0) or (amount >= expected_amount)
    overpaid = max(0.0, amount - expected_amount)

    if is_partial:
        user_msg = user_text(
            "payment-approved-user-partial",
            worksheet=worksheet,
            paid=f"{final_paid:.2f}",
            remaining=f"{final_remaining:.2f}",
            total=f"{final_total:.2f}",
            deadline=deadline_text or user_text("not-set"),
        )
        await _notify_user(bot, telegram_id, user_msg, user_text)
    else:
        user_msg = user_text(
            "payment-approved-user", worksheet=worksheet, summa=f"{amount:.2f}"
        )
        await _notify_user(bot, telegram_id, user_msg, user_text)
        if is_fully_paid and telegram_id:
            webapp_btn = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="📦 1 daqiqada zayavka qoldiring",
                        web_app=WebAppInfo(url=config.telegram.webapp_request_page_url),
                    )
                ]]
            )
            try:
                await bot.send_message(
                    chat_id=telegram_id,
                    text=user_text(
                        "payment-approved-full-success",
                        worksheet=worksheet,
                        paid=f"{final_paid:,.2f}",
                        overpaid=overpaid,
                        overpaid_fmt=f"{overpaid:,.2f}",
                    ),
                    reply_markup=webapp_btn,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to send full-success WebApp message to {telegram_id}: {e}"
                )

    # --- Channel notification ---
    from datetime import datetime, timezone

    formatted_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    track_display = ", ".join(track_codes) if track_codes else "N/A"
    payment_emoji = "💵" if payment_provider == "cash" else "💳"
    status_line = (
        "✅ To'liq to'landi"
        if is_fully_paid
        else f"⚠️ Qisman to'lov ({final_remaining:,.2f} so'm qoldi)"
    )

    channel_text = (
        f"{'✅' if is_fully_paid else '⚠️'} <b>To'lov tasdiqlandi</b>\n"
        f"{'━' * 28}\n"
        f"👤 <b>Mijoz:</b> <code>{client.client_code}</code>\n"
        f"✈️ <b>Reys:</b> {worksheet}\n"
        f"{'━' * 28}\n"
        f"💰 <b>Jami narx:</b> {final_total:,.2f} so'm\n"
        f"{payment_emoji} <b>To'langan:</b> {final_paid:,.2f} so'm\n"
        f"{f'💚 Ortiqcha (balansga): {overpaid:,.2f} so{chr(39)}m{chr(10)}' if overpaid > 0 else ''}"
        f"{f'💰 Hamyondan: {wallet_used:,.2f} so{chr(39)}m{chr(10)}' if wallet_used > 0 else ''}"
        f"📊 <b>Holat:</b> {status_line}\n"
        f"{'━' * 28}\n"
        f"⚖️ <b>Vazn:</b> {vazn} kg\n"
        f"📦 <b>Trek kodlar:</b> {track_display}\n"
        f"{'━' * 28}\n"
        f"📱 <b>Telefon:</b> {client.phone or 'N/A'}\n"
        f"🆔 <b>Telegram:</b> {telegram_id}\n"
        f"👨‍💼 <b>Tasdiqladi:</b> {approver_name}\n"
        f"🕐 <b>Vaqt:</b> {formatted_time}"
    )

    await _send_to_channel(
        bot,
        config.telegram.TOLOV_TASDIQLANGAN_CHANNEL_ID,
        channel_text,
        receipt,
        parse_mode="HTML",
    )

    # --- Update original admin message ---
    approval_msg_id = data.get("approval_message_id")
    approval_chat_id = data.get("approval_chat_id")
    if approval_msg_id and approval_chat_id:
        await _stamp_admin_message(
            bot,
            approval_chat_id,
            approval_msg_id,
            f"✅ Tasdiqlandi: {approver_name}\n💰 Summa: {amount:,.2f} so'm",
        )

    await answer_func(_("admin-payment-success"))
    await state.clear()


# ---------------------------------------------------------------------------
# Handlers: Online Payment Approval
# ---------------------------------------------------------------------------


@payment_approval_router.callback_query(
    IsAdmin(), F.data.startswith("approve_payment:")
)
async def approve_payment_callback(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    redis: Redis,
):
    """Start payment approval — ask admin for the received amount."""
    await safe_answer_callback(callback)

    parts = callback.data.split(":")
    if len(parts) != 3:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    client_code, worksheet = parts[1], parts[2]

    client = await client_service.get_client_by_code(client_code, session)
    if not client:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    from src.bot.handlers.user.make_payment import calculate_flight_payment

    payment_data = await calculate_flight_payment(
        session=session,
        flight_name=worksheet,
        client_code=client.active_codes,
        redis=redis,
    )
    if not payment_data:
        await callback.message.answer(_("error-occurred"))
        return

    expected_amount = payment_data["total_payment"]

    existing_tx = await ClientTransactionDAO.get_by_client_code_flight(
        session, client.active_codes, worksheet
    )
    if existing_tx and existing_tx.payment_status == "partial":
        expected_amount = float(existing_tx.remaining_amount)

    wallet_used = await _get_redis_float(
        redis, f"wallet_used:{client_code}:{worksheet}"
    )
    is_wallet_only = wallet_used >= expected_amount > 0

    await state.update_data(
        approval_telegram_id=client.telegram_id,
        approval_worksheet=worksheet,
        approval_row_number=0,
        approval_client_code=client_code,
        approval_expected_amount=expected_amount,
        approval_message_id=callback.message.message_id,
        approval_chat_id=callback.message.chat.id,
        approval_wallet_used=wallet_used,
        approval_is_wallet_only=is_wallet_only,
    )
    await state.set_state(PaymentApprovalState.waiting_for_amount)

    if is_wallet_only:
        prompt = _(
            "admin-payment-enter-amount-wallet-only",
            total=f"{expected_amount:,.2f}",
            wallet=f"{wallet_used:,.2f}",
        )
    elif wallet_used > 0:
        prompt = _(
            "admin-payment-enter-amount-with-wallet",
            total=f"{expected_amount:,.2f}",
            wallet=f"{wallet_used:,.2f}",
            expected=f"{expected_amount - wallet_used:,.2f}",
        )
    else:
        prompt = _("admin-payment-enter-amount", expected=f"{expected_amount:,.2f}")

    from aiogram.utils.keyboard import InlineKeyboardBuilder as _IKB

    full_pay_builder = _IKB()
    full_pay_builder.button(
        text=f"✅ To'liq to'landi ({expected_amount:,.2f} so'm)",
        callback_data=f"full_pay_approve:{client_code}:{worksheet}",
    )

    hint = (
        f"ℹ️ Istalgan summani kiriting:\n"
        f"• Ko'proq → ortiqcha balansga o'tadi\n"
        f"• Kamroq → qisman to'lov sifatida saqlanadi\n"
        f"• Kutilgan summa: {expected_amount:,.2f} so'm\n\n"
        f"yoki to'liq to'lov uchun quyidagi tugmani bosing 👇"
    )
    await callback.message.answer(prompt)
    await callback.message.answer(hint, reply_markup=full_pay_builder.as_markup())


@payment_approval_router.message(
    IsAdmin(), PaymentApprovalState.waiting_for_amount, F.text
)
async def payment_approval_amount_received(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    state: FSMContext,
    bot: Bot,
    redis: Redis,
):
    """Finalise online payment approval after admin manually enters the amount."""
    if message.text.strip().lower() in ("/cancel", "bekor", "отмена"):
        await message.answer(_("admin-payment-cancelled"))
        await state.clear()
        return

    try:
        amount = parse_money(message.text)
    except (ValueError, TypeError):
        await session.rollback()
        await message.answer(_("admin-payment-invalid-amount"))
        return

    data = await state.get_data()
    is_wallet_only = data.get("approval_is_wallet_only", False)

    if amount < 0 or (amount == 0 and not is_wallet_only):
        await message.answer(_("admin-payment-invalid-amount"))
        return

    await _process_approved_payment(
        amount=amount,
        data=data,
        session=session,
        bot=bot,
        redis=redis,
        client_service=client_service,
        transaction_service=transaction_service,
        approver_id=message.from_user.id,
        approver_name=message.from_user.full_name,
        answer_func=message.answer,
        _=_,
        state=state,
    )


@payment_approval_router.callback_query(
    IsAdmin(), F.data.startswith("full_pay_approve:")
)
async def full_pay_confirmed_callback(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    state: FSMContext,
    bot: Bot,
    redis: Redis,
):
    """Finalise online payment using the full expected amount (one-click shortcut button)."""
    await safe_answer_callback(callback)

    data = await state.get_data()
    if not data or "approval_expected_amount" not in data:
        await callback.message.answer(
            "❌ Ma'lumotlar topilmadi. Qaytadan «Tasdiqlash» tugmasini bosing."
        )
        return

    amount = float(data["approval_expected_amount"])

    # Remove the inline button so the admin can't press it twice
    with contextlib.suppress(Exception):
        await callback.message.edit_reply_markup(reply_markup=None)
    await _process_approved_payment(
        amount=amount,
        data=data,
        session=session,
        bot=bot,
        redis=redis,
        client_service=client_service,
        transaction_service=transaction_service,
        approver_id=callback.from_user.id,
        approver_name=callback.from_user.full_name,
        answer_func=callback.message.answer,
        _=_,
        state=state,
    )


# ---------------------------------------------------------------------------
# Handlers: Payment Rejection
# ---------------------------------------------------------------------------


@payment_approval_router.callback_query(IsAdmin(), F.data.startswith("reject_payment:"))
async def reject_payment_callback(
    callback: CallbackQuery,
    _: callable,
    bot: Bot,
    session: AsyncSession,
    client_service: ClientService,
):
    """Reject payment without comment."""
    await _remove_buttons(callback)
    await safe_answer_callback(callback, _("payment-rejected-success"), show_alert=True)

    parts = callback.data.split(":")
    if len(parts) != 2:
        return

    client_code = parts[1]
    msg_text = callback.message.caption or callback.message.text or ""
    flight_name = _extract_flight_name(msg_text)

    client = await client_service.get_client_by_code(client_code, session)
    user_text = _user_translator(client)

    user_msg = (
        f"⚠️ To'lovingiz (Reys: {flight_name}) rad etildi. Admin bilan bog'laning."
        if flight_name
        else user_text("payment-rejected-user")
    )
    if client:
        await _notify_user(bot, client.telegram_id, user_msg, user_text)

    rejection_suffix = f"\n\n❌ Bekor qilindi: {callback.from_user.full_name}"
    try:
        if callback.message.caption:
            await callback.message.edit_caption(
                caption=callback.message.caption + rejection_suffix, reply_markup=None
            )
        else:
            await callback.message.edit_text(
                text=callback.message.text + rejection_suffix, reply_markup=None
            )
    except Exception as e:
        await session.rollback()
        logger.warning(f"Failed to update group message: {e}")


@payment_approval_router.callback_query(
    IsAdmin(), F.data.startswith("reject_payment_comment:")
)
async def reject_payment_with_comment_callback(
    callback: CallbackQuery, _: callable, state: FSMContext
):
    """Start rejection with comment flow."""
    await _remove_buttons(callback)
    await safe_answer_callback(callback)

    parts = callback.data.split(":")
    if len(parts) != 2:
        return

    client_code = parts[1]
    msg_text = callback.message.caption or callback.message.text or ""
    flight_name = _extract_flight_name(msg_text)

    await state.update_data(
        reject_client_code=client_code,
        reject_message_id=callback.message.message_id,
        reject_chat_id=callback.message.chat.id,
        reject_admin_name=callback.from_user.full_name,
        reject_flight_name=flight_name,
    )
    await state.set_state(RejectCommentState.waiting_for_comment)
    await callback.message.answer(_("payment-rejection-comment-prompt"))


async def _do_rejection(
    bot: Bot,
    session: AsyncSession,
    client_service: ClientService,
    state_data: dict,
    admin_name: str,
    comment: str | None,
    message_chat_id: int,
):
    """Shared logic for both /stop and comment-based rejection."""
    client_code = state_data.get("reject_client_code")
    flight_name = state_data.get("reject_flight_name", "")
    message_id = state_data.get("reject_message_id")
    chat_id = state_data.get("reject_chat_id", message_chat_id)

    client = (
        await client_service.get_client_by_code(client_code, session)
        if client_code
        else None
    )
    user_text = _user_translator(client)

    # User notification
    if comment:
        user_msg = (
            f"⚠️ To'lovingiz (Reys: {flight_name}) rad etildi.\n💬 Sabab: {comment}"
            if flight_name
            else user_text("payment-rejected-with-comment", comment=comment)
        )
    else:
        user_msg = (
            f"⚠️ To'lovingiz (Reys: {flight_name}) rad etildi. Admin bilan bog'laning."
            if flight_name
            else user_text("payment-rejected-user")
        )

    if client:
        await _notify_user(bot, client.telegram_id, user_msg, user_text)

    # Admin message stamp
    if message_id:
        stamp = (
            f"❌ Bekor qilindi (Izoh bilan): {admin_name}\n💬 Izoh: {comment}"
            if comment
            else f"❌ Bekor qilindi: {admin_name}"
        )
        with contextlib.suppress(Exception):
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=stamp
            )


@payment_approval_router.message(IsAdmin(), RejectCommentState.waiting_for_comment)
async def rejection_comment_received(
    message: Message,
    _: callable,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    client_service: ClientService,
):
    """Process rejection comment (or /stop to reject without comment)."""
    data = await state.get_data()
    admin_name = data.get("reject_admin_name", message.from_user.full_name)

    is_stop = message.text and message.text.strip() == "/stop"
    comment = None if is_stop else message.text.strip()

    await _do_rejection(
        bot, session, client_service, data, admin_name, comment, message.chat.id
    )
    await message.answer(_("payment-rejected-success"))
    await state.clear()


# ---------------------------------------------------------------------------
# Handlers: Cash Payment Approval
# ---------------------------------------------------------------------------


@payment_approval_router.callback_query(
    IsAdmin(), F.data.startswith("cash_payment_confirmed:")
)
async def cash_payment_confirmed_callback(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    redis: Redis,
):
    """Start cash payment confirmation — ask admin for the received amount."""
    await _remove_buttons(callback)
    await safe_answer_callback(callback)

    parts = callback.data.split(":")
    if len(parts) != 3:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    client_code, worksheet = parts[1], parts[2]

    client = await client_service.get_client_by_code(client_code, session)
    if not client:
        await safe_answer_callback(callback, _("client-not-found"), show_alert=True)
        return

    from src.bot.handlers.user.make_payment import calculate_flight_payment

    payment_data = await calculate_flight_payment(
        session=session,
        flight_name=worksheet,
        client_code=client.active_codes,
        redis=redis,
    )
    expected_amount = payment_data["total_payment"] if payment_data else 0

    existing_tx = await ClientTransactionDAO.get_by_client_code_flight(
        session, client.active_codes, worksheet
    )
    if existing_tx and existing_tx.payment_status == "partial":
        expected_amount = float(existing_tx.remaining_amount)

    await state.update_data(
        cash_telegram_id=client.telegram_id,
        cash_worksheet=worksheet,
        cash_row_number=0,
        cash_client_code=client_code,
        cash_expected_amount=expected_amount,
        cash_message_id=callback.message.message_id,
        cash_chat_id=callback.message.chat.id,
        cash_is_partial=bool(existing_tx and existing_tx.payment_status == "partial"),
        cash_existing_tx_id=existing_tx.id if existing_tx else None,
    )
    await state.set_state(CashPaymentApprovalState.waiting_for_amount)
    await callback.message.answer(
        _("admin-cash-payment-enter-amount", expected=f"{expected_amount:,.2f}")
    )
    await callback.message.answer(
        f"ℹ️ Istalgan summani kiriting:\n"
        f"• Ko'proq → ortiqcha balansga o'tadi\n"
        f"• Kamroq → qisman to'lov sifatida saqlanadi\n"
        f"• Kutilgan summa: {expected_amount:,.2f} so'm"
    )


@payment_approval_router.message(
    IsAdmin(), CashPaymentApprovalState.waiting_for_amount, F.text
)
async def cash_payment_amount_received(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    state: FSMContext,
    bot: Bot,
    redis: Redis,
):    # sourcery skip: low-code-quality
    """Finalise cash payment approval after admin enters the amount."""
    if message.text.strip().lower() in ("/cancel", "bekor", "отмена"):
        await message.answer(_("admin-payment-cancelled"))
        await state.clear()
        return

    try:
        amount = parse_money(message.text)
    except (ValueError, TypeError):
        await session.rollback()
        await message.answer(_("admin-payment-invalid-amount"))
        return

    if amount <= 0:
        await message.answer(_("admin-payment-invalid-amount"))
        return

    data = await state.get_data()
    telegram_id = data["cash_telegram_id"]
    worksheet = data["cash_worksheet"]
    client_code = data["cash_client_code"]
    expected_amount = data.get("cash_expected_amount", 0)
    admin_message_id = data.get("cash_message_id")
    admin_chat_id = data.get("cash_chat_id")
    is_partial = data.get("cash_is_partial", False)
    existing_tx_id = data.get("cash_existing_tx_id")

    if not client_code or not worksheet:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    client = await client_service.get_client_by_code(client_code, session)
    if not client:
        await message.answer(_("client-not-found"))
        await state.clear()
        return

    from src.infrastructure.tools.datetime_utils import get_current_time
    from src.bot.handlers.user.make_payment import calculate_flight_payment
    from datetime import datetime, timezone

    wallet_used = await _get_redis_float(
        redis, f"wallet_used:{client_code}:{worksheet}"
    )

    # Fetch flight data upfront for both branches (vazn, track_codes, total_expected)
    payment_data = await calculate_flight_payment(
        session=session,
        flight_name=worksheet,
        client_code=client.active_codes,
        redis=redis,
    )
    vazn = payment_data["total_weight"] if payment_data else "N/A"
    track_codes: list[str] = payment_data.get("track_codes", []) if payment_data else []
    track_display = ", ".join(track_codes) if track_codes else "N/A"
    total_expected = payment_data["total_payment"] if payment_data else expected_amount

    # --- Persist payment ---
    if is_partial and existing_tx_id:
        existing_tx = await ClientTransactionDAO.get_by_id(session, existing_tx_id)
        if not existing_tx:
            await message.answer(_("error-occurred"))
            await state.clear()
            return

        await ClientPaymentEventDAO.create(
            session=session,
            transaction_id=existing_tx.id,
            payment_provider="cash",
            amount=amount,
            approved_by_admin_id=message.from_user.id,
            payment_type="cash",
        )
        await PaymentAllocationService.recalculate_transaction_balance(
            session, existing_tx.id
        )
        await session.refresh(existing_tx)

        if existing_tx.remaining_amount <= 0:
            existing_tx.is_taken_away = True
            existing_tx.taken_away_date = get_current_time()

    else:
        total_paid = wallet_used + amount
        pbd = float(amount) - float(total_expected)

        from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO as _FC

        cash_cargo_client_code = (
            await _FC.get_registered_client_code(
                session, worksheet, client.active_codes
            )
            or client_code
        )

        # Re-use a pending-debt row (written by bulk_cargo_sender) if one exists so that
        # the cash approval never creates a second transaction for the same user+flight.
        _pending_debt = None
        if existing_tx_id:
            _looked_up = await ClientTransactionDAO.get_by_id(session, existing_tx_id)
            if _looked_up and _looked_up.payment_status == "pending":
                _pending_debt = _looked_up

        cash_pay_status = "paid" if total_paid >= total_expected else "partial"
        if _pending_debt:
            _pending_debt.client_code = cash_cargo_client_code
            _pending_debt.summa = float(total_expected)
            _pending_debt.vazn = str(vazn)
            _pending_debt.payment_type = "cash"
            _pending_debt.payment_status = cash_pay_status
            _pending_debt.paid_amount = float(amount)
            _pending_debt.total_amount = float(total_expected)
            _pending_debt.remaining_amount = max(0.0, float(total_expected) - total_paid)
            _pending_debt.is_taken_away = True
            _pending_debt.taken_away_date = get_current_time()
            _pending_debt.payment_balance_difference = pbd
            new_tx = _pending_debt
            await session.flush()
        else:
            new_tx = await ClientTransactionDAO.create(
                session,
                {
                    "telegram_id": telegram_id,
                    "client_code": cash_cargo_client_code,
                    "qator_raqami": 0,
                    "reys": worksheet,
                    "summa": float(total_expected),
                    "vazn": str(vazn),
                    "payment_receipt_file_id": None,
                    "payment_type": "cash",
                    "payment_status": cash_pay_status,
                    "paid_amount": float(amount),
                    "total_amount": float(total_expected),
                    "remaining_amount": max(0.0, float(total_expected) - total_paid),
                    "is_taken_away": True,
                    "taken_away_date": get_current_time(),
                    "payment_balance_difference": pbd,
                },
            )
        await ClientPaymentEventDAO.create(
            session=session,
            transaction_id=new_tx.id,
            payment_provider="cash",
            amount=amount,
            approved_by_admin_id=message.from_user.id,
            payment_type="cash",
        )
    await session.commit()
    # --- Build final state for notifications ---
    final_tx = await ClientTransactionDAO.get_by_client_code_flight(
        session, client.active_codes, worksheet
    )
    final_paid = (
        float(final_tx.paid_amount)
        if final_tx and final_tx.paid_amount is not None
        else float(amount)
    )
    final_remaining = (
        float(final_tx.remaining_amount)
        if final_tx and final_tx.remaining_amount is not None
        else 0.0
    )
    final_total = (
        float(final_tx.total_amount)
        if final_tx and final_tx.total_amount is not None
        else float(total_expected)
    )
    is_fully_paid = (final_remaining <= 0) or (amount >= expected_amount)
    overpaid = max(0.0, amount - expected_amount)

    # --- Notify user ---
    user_text = _user_translator(client)
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=user_text("payment-cash-confirmed-user"),
        )
    except Exception as e:
        logger.warning(f"Failed to notify user {telegram_id}: {e}")

    if is_fully_paid and telegram_id:
        webapp_btn = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="📦 1 daqiqada zayavka qoldiring",
                    web_app=WebAppInfo(url=config.telegram.webapp_request_page_url),
                )
            ]]
        )
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=user_text(
                    "payment-approved-full-success",
                    worksheet=worksheet,
                    paid=f"{final_paid:,.2f}",
                    overpaid=overpaid,
                    overpaid_fmt=f"{overpaid:,.2f}",
                ),
                reply_markup=webapp_btn,
            )
        except Exception as e:
            logger.warning(f"Failed to send full-success WebApp message to {telegram_id}: {e}")

    # --- Channel notification ---
    formatted_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payment_emoji = "💵"
    status_line = (
        "✅ To'liq to'landi"
        if is_fully_paid
        else f"⚠️ Qisman to'lov ({final_remaining:,.2f} so'm qoldi)"
    )

    channel_text = (
        f"{'✅' if is_fully_paid else '⚠️'} <b>To'lov tasdiqlandi</b>\n"
        f"{'━' * 28}\n"
        f"👤 <b>Mijoz:</b> <code>{client.client_code}</code>\n"
        f"✈️ <b>Reys:</b> {worksheet}\n"
        f"{'━' * 28}\n"
        f"💰 <b>Jami narx:</b> {final_total:,.2f} so'm\n"
        f"{payment_emoji} <b>To'langan:</b> {final_paid:,.2f} so'm\n"
        f"{f'💚 Ortiqcha (balansga): {overpaid:,.2f} so{chr(39)}m{chr(10)}' if overpaid > 0 else ''}"
        f"{f'💰 Hamyondan: {wallet_used:,.2f} so{chr(39)}m{chr(10)}' if wallet_used > 0 else ''}"
        f"📊 <b>Holat:</b> {status_line}\n"
        f"{'━' * 28}\n"
        f"⚖️ <b>Vazn:</b> {vazn} kg\n"
        f"📦 <b>Trek kodlar:</b> {track_display}\n"
        f"{'━' * 28}\n"
        f"📱 <b>Telefon:</b> {client.phone or 'N/A'}\n"
        f"🆔 <b>Telegram:</b> {telegram_id}\n"
        f"👨‍💼 <b>Tasdiqladi:</b> {message.from_user.full_name}\n"
        f"🕐 <b>Vaqt:</b> {formatted_time}"
    )

    receipt = await _resolve_receipt(redis, client_code, worksheet)
    await _send_to_channel(
        bot,
        config.telegram.TOLOV_TASDIQLANGAN_CHANNEL_ID,
        channel_text,
        receipt,
        parse_mode="HTML",
    )

    # --- Update original admin message ---
    if admin_message_id and admin_chat_id:
        approval_text = _(
            "payment-cash-confirmed-group",
            client_code=client_code,
            worksheet=worksheet,
            row_number=0,
            admin_name=message.from_user.full_name,
        )
        await _stamp_admin_message(
            bot,
            admin_chat_id,
            admin_message_id,
            f"✅ {approval_text}\n💰 Summa: {final_paid:,.2f} so'm",
        )

    await message.answer(_("admin-payment-success"))
    await state.clear()
