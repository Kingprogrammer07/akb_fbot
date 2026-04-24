"""Delivery request (Zayavka) handlers."""

import json
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.bot.filters.is_admin import IsAdmin
from src.bot.filters.is_private_chat import IsPrivate
from src.bot.filters.is_logged_in import ClientExists, IsRegistered, IsLoggedIn
from src.bot.utils.decorators import handle_errors
from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.infrastructure.database.dao import ClientTransactionDAO
from src.infrastructure.services import ClientService
from src.infrastructure.database.dao.delivery_request import DeliveryRequestDAO
from src.config import config, BASE_DIR
import math

special_regions = ["Qoraqalpog'iston", "Surxondaryo", "Xorazm"]

delivery_request_router = Router(name="delivery_request")


def calculate_price(total_weight: float, region: str) -> int:
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
    """
    Calculate total weight for a client in a flight.
    """

    transactions = await ClientTransactionDAO.get_by_client_code_and_flight(
        session, client_code, flight_name
    )

    valid = [
        t
        for t in transactions
        if t.payment_status == "paid" and (t.remaining_amount or 0) <= 0
    ]

    return sum(float(t.vazn or 0) for t in valid)


# Delivery types
DELIVERY_TYPES = {
    "uzpost": "delivery-type-uzpost",
    "yandex": "delivery-type-yandex",
    "akb": "delivery-type-akb",
    "bts": "delivery-type-bts",
}

# Region constants for Uzbekistan
UZBEKISTAN_REGIONS = {
    "toshkent_city": "Toshkent shahri",
    "toshkent": "Toshkent viloyati",
    "andijan": "Andijon viloyati",
    "bukhara": "Buxoro viloyati",
    "fergana": "Fargona viloyati",
    "jizzakh": "Jizzax viloyati",
    "kashkadarya": "Qashqadaryo viloyati",
    "navoi": "Navoiy viloyati",
    "namangan": "Namangan viloyati",
    "samarkand": "Samarkand viloyati",
    "sirdarya": "Sirdaryo viloyati",
    "surkhandarya": "Surxondaryo viloyati",
    "karakalpakstan": "Qoraqalpogiston viloyati",
    "khorezm": "Xorazm viloyati",
}


class DeliveryRequestStates(StatesGroup):
    """States for delivery request flow."""

    waiting_for_delivery_type = State()
    waiting_for_profile_confirmation = State()
    waiting_for_flight_selection = State()
    waiting_for_uzpost_payment_receipt = State()


async def get_cached_sheets_data(client_code: str, redis: Redis):
    """Get cached sheets data or fetch from API."""
    cache_key = f"sheets_data:{client_code}"

    # Try to get from cache
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    # If not cached, fetch from API
    checker = GoogleSheetsChecker(
        spreadsheet_id=config.google_sheets.SHEETS_ID,
        api_key=config.google_sheets.API_KEY,
        last_n_sheets=5,
    )

    result = await checker.find_client_group(client_code)

    # Cache for 5 minutes
    if result["found"]:
        await redis.setex(cache_key, 300, json.dumps(result, ensure_ascii=False))

    return result


@delivery_request_router.message(
    IsPrivate(),
    ClientExists(),
    IsRegistered(),
    IsLoggedIn(),
    F.text.in_(["📦 Zayavka qoldirish", "📦 Оставить заявку"]),
)
@handle_errors
async def delivery_request_start(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
):
    """Start delivery request - show delivery type selection."""
    await state.clear()
    # Get client
    client = await client_service.get_client(message.from_user.id, session)

    if not client:
        await message.answer(_("error-occurred"))
        return

    # Create keyboard with delivery types
    builder = InlineKeyboardBuilder()

    for delivery_key, delivery_trans_key in DELIVERY_TYPES.items():
        builder.button(
            text=_(delivery_trans_key), callback_data=f"delivery_type:{delivery_key}"
        )

    builder.adjust(2)  # 2 buttons per row

    await message.answer(_("delivery-select-type"), reply_markup=builder.as_markup())
    await state.set_state(DeliveryRequestStates.waiting_for_delivery_type)


