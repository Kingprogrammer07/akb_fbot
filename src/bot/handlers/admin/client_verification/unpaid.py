"""Unpaid payments handlers for client verification."""
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.bot.filters.is_admin import IsAdmin
from src.infrastructure.services.client import ClientService
from src.infrastructure.services.client_transaction import ClientTransactionService
from src.infrastructure.services.payment_allocation import PaymentAllocationService
from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.client_payment_event import ClientPaymentEventDAO
from src.infrastructure.tools.money_utils import parse_money
from src.bot.utils.decorators import handle_errors
from src.config import config

from .utils import (
    safe_answer_callback,
    encode_flight_code,
    decode_flight_code_from_cargo,
    get_unpaid_payments_for_client,
    get_cargo_by_id,
    VERIFICATION_CONTEXT
)

router = Router()


class UnpaidCashPaymentState(StatesGroup):
    """State for unpaid cash payment approval with amount input."""
    waiting_for_amount = State()


class UnpaidAccountPaymentState(StatesGroup):
    """State for unpaid account payment approval with amount input."""
    waiting_for_amount = State()


@router.callback_query(F.data.startswith("v:unp:"), IsAdmin())
@handle_errors
async def show_unpaid_payments_list(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    bot: Bot,
    redis: Redis
):
    """Show paginated unpaid payments list with filters and sorting."""
    parts = callback.data.split(":")
    client_code = parts[2]
    filter_type = parts[3] if len(parts) > 3 else "all"
    sort_order = parts[4] if len(parts) > 4 else "desc"
    page = int(parts[5]) if len(parts) > 5 else 0
    flight_hash = parts[6] if len(parts) > 6 and parts[6] != "none" else None

    # Resolve all active aliases so cargos stored under any code variant are found.
    client = await client_service.get_client_by_code(client_code, session)
    if not client:
        await safe_answer_callback(callback, _("client-not-found"), show_alert=True)
        return

    active_codes = client.active_codes
    canonical_code = client.primary_code

    # Decode flight filter from cargo data (not sheets)
    flight_code = None
    if flight_hash and flight_hash != "none":
        flight_code = await decode_flight_code_from_cargo(flight_hash, active_codes, session)

    VERIFICATION_CONTEXT[callback.from_user.id] = {
        "client_code": canonical_code,
        "filter_type": filter_type,
        "sort_order": sort_order,
        "page": page,
        "flight_hash": flight_hash or "none",
        "view_type": "unpaid"
    }

    # Get unpaid cargos from flight_cargo table (source of truth)
    all_unpaid = await get_unpaid_payments_for_client(
        active_codes, session, redis, flight_code
    )

    # Filter is only "pending" for unpaid (no partial since no transaction exists)
    # but keep filter options for UI consistency
    if filter_type == "pending":
        all_unpaid = [u for u in all_unpaid if u["payment_status"] == "pending"]
    # Note: "partial" filter will return empty since unpaid cargos have no transactions

    # Sort by flight_name
    reverse = sort_order == "desc"
    all_unpaid.sort(key=lambda x: x["flight_name"], reverse=reverse)

    if not all_unpaid:
        await safe_answer_callback(callback, _("admin-verification-no-unpaid"), show_alert=True)
        return

    per_page = 3
    offset = page * per_page
    total_count = len(all_unpaid)
    total_pages = (total_count + per_page - 1) // per_page

    page_items = all_unpaid[offset:offset + per_page]
    print(page_items)
    for item in page_items:
        flight_name = item["flight_name"]
        cargo_id = item["cargo_id"]
        total_payment = item["total_payment"]
        weight = item["weight"]

        # Format unpaid item info (always pending status, no partial)
        info_text = _("admin-verification-unpaid-item",
            flight=flight_name,
            row=cargo_id,
            total=f"{total_payment:,.0f}",
            remaining=f"{total_payment:,.0f}",
            date=item["created_at"].strftime('%Y-%m-%d') if item.get("created_at") else "N/A"
        )

        tx_builder = InlineKeyboardBuilder()

        # Payment buttons - use cargo_id as row_number
        tx_builder.button(
            text=_("btn-cash-payment-confirm"),
            callback_data=f"v:ucp:{canonical_code}:{flight_name}:{cargo_id}"
        )

        tx_builder.button(
            text=_("btn-account-payment"),
            callback_data=f"v:uap:{canonical_code}:{flight_name}:{cargo_id}"
        )

        tx_builder.adjust(1)

        await callback.message.answer(
            info_text,
            reply_markup=tx_builder.as_markup()
        )

    # Navigation and filter buttons
    builder = InlineKeyboardBuilder()

    filter_info = ""
    if flight_code:
        filter_info = f"✈️ {flight_code} | "

    # Filter buttons (only "all" and "pending" make sense for unpaid)
    filters = [
        ("all", "btn-filter-all"),
        ("pending", "btn-filter-pending"),
    ]

    for filter_val, filter_label in filters:
        prefix = "✓ " if filter_val == filter_type else ""
        builder.button(
            text=prefix + _(filter_label),
            callback_data=f"v:unp:{canonical_code}:{filter_val}:{sort_order}:0:{flight_hash or 'none'}"
        )
    builder.adjust(2)

    # Sort button
    sort_label = _("btn-sort-oldest") if sort_order == "desc" else _("btn-sort-newest")
    new_sort = "asc" if sort_order == "desc" else "desc"
    builder.row(
        InlineKeyboardBuilder().button(
            text=sort_label,
            callback_data=f"v:unp:{canonical_code}:{filter_type}:{new_sort}:0:{flight_hash or 'none'}"
        ).as_markup().inline_keyboard[0][0]
    )

    # Flight filter button
    if flight_code:
        builder.row(
            InlineKeyboardBuilder().button(
                text=_("btn-clear-flight-filter"),
                callback_data=f"v:unp:{canonical_code}:{filter_type}:{sort_order}:0:none"
            ).as_markup().inline_keyboard[0][0]
        )
    else:
        builder.row(
            InlineKeyboardBuilder().button(
                text=_("btn-filter-by-flight"),
                callback_data=f"v:usf:{canonical_code}"
            ).as_markup().inline_keyboard[0][0]
        )

    # Pagination buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardBuilder().button(
                text=_("btn-previous"),
                callback_data=f"v:unp:{canonical_code}:{filter_type}:{sort_order}:{page - 1}:{flight_hash or 'none'}"
            ).as_markup().inline_keyboard[0][0]
        )

    nav_buttons.append(
        InlineKeyboardBuilder().button(
            text=f"{page + 1}/{total_pages}",
            callback_data="v:pi"
        ).as_markup().inline_keyboard[0][0]
    )

    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardBuilder().button(
                text=_("btn-next"),
                callback_data=f"v:unp:{canonical_code}:{filter_type}:{sort_order}:{page + 1}:{flight_hash or 'none'}"
            ).as_markup().inline_keyboard[0][0]
        )

    if nav_buttons:
        builder.row(*nav_buttons)

    # Back button
    builder.row(
        InlineKeyboardBuilder().button(
            text=_("btn-back"),
            callback_data=f"v:btc:{canonical_code}"
        ).as_markup().inline_keyboard[0][0]
    )

    await callback.message.answer(
        text=filter_info + _("admin-verification-unpaid-nav", current=page + 1, total=total_pages),
        reply_markup=builder.as_markup()
    )

    await safe_answer_callback(callback)


