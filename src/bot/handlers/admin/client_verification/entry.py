"""Entry handlers for client verification - initial search and client lookup."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_private_chat import IsPrivate
from src.bot.filters.is_admin import IsAdmin
from src.bot.states.client_verification import ClientVerificationStates
from src.infrastructure.services.client import ClientService
from src.infrastructure.services.client_transaction import ClientTransactionService
from src.bot.utils.decorators import handle_errors
from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.bot.keyboards.reply_kb.general_keyb import cancel_kyb
from src.config import config
from src.infrastructure.database.dao.client import ClientDAO

from .utils import safe_answer_callback

router = Router()


@router.message(F.text.in_(["✅ Foydalanuvchi tekshirish", "✅ Проверка пользователя"]), IsPrivate(), IsAdmin())
@handle_errors
async def open_verification_webapp_handler(message: Message, _: callable):
    """Send inline keyboard with WebApp button for client verification."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=_("btn-open-verification-webapp"),
                web_app=WebAppInfo(url=config.telegram.webapp_verification_search)
            )
        ]
    ])

    await message.answer(
        text=_("msg-click-to-open-verification"),
        reply_markup=kb
    )


# @router.message(F.text.in_(["✅ Foydalanuvchi tekshirish", "✅ Проверка пользователя"]), IsPrivate(), IsAdmin())
@handle_errors
async def start_client_verification(
    message: Message,
    _: callable,
    state: FSMContext
):
    """Start client verification flow - Ask for client code directly."""
    await state.set_state(ClientVerificationStates.waiting_for_client_code)
    await message.answer(
        _("admin-verification-ask-client-code"),
        reply_markup=cancel_kyb(_)
    )


@router.message(ClientVerificationStates.waiting_for_client_code, IsAdmin())
@handle_errors
async def process_client_code_verification(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    state: FSMContext
):
    """Process client code or phone and show verification results with Google Sheets integration."""
    query = message.text.strip()

    # Check if this looks like a phone number (contains mostly digits)
    digits_only = ''.join(c for c in query if c.isdigit())
    is_phone_query = len(digits_only) >= 7  # Phone numbers have at least 7 digits

    client = None

    if is_phone_query:
        # Search by phone number
        client = await ClientDAO.search_by_client_code_or_phone(session, query)
    else:
        # Search by client code
        client_code = query.upper()
        client = await client_service.get_client_by_code(client_code, session)

    if not client:
        await message.answer(
            _("admin-verification-client-not-found"),
            reply_markup=cancel_kyb(_)
        )
        return

    await state.clear()

    # Use all active codes (extra_code, client_code, legacy_code) so that
    # transactions/cargo stored under any alias are counted correctly.
    active_codes = client.active_codes
    canonical_code = client.primary_code

    total_payments = await transaction_service.count_transactions_by_client_code(
        active_codes, session
    )
    taken_away_count = await transaction_service.count_taken_away_by_client_code(
        active_codes, session
    )

    db_flights = await transaction_service.get_unique_flights_by_client_code(
        active_codes, session
    )

    sheets_flights = []
    try:
        checker = GoogleSheetsChecker(
            spreadsheet_id=config.google.SPREADSHEET_ID,
            api_key=config.google.API_KEY
        )
        # Search Google Sheets with the canonical code (highest-priority alias).
        result = await checker.find_client_group(canonical_code, reverse=True)

        if result.get("found") and result.get("matches"):
            for match in result["matches"]:
                sheet_name = match.get("worksheet", "")
                if sheet_name and sheet_name not in sheets_flights:
                    sheets_flights.append(sheet_name)
    except Exception:
        await session.rollback()
        pass

    all_flights = list(set(db_flights + sheets_flights))
    all_flights.sort(reverse=True)

    info_text = _("admin-verification-client-found",
        client_code=client.client_code or canonical_code,
        full_name=client.full_name,
        telegram_id=str(client.telegram_id) if client.telegram_id else _("not-provided"),
        total_payments=total_payments,
        taken_away=taken_away_count
    )

    if all_flights:
        admin_verification_flights_label = _("admin-verification-flights")
        info_text += f"\n\n🛫 {admin_verification_flights_label}: {', '.join(all_flights)}"

    builder = InlineKeyboardBuilder()

    builder.button(
        text=_("btn-verification-full-info"),
        callback_data=f"v:fi:{client.id}"
    )

    if all_flights:
        builder.button(
            text=_("btn-verification-select-flight"),
            callback_data=f"v:sf:{canonical_code}"
        )

    builder.button(
        text=_("btn-verification-all-payments"),
        callback_data=f"v:pay:{canonical_code}:all:desc:0:none"
    )

    builder.button(
        text=_("btn-verification-unpaid-payments"),
        callback_data=f"v:unp:{canonical_code}:all:desc:0:none"
    )

    builder.adjust(1)

    await message.answer(
        text=info_text,
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("v:btc:"), IsAdmin())
@handle_errors
async def back_to_client_info(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService
):
    """Go back to client info from flight selection."""
    client_code = callback.data.split(":")[2]

    client = await client_service.get_client_by_code(client_code, session)

    if not client:
        await safe_answer_callback(callback, _("client-not-found"), show_alert=True)
        return

    active_codes = client.active_codes
    canonical_code = client.primary_code

    total_payments = await transaction_service.count_transactions_by_client_code(
        active_codes, session
    )
    taken_away_count = await transaction_service.count_taken_away_by_client_code(
        active_codes, session
    )

    db_flights = await transaction_service.get_unique_flights_by_client_code(
        active_codes, session
    )

    sheets_flights = []
    try:
        checker = GoogleSheetsChecker(
            spreadsheet_id=config.google.SPREADSHEET_ID,
            api_key=config.google.API_KEY
        )
        result = await checker.find_client_group(canonical_code, reverse=True)

        if result.get("found") and result.get("matches"):
            for match in result["matches"]:
                sheet_name = match.get("worksheet", "")
                if sheet_name and sheet_name not in sheets_flights:
                    sheets_flights.append(sheet_name)
    except Exception:
        await session.rollback()
        pass

    all_flights = list(set(db_flights + sheets_flights))
    all_flights.sort(reverse=True)

    info_text = _("admin-verification-client-found",
        client_code=client.client_code or canonical_code,
        full_name=client.full_name,
        telegram_id=str(client.telegram_id) if client.telegram_id else _("not-provided"),
        total_payments=total_payments,
        taken_away=taken_away_count
    )

    if all_flights:
        admin_verification_flights_label = _("admin-verification-flights")
        info_text += f"\n\n🛫 {admin_verification_flights_label}: {', '.join(all_flights)}"

    builder = InlineKeyboardBuilder()

    builder.button(
        text=_("btn-verification-full-info"),
        callback_data=f"v:fi:{client.id}"
    )

    if all_flights:
        builder.button(
            text=_("btn-verification-select-flight"),
            callback_data=f"v:sf:{canonical_code}"
        )

    builder.button(
        text=_("btn-verification-all-payments"),
        callback_data=f"v:pay:{canonical_code}:all:desc:0:none"
    )

    builder.button(
        text=_("btn-verification-unpaid-payments"),
        callback_data=f"v:unp:{canonical_code}:all:desc:0:none"
    )

    builder.adjust(1)

    await callback.message.edit_text(
        text=info_text,
        reply_markup=builder.as_markup()
    )
    await safe_answer_callback(callback)