@delivery_request_router.callback_query(
    DeliveryRequestStates.waiting_for_delivery_type, F.data.startswith("delivery_type:")
)
@handle_errors
async def process_delivery_type_selection(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
):
    """Process delivery type selection and show profile confirmation."""
    delivery_type = callback.data.split(":")[1]

    # Store delivery type in state
    await state.update_data(delivery_type=delivery_type)

    # Get client
    client = await client_service.get_client(callback.from_user.id, session)

    if not client:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    # Check if profile is complete
    if not all([client.full_name, client.phone, client.region, client.address]):
        await callback.message.edit_text(_("delivery-incomplete-profile"))
        await state.clear()
        await callback.answer()
        return

    if client.language_code == "ru":
        district_file = BASE_DIR / "locales" / "district_ru.json"
        with open(district_file, "r", encoding="utf-8") as f:
            district_ru = json.load(f)
            district_ru = district_ru.get("districts", {}).get(client.region, {})
    else:
        district_file = BASE_DIR / "locales" / "district_uz.json"
        with open(district_file, "r", encoding="utf-8") as f:
            district_uz = json.load(f)
            district_uz = district_uz.get("districts", {}).get(client.region, {})

    full_address = (
        UZBEKISTAN_REGIONS.get(client.region, client.region)
        + ", "
        + (
            district_ru.get(client.district, client.district)
            if client.language_code == "ru"
            else district_uz.get(client.district, client.district)
        )
    )

    # Show profile confirmation
    profile_text = _(
        "delivery-confirm-profile",
        client_code=client.primary_code,
        full_name=client.full_name,
        phone=client.phone,
        region=full_address,
        address=client.address,
    )

    # Create confirmation keyboard
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_("btn-confirm-profile"), callback_data="confirm_profile_yes"
        ),
        InlineKeyboardButton(
            text=_("btn-edit-profile"), callback_data="confirm_profile_no"
        ),
    )

    await callback.message.edit_text(profile_text, reply_markup=builder.as_markup())
    await state.set_state(DeliveryRequestStates.waiting_for_profile_confirmation)
    await callback.answer()


@delivery_request_router.callback_query(
    DeliveryRequestStates.waiting_for_profile_confirmation,
    F.data == "confirm_profile_no",
)
async def profile_confirmation_no(
    callback: CallbackQuery, _: callable, state: FSMContext
):
    """User wants to edit profile before submitting."""
    await callback.message.edit_text(_("delivery-edit-profile-first"))
    await state.clear()
    await callback.answer()


@delivery_request_router.callback_query(
    DeliveryRequestStates.waiting_for_profile_confirmation,
    F.data == "confirm_profile_yes",
)
@handle_errors
async def profile_confirmation_yes(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    redis: Redis,
    state: FSMContext,
):
    """Profile confirmed - show flight selection."""
    # Get client
    client = await client_service.get_client(callback.from_user.id, session)

    if not client:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    await callback.answer(text=_("please-wait"), show_alert=True)
    # Get flights from Google Sheets
    result = await get_cached_sheets_data(client.client_code, redis)

    if not result["found"] or not result["matches"]:
        await callback.message.edit_text(_("delivery-no-flights"))
        await state.clear()
        await callback.answer()
        return

    # Get delivery type from state
    data = await state.get_data()
    delivery_type = data.get("delivery_type")

    # Filter only PAID flights using client_code + reys + qator_raqami
    from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO

    paid_flights = []
    seen_flights = set()
    for match in result["matches"]:
        flight_name = match["flight_name"]

        # Deduplicate - only check each flight once
        if flight_name in seen_flights:
            continue
        seen_flights.add(flight_name)

        # Check if payment exists for this flight
        is_paid = await ClientTransactionDAO.check_payment_exists(
            session=session, client_code=client.client_code, reys=flight_name
        )

        if is_paid:
            paid_flights.append(
                {
                    "flight_name": flight_name,
                }
            )

    # If no paid flights, inform user
    if not paid_flights:
        await callback.message.edit_text(_("delivery-no-flights"))
        await state.clear()
        return

    # Create flight selection keyboard with only paid flights
    builder = InlineKeyboardBuilder()

    for flight_data in paid_flights:
        flight_name = flight_data["flight_name"]
        builder.button(
            text=f"✈️ {flight_name}", callback_data=f"select_flight:{flight_name}"
        )

    # Add "Done" button for all delivery types (multiple selection)
    builder.button(
        text=_("btn-done-selecting-flights"), callback_data="flights_selected_done"
    )

    builder.adjust(1)

    # All delivery types use multiple selection
    message_key = "delivery-select-flights-multiple"

    await callback.message.edit_text(_(message_key), reply_markup=builder.as_markup())
    await state.update_data(selected_flights=[], paid_flights=paid_flights)
    await state.set_state(DeliveryRequestStates.waiting_for_flight_selection)