@router.callback_query(F.data.startswith("v:usf:"), IsAdmin())
@handle_errors
async def show_unpaid_flight_selection(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    redis: Redis
):
    """Show flight selection for filtering unpaid payments (from cargo data)."""
    client_code = callback.data.split(":")[2]

    client = await client_service.get_client_by_code(client_code, session)
    if not client:
        await safe_answer_callback(callback, _("client-not-found"), show_alert=True)
        return

    active_codes = client.active_codes
    canonical_code = client.primary_code

    # Get unique flights from sent cargos (source of truth)
    flights = await FlightCargoDAO.get_unique_flights_by_client_sent(session, active_codes)

    if not flights:
        await safe_answer_callback(callback, _("admin-verification-no-flights"), show_alert=True)
        return

    builder = InlineKeyboardBuilder()

    for flight in flights:
        flight_hash = encode_flight_code(flight)
        builder.button(
            text=f"✈️ {flight}",
            callback_data=f"v:unp:{canonical_code}:all:desc:0:{flight_hash}"
        )

    builder.button(
        text=_("btn-back"),
        callback_data=f"v:unp:{canonical_code}:all:desc:0:none"
    )

    builder.adjust(1)

    await callback.message.edit_text(
        _("admin-verification-select-flight-prompt"),
        reply_markup=builder.as_markup()
    )
    await safe_answer_callback(callback)