@delivery_request_router.callback_query(
    DeliveryRequestStates.waiting_for_flight_selection,
    F.data.startswith("select_flight:"),
)
@handle_errors
async def process_flight_selection(
    callback: CallbackQuery, _: callable, state: FSMContext
):
    """Process flight selection - ALL delivery types use multiple selection."""
    flight_name = callback.data.split(":")[1]

    # Get data from state
    data = await state.get_data()
    selected_flights = data.get("selected_flights", [])
    paid_flights = data.get("paid_flights", [])

    # Multiple selection mode - toggle selection
    if flight_name in selected_flights:
        selected_flights.remove(flight_name)
    else:
        selected_flights.append(flight_name)

    await state.update_data(selected_flights=selected_flights)

    # Rebuild keyboard with checkmarks using only paid flights
    builder = InlineKeyboardBuilder()

    for flight_data in paid_flights:
        fname = flight_data["flight_name"]
        checkmark = "✅ " if fname in selected_flights else ""
        builder.button(
            text=f"{checkmark}✈️ {fname}", callback_data=f"select_flight:{fname}"
        )

    builder.button(
        text=_("btn-done-selecting-flights"), callback_data="flights_selected_done"
    )
    builder.adjust(1)

    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()


async def _check_rate_limit_bot(session: AsyncSession, client_id: int, requesting_flights: list[str]) -> str | None:
    """Check if the user requested any of these flights within the last hour. Returns error message if so."""
    recent_requests = await DeliveryRequestDAO.get_recent_requests_by_client(session, client_id, hours=1)
    
    for req in recent_requests:
        if not req.flight_names:
            continue
        try:
            req_flights = json.loads(req.flight_names)
            overlap = set(requesting_flights).intersection(set(req_flights))
            if overlap:
                return f"Siz {', '.join(overlap)} reys(lar)i uchun so'nggi 1 soat ichida zayavka yuborgansiz. Iltimos biroz kuting."
        except json.JSONDecodeError:
            pass
    return None