@router.callback_query(F.data.startswith("v:ucp:"), IsAdmin())
@handle_errors
async def unpaid_cash_payment_start(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    redis: Redis
):
    """
    Start cash payment confirmation for unpaid cargo - ask for amount input.

    Callback format: v:ucp:{client_code}:{flight_name}:{cargo_id}
    """
    await safe_answer_callback(callback)

    parts = callback.data.split(":")
    if len(parts) < 5:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    client_code = parts[2]
    flight_name = parts[3]
    cargo_id = int(parts[4])

    # Get client info
    client = await client_service.get_client_by_code(client_code, session)
    if not client:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    # Get cargo data from flight_cargo table (source of truth)
    cargo_data = await get_cargo_by_id(cargo_id, session)
    if not cargo_data:
        await safe_answer_callback(callback, _("admin-verification-no-cargo-data"), show_alert=True)
        return

    # Verify cargo belongs to this client and flight
    if cargo_data["client_id"].upper() != client_code.upper():
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    if cargo_data["flight_name"].upper() != flight_name.upper():
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    # Verify cargo is sent
    if not cargo_data["is_sent"]:
        await safe_answer_callback(callback, _("admin-verification-no-cargo-data"), show_alert=True)
        return

    # Check if transaction already exists (double-check)
    existing_tx = await ClientTransactionDAO.get_by_client_code_flight_row(
        session, client_code, flight_name, cargo_id
    )
    if existing_tx:
        await safe_answer_callback(callback, _("payment-already-exists"), show_alert=True)
        return

    # Calculate expected amount from cargo
    expected_amount = cargo_data["total_amount"]
    vazn = cargo_data["weight"]

    if expected_amount <= 0:
        await safe_answer_callback(callback, _("admin-verification-no-cargo-data"), show_alert=True)
        return

    # Store context in FSM state
    await state.update_data(
        ucp_client_code=client_code,
        ucp_flight_name=flight_name,
        ucp_cargo_id=cargo_id,
        ucp_telegram_id=client.telegram_id,
        ucp_expected_amount=expected_amount,
        ucp_vazn=vazn,
        ucp_message_id=callback.message.message_id,
        ucp_chat_id=callback.message.chat.id,
        ucp_phone=client.phone
    )

    # Ask for amount input
    await callback.message.answer(
        _("admin-cash-payment-enter-amount", expected=f"{expected_amount:,.0f}")
    )
    await callback.message.answer(
        f"ℹ️ Istalgan summani kiriting:\n"
        f"• Ko'proq → ortiqcha balansga o'tadi\n"
        f"• Kamroq → qisman to'lov sifatida saqlanadi\n"
        f"• Kutilgan summa: {expected_amount:,.2f} so'm"
    )
    await state.set_state(UnpaidCashPaymentState.waiting_for_amount)


@router.message(IsAdmin(), UnpaidCashPaymentState.waiting_for_amount, F.text)
async def unpaid_cash_payment_amount_received(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    state: FSMContext,
    bot: Bot,
    redis: Redis
):
    """Process cash payment amount from admin for unpaid cargo."""
    # Check for cancel
    if message.text.strip().lower() in ["/cancel", "bekor", "отмена"]:
        await message.answer(_("admin-payment-cancelled"))
        await state.clear()
        return

    # Parse amount
    try:
        amount = parse_money(message.text)
    except (ValueError, TypeError):
        await session.rollback()
        await message.answer(_("admin-payment-invalid-amount"))
        return

    if amount <= 0:
        await message.answer(_("admin-payment-invalid-amount"))
        return

    # Get stored context
    data = await state.get_data()
    client_code = data.get("ucp_client_code")
    flight_name = data.get("ucp_flight_name")
    cargo_id = data.get("ucp_cargo_id")
    telegram_id = data.get("ucp_telegram_id")
    expected_amount = data.get("ucp_expected_amount", 0)
    vazn = data.get("ucp_vazn")
    admin_message_id = data.get("ucp_message_id")
    admin_chat_id = data.get("ucp_chat_id")
    phone = data.get("ucp_phone")

    if not client_code or not flight_name:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    from src.infrastructure.tools.datetime_utils import get_current_time

    try:
        # Calculate payment_balance_difference correctly:
        # paid_amount - expected_amount
        # If paid < expected: negative (debt)
        # If paid >= expected: 0 or positive (credit/overpayment)
        payment_balance_diff = float(amount) - float(expected_amount)

        # Create new transaction with correct payment_balance_difference
        tx_data = {
            "telegram_id": telegram_id if telegram_id else 0,
            "client_code": client_code,
            "qator_raqami": cargo_id,
            "reys": flight_name,
            "summa": float(amount),
            "vazn": str(vazn),
            "payment_receipt_file_id": None,
            "payment_type": "cash",
            "payment_status": "paid" if payment_balance_diff >= 0 else "partial",
            "paid_amount": float(amount),
            "total_amount": float(expected_amount),
            "remaining_amount": max(0.0, float(expected_amount) - float(amount)),
            "is_taken_away": True,
            "taken_away_date": get_current_time(),
            "payment_balance_difference": payment_balance_diff,  # Key field!
        }
        new_tx = await ClientTransactionDAO.create(session, tx_data)

        # Create payment event
        await ClientPaymentEventDAO.create(
            session=session,
            transaction_id=new_tx.id,
            payment_type="cash",
            amount=amount,
            approved_by_admin_id=message.from_user.id,
            payment_provider="cash"
        )

        await session.commit()

        # Notify user if telegram_id exists
        if telegram_id:
            try:
                await bot.send_message(
                    chat_id=telegram_id,
                    text=_("payment-cash-confirmed-user")
                )
            except Exception as e:
                await session.rollback()
                print(f"Failed to notify user: {e}")

        # Send to channel
        channel_id = config.telegram.TOLOV_TASDIQLANGAN_CHANNEL_ID
        channel_notification = _(
            "payment-confirmed-channel-cash",
            client_code=client_code,
            worksheet=flight_name,
            summa=f"{amount:.0f} so'm",
            full_name=message.from_user.full_name,
            phone=phone or "N/A",
            telegram_id=str(telegram_id) if telegram_id else "N/A"
        )

        try:
            await bot.send_message(chat_id=channel_id, text=channel_notification)
        except Exception as e:
            await session.rollback()
            print(f"Failed to send to channel: {e}")

        # Update original admin message
        if admin_message_id and admin_chat_id:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=admin_chat_id,
                    message_id=admin_message_id,
                    reply_markup=None
                )
                await bot.send_message(
                    chat_id=admin_chat_id,
                    text=f"✅ Naqd to'lov tasdiqlandi\n👤 Mijoz: {client_code}\n✈️ Reys: {flight_name}\n💰 Summa: {amount:,.0f} so'm",
                    reply_to_message_id=admin_message_id
                )
            except Exception as e:
                await session.rollback()
                print(f"Failed to update admin message: {e}")

        await message.answer(_("admin-payment-success"))

    except Exception as e:
        await session.rollback()
        print(f"Error in unpaid cash payment: {e}")
        await message.answer(_("error-occurred"))

    await state.clear()