@delivery_request_router.callback_query(
    DeliveryRequestStates.waiting_for_flight_selection,
    F.data == "flight_selection_done",
)
@handle_errors
async def process_flight_selection_done(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    bot: Bot,
    redis: Redis,
):
    """User finished selecting flights - all flights shown are already verified as paid."""
    # Get data from state
    data = await state.get_data()
    selected_flights = data.get("selected_flights", [])
    delivery_type: str = data.get("delivery_type")

    if not selected_flights:
        await callback.answer(_("delivery-no-flights-selected"), show_alert=True)
        return

    # Get client
    client = await client_service.get_client(callback.from_user.id, session)
    
    rate_limit_error = await _check_rate_limit_bot(session, client.id, selected_flights)
    if rate_limit_error:
        await callback.answer(rate_limit_error, show_alert=True)
        return

    # UZPOST - show prepayment info with weight and price calculation
    if delivery_type == "uzpost":
        # Calculate total weight for UZPOST delivery
        total_weight = 0

        for flight_name in selected_flights:
            # Calculate total weight for each flight
            weight = await calculate_total_weight(
                session, flight_name, client.active_codes
            )

            if weight:
                total_weight += weight

        # Calculate price based on region
        # Standard: 15,000 som/kg
        # Qoraqalpoq, Surxondaryo, Xorazm: 18,000 som/kg
        price_per_kg = 18000 if client.region in special_regions else 15000
        total_amount = calculate_price(total_weight, client.region)

        if total_weight > 20:
            warning_text = _(
                "delivery-uzpost-payment-info_warning",
                total_weight=f"{total_weight:.2f}",
                price_per_kg=f"{price_per_kg:,}",
                total_amount=f"{total_amount:,}",
                flights=", ".join(selected_flights),
            )
            await callback.message.edit_text(warning_text)
            await callback.answer()
            return

        from src.infrastructure.services import PaymentCardService

        # Get payment card
        payment_card_service = PaymentCardService()
        card = await payment_card_service.get_random_active_card(session)

        if not card:
            await callback.answer(_("payment-no-cards"), show_alert=True)
            return

        # Check wallet balance
        wallet_balance = (
            await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
                session, client.active_codes
            )
        )

        # Calculate wallet usage
        wallet_used = 0
        final_payable_amount = total_amount
        use_wallet = data.get("use_wallet", False)

        if use_wallet and wallet_balance > 0:
            wallet_used = min(wallet_balance, total_amount)
            final_payable_amount = total_amount - wallet_used

        # Store wallet info in FSM
        await state.update_data(
            total_amount=total_amount,
            total_weight=total_weight,
            wallet_balance=wallet_balance,
            wallet_used=wallet_used,
            final_payable_amount=final_payable_amount,
            use_wallet=use_wallet,
        )

        # Show payment info for UZPOST prepayment
        if use_wallet and wallet_used > 0:
            if final_payable_amount <= 0:
                # Wallet covers full amount — wallet-only message (no card info needed)
                payment_text = _(
                    "delivery-uzpost-wallet-only-info",
                    total_weight=f"{total_weight:.2f}",
                    total_amount=f"{total_amount:,}",
                    wallet_used=f"{wallet_used:,.0f}",
                    flights=", ".join(selected_flights),
                )
            else:
                payment_text = _(
                    "delivery-uzpost-payment-info-with-wallet",
                    total_weight=f"{total_weight:.2f}",
                    price_per_kg=f"{price_per_kg:,}",
                    total_amount=f"{total_amount:,}",
                    wallet_used=f"{wallet_used:,.0f}",
                    final_payable=f"{final_payable_amount:,.0f}",
                    card_number=card.card_number,
                    card_owner=card.full_name,
                    flights=", ".join(selected_flights),
                )
        else:
            payment_text = _(
                "delivery-uzpost-payment-info",
                total_weight=f"{total_weight:.2f}",
                price_per_kg=f"{price_per_kg:,}",
                total_amount=f"{total_amount:,}",
                card_number=card.card_number,
                card_owner=card.full_name,
                flights=", ".join(selected_flights),
            )

        # Add wallet toggle button if wallet balance exists
        builder = InlineKeyboardBuilder()
        if wallet_balance > 0:
            wallet_toggle_text = "✅ " if use_wallet else ""
            builder.button(
                text=wallet_toggle_text + _("btn-use-wallet"),
                callback_data="uzpost_toggle_wallet",
            )

        # Always set state so toggle button works in both paths
        await state.set_state(DeliveryRequestStates.waiting_for_uzpost_payment_receipt)

        if use_wallet and final_payable_amount <= 0:
            # Wallet-only: show submit button (no receipt needed)
            builder.button(
                text=_("btn-payment-wallet-only"),
                callback_data="uzpost_wallet_only_submit",
            )
            builder.adjust(1)
            await callback.message.edit_text(
                payment_text, reply_markup=builder.as_markup()
            )
        else:
            # Normal flow: show receipt prompt
            builder.adjust(1)
            if wallet_balance > 0:
                await callback.message.edit_text(
                    payment_text, reply_markup=builder.as_markup()
                )
            else:
                await callback.message.edit_text(payment_text)
            await callback.message.answer(_("delivery-uzpost-send-receipt"))
        await callback.answer()

    else:
        # Other delivery types (Yandex, AKB, BTS) - direct submission
        # All flights are already verified as paid, so we can proceed
        delivery_request = await DeliveryRequestDAO.create(
            session=session,
            client_id=client.id,
            client_code=client.client_code,
            telegram_id=client.telegram_id,
            delivery_type=delivery_type,
            flight_names=json.dumps(selected_flights, ensure_ascii=False),
            full_name=client.full_name,
            phone=client.phone,
            region=client.region,
            address=client.address,
        )
        await session.commit()

        # Send to admin channel
        key = f"{delivery_type.upper()}_DELIVERY_REQUEST_CHANNEL_ID"
        admin_group_id = getattr(config.telegram, key)

        admin_text = _(
            "delivery-admin-new-request",
            request_id=delivery_request.id,
            client_code=client.client_code,
            full_name=client.full_name,
            phone=client.phone,
            delivery_type=_(DELIVERY_TYPES[delivery_type]),
            flights=", ".join(selected_flights),
            region=client.region,
            address=client.address,
        )

        # Create admin approval keyboard
        admin_builder = InlineKeyboardBuilder()
        admin_builder.row(
            InlineKeyboardButton(
                text=_("btn-approve-delivery"),
                callback_data=f"approve_delivery:{delivery_request.id}",
            )
        )
        admin_builder.row(
            InlineKeyboardButton(
                text=_("btn-reject-delivery"),
                callback_data=f"reject_delivery:{delivery_request.id}",
            )
        )

        await bot.send_message(
            chat_id=admin_group_id,
            text=admin_text,
            reply_markup=admin_builder.as_markup(),
        )

        # Notify user
        await callback.message.edit_text(_("delivery-request-submitted"))
        await state.clear()
        await callback.answer()


@delivery_request_router.callback_query(
    DeliveryRequestStates.waiting_for_uzpost_payment_receipt,
    F.data == "uzpost_toggle_wallet",
)
@handle_errors
async def uzpost_toggle_wallet(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
):
    """Toggle wallet usage for UZPOST delivery payment."""
    # Get client
    client = await client_service.get_client(callback.from_user.id, session)

    if not client:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    # Get data from state
    data = await state.get_data()
    total_amount = data.get("total_amount", 0)
    total_weight = data.get("total_weight", 0)
    wallet_balance = data.get("wallet_balance", 0)
    selected_flights = data.get("selected_flights", [])

    # Toggle wallet usage
    use_wallet = not data.get("use_wallet", False)

    # Calculate wallet usage
    wallet_used = 0
    final_payable_amount = total_amount

    if use_wallet and wallet_balance > 0:
        wallet_used = min(wallet_balance, total_amount)
        final_payable_amount = total_amount - wallet_used

    # Update FSM
    await state.update_data(
        use_wallet=use_wallet,
        wallet_used=wallet_used,
        final_payable_amount=final_payable_amount,
    )

    # Get payment card info
    from src.infrastructure.services import PaymentCardService

    payment_card_service = PaymentCardService()
    card = await payment_card_service.get_random_active_card(session)

    if not card:
        await callback.answer(_("payment-no-cards"), show_alert=True)
        return

    # Calculate price per kg based on region
    price_per_kg = 18000 if client.region in special_regions else 15000

    # Build message
    if use_wallet and wallet_used > 0:
        if final_payable_amount <= 0:
            # Wallet covers full amount
            payment_text = _(
                "delivery-uzpost-wallet-only-info",
                total_weight=f"{total_weight:.2f}",
                total_amount=f"{total_amount:,}",
                wallet_used=f"{wallet_used:,.0f}",
                flights=", ".join(selected_flights),
            )
        else:
            payment_text = _(
                "delivery-uzpost-payment-info-with-wallet",
                total_weight=f"{total_weight:.2f}",
                price_per_kg=f"{price_per_kg:,}",
                total_amount=f"{total_amount:,}",
                wallet_used=f"{wallet_used:,.0f}",
                final_payable=f"{final_payable_amount:,.0f}",
                card_number=card.card_number,
                card_owner=card.full_name,
                flights=", ".join(selected_flights),
            )
    else:
        payment_text = _(
            "delivery-uzpost-payment-info",
            total_weight=f"{total_weight:.2f}",
            price_per_kg=f"{price_per_kg:,}",
            total_amount=f"{total_amount:,}",
            card_number=card.card_number,
            card_owner=card.full_name,
            flights=", ".join(selected_flights),
        )

    # Rebuild keyboard
    builder = InlineKeyboardBuilder()
    wallet_toggle_text = "✅ " if use_wallet else ""
    builder.button(
        text=wallet_toggle_text + _("btn-use-wallet"),
        callback_data="uzpost_toggle_wallet",
    )

    if use_wallet and final_payable_amount <= 0:
        # Wallet-only: add submit button, no receipt needed
        builder.button(
            text=_("btn-payment-wallet-only"), callback_data="uzpost_wallet_only_submit"
        )

    builder.adjust(1)

    await callback.message.edit_text(payment_text, reply_markup=builder.as_markup())
    await callback.answer()