@router.callback_query(F.data.startswith("v:uap:"), IsAdmin())
@handle_errors
async def unpaid_account_payment_select_provider(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    redis: Redis
):
    """
    Show provider selection for account payment on unpaid cargo.

    Callback format: v:uap:{client_code}:{flight_name}:{cargo_id}
    """
    parts = callback.data.split(":")
    if len(parts) < 5:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    client_code = parts[2]
    flight_name = parts[3]
    cargo_id = int(parts[4])

    # Get cargo data from flight_cargo table
    cargo_data = await get_cargo_by_id(cargo_id, session)
    if not cargo_data:
        await safe_answer_callback(callback, _("admin-verification-no-cargo-data"), show_alert=True)
        return

    amount = cargo_data["total_amount"]

    if amount <= 0:
        await safe_answer_callback(callback, _("admin-verification-no-cargo-data"), show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("btn-account-payment-click"),
        callback_data=f"v:uapc:{client_code}:{flight_name}:{cargo_id}:click"
    )
    builder.button(
        text=_("btn-account-payment-payme"),
        callback_data=f"v:uapc:{client_code}:{flight_name}:{cargo_id}:payme"
    )
    builder.button(
        text=_("btn-account-payment-cancel"),
        callback_data=f"v:unp:{client_code}:all:desc:0:none"
    )
    builder.adjust(2, 1)

    admin_account_payment_select_provider_text = _("admin-account-payment-select-provider")
    amount_label = _("amount")
    text = f"{admin_account_payment_select_provider_text}\n\n💰 {amount_label}: {amount:,.0f} so'm"

    await callback.message.answer(
        text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await safe_answer_callback(callback)


@router.callback_query(F.data.startswith("v:uapc:"), IsAdmin())
@handle_errors
async def unpaid_account_payment_start(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    redis: Redis
):
    """
    Start account payment for unpaid cargo - ask for amount input.

    Callback format: v:uapc:{client_code}:{flight_name}:{cargo_id}:{provider}
    """
    await safe_answer_callback(callback)

    parts = callback.data.split(":")
    if len(parts) < 6:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    client_code = parts[2]
    flight_name = parts[3]
    cargo_id = int(parts[4])
    provider = parts[5]

    if provider not in ['click', 'payme']:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    # Get client info
    client = await client_service.get_client_by_code(client_code, session)
    if not client:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    # Get cargo data from flight_cargo table (source of truth)
    cargo_data = await get_cargo_by_id(cargo_id, session)
    if not cargo_data:
        await safe_answer_callback(callback, _("admin-verification-no-cargo-data"), show_alert=True)
        return

    # Verify cargo belongs to this client
    if cargo_data["client_id"].upper() != client_code.upper():
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    # Verify cargo is sent
    if not cargo_data["is_sent"]:
        await safe_answer_callback(callback, _("admin-verification-no-cargo-data"), show_alert=True)
        return

    # Check if transaction already exists
    existing_tx = await ClientTransactionDAO.get_by_client_code_flight_row(
        session, client_code, flight_name, cargo_id
    )
    if existing_tx:
        await safe_answer_callback(callback, _("payment-already-exists"), show_alert=True)
        return

    expected_amount = cargo_data["total_amount"]
    vazn = cargo_data["weight"]

    if expected_amount <= 0:
        await safe_answer_callback(callback, _("admin-verification-no-cargo-data"), show_alert=True)
        return

    # Store context in FSM state
    await state.update_data(
        uapc_client_code=client_code,
        uapc_flight_name=flight_name,
        uapc_cargo_id=cargo_id,
        uapc_telegram_id=client.telegram_id,
        uapc_expected_amount=expected_amount,
        uapc_vazn=vazn,
        uapc_provider=provider,
        uapc_message_id=callback.message.message_id,
        uapc_chat_id=callback.message.chat.id
    )

    provider_display = "Click" if provider == "click" else "Payme"

    # Ask for amount input
    await callback.message.answer(
        _("admin-account-payment-enter-amount", expected=f"{expected_amount:,.0f}", provider=provider_display)
    )
    await callback.message.answer(
        f"ℹ️ Istalgan summani kiriting:\n"
        f"• Ko'proq → ortiqcha balansga o'tadi\n"
        f"• Kamroq → qisman to'lov sifatida saqlanadi\n"
        f"• Kutilgan summa: {expected_amount:,.2f} so'm"
    )
    await state.set_state(UnpaidAccountPaymentState.waiting_for_amount)


@router.message(IsAdmin(), UnpaidAccountPaymentState.waiting_for_amount, F.text)
async def unpaid_account_payment_amount_received(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    state: FSMContext,
    bot: Bot,
    redis: Redis
):
    """Process account payment amount from admin for unpaid cargo."""
    # Check for cancel
    if message.text.strip().lower() in ["/cancel", "bekor", "отмена"]:
        await message.answer(_("admin-payment-cancelled"))
        await state.clear()
        return

    # Parse amount
    try:
        amount = parse_money(message.text)
    except (ValueError, TypeError):
        await session.rollback()
        await message.answer(_("admin-payment-invalid-amount"))
        return

    if amount <= 0:
        await message.answer(_("admin-payment-invalid-amount"))
        return

    # Get stored context
    data = await state.get_data()
    client_code = data.get("uapc_client_code")
    flight_name = data.get("uapc_flight_name")
    cargo_id = data.get("uapc_cargo_id")
    telegram_id = data.get("uapc_telegram_id")
    expected_amount = data.get("uapc_expected_amount", 0)
    vazn = data.get("uapc_vazn")
    provider = data.get("uapc_provider")
    admin_message_id = data.get("uapc_message_id")
    admin_chat_id = data.get("uapc_chat_id")

    if not client_code or not flight_name or not provider:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    from src.infrastructure.tools.datetime_utils import get_current_time, to_tashkent

    try:
        # Calculate payment_balance_difference correctly:
        # paid_amount - expected_amount
        # If paid < expected: negative (debt)
        # If paid >= expected: 0 or positive (credit/overpayment)
        payment_balance_diff = float(amount) - float(expected_amount)

        # Create new transaction with correct payment_balance_difference
        tx_data = {
            "telegram_id": telegram_id if telegram_id else 0,
            "client_code": client_code,
            "qator_raqami": cargo_id,
            "reys": flight_name,
            "summa": float(amount),
            "vazn": str(vazn),
            "payment_receipt_file_id": None,
            "payment_type": "online",
            "payment_status": "paid" if payment_balance_diff >= 0 else "partial",
            "paid_amount": float(amount),
            "total_amount": float(expected_amount),
            "remaining_amount": max(0.0, float(expected_amount) - float(amount)),
            "is_taken_away": False,
            "taken_away_date": None,
            "payment_balance_difference": payment_balance_diff,  # Key field!
        }
        new_tx = await ClientTransactionDAO.create(session, tx_data)

        # Create payment event
        await ClientPaymentEventDAO.create(
            session=session,
            transaction_id=new_tx.id,
            payment_type="online",
            amount=amount,
            approved_by_admin_id=message.from_user.id,
            payment_provider=provider
        )

        await session.commit()
        tx_id = new_tx.id

        # Update original admin message
        if admin_message_id and admin_chat_id:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=admin_chat_id,
                    message_id=admin_message_id,
                    reply_markup=None
                )
            except Exception as e:
                await session.rollback()
                print(f"Failed to update admin message: {e}")

        # Send channel notification
        channel_id = config.telegram.TOLOV_TASDIQLANGAN_CHANNEL_ID
        provider_display = "Click" if provider == "click" else "Payme"

        current_time = get_current_time()
        tashkent_time = to_tashkent(current_time)
        formatted_time = tashkent_time.strftime("%Y-%m-%d %H:%M:%S")

        admin_name = message.from_user.full_name
        if message.from_user.username:
            admin_name = f"@{message.from_user.username}"

        channel_text = _("account-payment-channel-notification",
            client_code=client_code,
            transaction_id=tx_id,
            flight=flight_name,
            amount=f"{amount:.0f}",
            provider=provider_display,
            admin_name=admin_name,
            time=formatted_time
        )

        try:
            await bot.send_message(chat_id=channel_id, text=channel_text, parse_mode="HTML")
        except Exception as e:
            await session.rollback()
            print(f"Failed to send notification to channel: {e}")

        await message.answer(_("admin-payment-success"))

    except Exception as e:
        await session.rollback()
        print(f"Error in unpaid account payment: {e}")
        await message.answer(_("error-occurred"))

    await state.clear()