@delivery_request_router.callback_query(
    DeliveryRequestStates.waiting_for_uzpost_payment_receipt,
    F.data == "uzpost_wallet_only_submit",
)
@handle_errors
async def uzpost_wallet_only_submit(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    bot: Bot,
    redis: Redis,
):
    """Handle UZPOST wallet-only delivery payment — no receipt needed, sends to admin."""
    await callback.answer()

    # Get client
    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    # Get data from state
    data = await state.get_data()
    selected_flights = data.get("selected_flights", [])
    delivery_type = data.get("delivery_type")
    wallet_used = data.get("wallet_used", 0)
    total_amount = data.get("total_amount", 0)

    if wallet_used <= 0 or wallet_used < total_amount:
        await callback.message.answer(_("error-occurred"))
        return

    # Store wallet_used in Redis for admin approval (MANDATORY)
    primary_flight = selected_flights[0] if selected_flights else "UZPOST"
    wallet_cache_key = (
        f"wallet_used:{client.telegram_id}:{client.client_code}:{primary_flight}"
    )
    await redis.setex(wallet_cache_key, 86400, str(wallet_used))

    # Create delivery request (no receipt)
    delivery_request = await DeliveryRequestDAO.create(
        session=session,
        client_id=client.id,
        client_code=client.client_code,
        telegram_id=client.telegram_id,
        delivery_type=delivery_type,
        flight_names=json.dumps(selected_flights, ensure_ascii=False),
        full_name=client.full_name,
        phone=client.phone,
        region=client.region,
        address=client.address,
        prepayment_receipt_file_id=None,
    )
    await session.commit()

    # Build admin notification with wallet info
    admin_text = _(
        "delivery-admin-new-request",
        request_id=delivery_request.id,
        client_code=client.client_code,
        full_name=client.full_name,
        phone=client.phone,
        delivery_type=_(DELIVERY_TYPES[delivery_type]),
        flights=", ".join(selected_flights),
        region=client.region,
        address=client.address,
    )
    # Append wallet info
    admin_text += (
        f"\n\n💰 Hamyondan: {wallet_used:,.0f} so'm"
        f"\n💵 Qo'shimcha to'lov: 0 so'm"
        f"\n⚠️ Faqat hamyon hisobidan to'lov"
    )

    # Send to UZPOST admin channel
    admin_group_id = config.telegram.UZPOST_TOLOVLARNI_TASDIQLASH_GROUP_ID

    admin_builder = InlineKeyboardBuilder()
    admin_builder.row(
        InlineKeyboardButton(
            text=_("btn-approve-delivery"),
            callback_data=f"approve_delivery:{delivery_request.id}",
        )
    )
    admin_builder.row(
        InlineKeyboardButton(
            text=_("btn-reject-delivery"),
            callback_data=f"reject_delivery:{delivery_request.id}",
        )
    )

    await bot.send_message(
        chat_id=admin_group_id, text=admin_text, reply_markup=admin_builder.as_markup()
    )

    # Notify user — wallet-only, waiting for admin approval
    await callback.message.edit_text(
        _("delivery-wallet-only-submitted", amount=f"{wallet_used:,.0f}")
    )
    await state.clear()


@delivery_request_router.message(
    DeliveryRequestStates.waiting_for_uzpost_payment_receipt,
    F.content_type.in_(["photo", "document"]),
)
@handle_errors
async def uzpost_receipt_received(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    bot: Bot,
    redis: Redis,
):
    """Process UZPOST prepayment receipt."""
    # Get client
    client = await client_service.get_client(message.from_user.id, session)

    if not client:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    # Get data from state
    data = await state.get_data()
    selected_flights = data.get("selected_flights", [])
    delivery_type = data.get("delivery_type")
    wallet_used = data.get("wallet_used", 0)

    # Get file_id
    receipt_file_id = None
    if message.photo:
        receipt_file_id = message.photo[-1].file_id
    elif message.document:
        receipt_file_id = message.document.file_id

    # Store wallet_used in Redis for admin approval (same key format as make_payment)
    if wallet_used > 0 and redis:
        # Use first flight for key (delivery requests can have multiple flights)
        primary_flight = selected_flights[0] if selected_flights else "UZPOST"
        wallet_cache_key = (
            f"wallet_used:{client.telegram_id}:{client.client_code}:{primary_flight}"
        )
        await redis.setex(
            wallet_cache_key, 86400, str(wallet_used)
        )  # Cache for 24 hours

    # Create delivery request
    delivery_request = await DeliveryRequestDAO.create(
        session=session,
        client_id=client.id,
        client_code=client.client_code,
        telegram_id=client.telegram_id,
        delivery_type=delivery_type,
        flight_names=json.dumps(selected_flights, ensure_ascii=False),
        full_name=client.full_name,
        phone=client.phone,
        region=client.region,
        address=client.address,
        prepayment_receipt_file_id=receipt_file_id,
    )
    await session.commit()

    # Send to UZPOST admin channel with receipt
    admin_group_id = config.telegram.UZPOST_TOLOVLARNI_TASDIQLASH_GROUP_ID

    admin_text = _(
        "delivery-admin-new-request",
        request_id=delivery_request.id,
        client_code=client.client_code,
        full_name=client.full_name,
        phone=client.phone,
        delivery_type=_(DELIVERY_TYPES[delivery_type]),
        flights=", ".join(selected_flights),
        region=client.region,
        address=client.address,
    )

    # Add wallet info to admin message if wallet was used
    if wallet_used > 0:
        final_payable = data.get("final_payable_amount", 0)
        admin_text += (
            f"\n\n💰 Hamyondan: {wallet_used:,.0f} so'm"
            f"\n💵 Qo'shimcha to'lov: {final_payable:,.0f} so'm"
        )

    # Create admin approval keyboard
    admin_builder = InlineKeyboardBuilder()
    admin_builder.row(
        InlineKeyboardButton(
            text=_("btn-approve-delivery"),
            callback_data=f"approve_delivery:{delivery_request.id}",
        )
    )
    admin_builder.row(
        InlineKeyboardButton(
            text=_("btn-reject-delivery"),
            callback_data=f"reject_delivery:{delivery_request.id}",
        )
    )

    # Send with receipt
    if message.photo:
        await bot.send_photo(
            chat_id=admin_group_id,
            photo=receipt_file_id,
            caption=admin_text,
            reply_markup=admin_builder.as_markup(),
        )
    elif message.document:
        await bot.send_document(
            chat_id=admin_group_id,
            document=receipt_file_id,
            caption=admin_text,
            reply_markup=admin_builder.as_markup(),
        )

    # Notify user
    await message.answer(_("delivery-request-submitted"))
    await state.clear()


# Admin handlers for approval/rejection
@delivery_request_router.callback_query(
    IsAdmin(), F.data.startswith("approve_delivery:")
)
@handle_errors
async def approve_delivery_request(
    callback: CallbackQuery, _: callable, session: AsyncSession, bot: Bot, redis: Redis
):
    """Admin approves delivery request."""
    request_id = int(callback.data.split(":")[1])

    # Approve request
    delivery_request = await DeliveryRequestDAO.approve(
        session=session, request_id=request_id, admin_id=callback.from_user.id
    )

    if not delivery_request:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    # Get client code and telegram_id
    client_code = delivery_request.client_code
    telegram_id = delivery_request.telegram_id

    # selected_flights ni olish
    try:
        selected_flights: list[str] = json.loads(delivery_request.flight_names)
    except Exception:
        await session.rollback()
        selected_flights = []

    # For UZPOST delivery type, retrieve wallet_used from Redis and apply wallet deduction
    if delivery_request.delivery_type == "uzpost" and selected_flights:
        # Use first flight for Redis key (same as user-side storage)
        primary_flight = selected_flights[0]
        wallet_cache_key = f"wallet_used:{telegram_id}:{client_code}:{primary_flight}"

        # Retrieve wallet_used from Redis
        wallet_used_raw = await redis.get(wallet_cache_key)
        wallet_used = 0
        if wallet_used_raw:
            try:
                if isinstance(wallet_used_raw, bytes):
                    wallet_used = float(wallet_used_raw.decode("utf-8"))
                elif isinstance(wallet_used_raw, str):
                    wallet_used = float(wallet_used_raw)
                else:
                    wallet_used = float(wallet_used_raw)
            except (ValueError, TypeError):
                await session.rollback()
                wallet_used = 0

        # If wallet was used, deduct from wallet by adjusting pbd on the
        # existing real flight transaction. Do NOT create a separate UZPOST_*
        # row — that would pollute the API and act like WALLET_ADJ.
        if wallet_used > 0:
            # Find the existing real transaction for primary_flight
            existing_tx = await ClientTransactionDAO.get_by_client_code_flight(
                session, client_code, primary_flight
            )

            if existing_tx:
                # Subtract wallet_used from pbd on the real transaction
                # This deducts wallet balance without creating a fake row
                current_pbd = float(existing_tx.payment_balance_difference or 0)
                existing_tx.payment_balance_difference = current_pbd - float(
                    wallet_used
                )
                await session.flush()
            else:
                # Fallback: no existing transaction found — should not happen
                # since UZPOST delivery requires paid flights, but log for safety
                import logging

                logging.getLogger(__name__).warning(
                    f"UZPOST wallet deduction: no existing tx for {client_code}/{primary_flight}, "
                    f"wallet_used={wallet_used}. Wallet deduction skipped."
                )

            # Delete wallet cache after successful application
            await redis.delete(wallet_cache_key)

    # Get client to access both client_code and extra_code
    from src.infrastructure.database.dao.client import ClientDAO

    client_obj = await ClientDAO.get_by_client_code(session, client_code)
    client_codes_list = [client_code]
    if client_obj and client_obj.extra_code:
        client_codes_list.append(client_obj.extra_code)

    await ClientTransactionDAO.mark_as_taken_by_client_and_flights(
        session=session, client_codes=client_codes_list, flights=selected_flights
    )
    await session.commit()

    # For UZPOST: forward approved request to the delivery channel
    if delivery_request.delivery_type == "uzpost":
        try:
            uzpost_channel_id = config.telegram.UZPOST_DELIVERY_REQUEST_CHANNEL_ID
            uzpost_channel_text = (
                f"✅ <b>UzPost zayavkasi tasdiqlandi</b>\n\n"
                f"🆔 Zayavka: #{delivery_request.id}\n"
                f"👤 Mijoz: <b>{delivery_request.full_name}</b> "
                f"(<code>{delivery_request.client_code}</code>)\n"
                f"📞 Telefon: {delivery_request.phone}\n"
                f"✈️ Reyslar: {', '.join(selected_flights)}\n"
                f"📍 Viloyat: {delivery_request.region}\n"
                f"🏠 Manzil: {delivery_request.address}\n"
                f"👷 Tasdiqlagan: {callback.from_user.full_name}"
            )
            await bot.send_message(
                chat_id=uzpost_channel_id,
                text=uzpost_channel_text,
                parse_mode="HTML",
            )
        except Exception as _exc:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "UZPOST channel notification failed for request #%d: %s",
                delivery_request.id, _exc,
            )

    # Notify user
    await bot.send_message(
        chat_id=delivery_request.telegram_id, text=_("delivery-request-approved")
    )
    try:
        # Update admin message
        await callback.message.edit_caption(
            caption=callback.message.caption
            + f"\n\n✅ Tasdiqlandi: {callback.from_user.full_name}"
        )
    except:
        # Update admin message
        await callback.message.edit_text(
            text=callback.message.text
            + f"\n\n✅ Tasdiqlandi: {callback.from_user.full_name}"
        )
    await callback.answer(_("delivery-approved-by-admin"))


@delivery_request_router.callback_query(
    IsAdmin(), F.data.startswith("reject_delivery:")
)
@handle_errors
async def reject_delivery_request(
    callback: CallbackQuery, _: callable, session: AsyncSession, bot: Bot
):
    """Admin rejects delivery request."""
    request_id = int(callback.data.split(":")[1])

    # Reject request
    delivery_request = await DeliveryRequestDAO.reject(
        session=session, request_id=request_id, admin_id=callback.from_user.id
    )

    if not delivery_request:
        await callback.answer(_("error-occurred"), show_alert=True)
        return

    await session.commit()

    # Notify user
    await bot.send_message(
        chat_id=delivery_request.telegram_id, text=_("delivery-request-rejected")
    )

    try:
        # Update admin message
        await callback.message.edit_text(
            text=callback.message.text
            + f"\n\n❌ Rad etildi: {callback.from_user.full_name}"
        )
    except:
        # Update admin message
        await callback.message.edit_caption(
            caption=callback.message.caption
            + f"\n\n❌ Rad etildi: {callback.from_user.full_name}"
        )
    await callback.answer(_("delivery-rejected-by-admin"))
