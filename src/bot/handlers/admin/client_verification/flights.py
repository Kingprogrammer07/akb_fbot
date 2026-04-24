"""Flight selection handlers for client verification."""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_admin import IsAdmin
from src.infrastructure.services.client import ClientService
from src.infrastructure.services.client_transaction import ClientTransactionService
from src.bot.utils.decorators import handle_errors

from .utils import safe_answer_callback, encode_flight_code

router = Router()


@router.callback_query(F.data.startswith("v:sf:"), IsAdmin())
@handle_errors
async def show_flight_selection(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService
):
    """Show flight selection menu for filtering payments."""
    client_code = callback.data.split(":")[2]

    # Resolve all active aliases so we don't miss flights stored under any code variant.
    client = await client_service.get_client_by_code(client_code, session)
    if not client:
        await safe_answer_callback(callback, _("client-not-found"), show_alert=True)
        return

    active_codes = client.active_codes
    canonical_code = client.primary_code

    flights = await transaction_service.get_unique_flights_by_client_code(active_codes, session)

    if not flights:
        await safe_answer_callback(callback, _("admin-verification-no-flights"), show_alert=True)
        return

    builder = InlineKeyboardBuilder()

    for flight in flights:
        flight_count = len(await transaction_service.get_filtered_transactions_by_client_code(
            active_codes, session, "all", "desc", 1000, 0, flight
        ))

        flight_hash = encode_flight_code(flight)
        builder.button(
            text=f"✈️ {flight} ({flight_count})",
            callback_data=f"v:pay:{canonical_code}:all:desc:0:{flight_hash}"
        )

    builder.button(
        text=_("btn-back"),
        callback_data=f"v:btc:{canonical_code}"
    )

    builder.adjust(1)

    await callback.message.edit_text(
        _("admin-verification-select-flight-prompt"),
        reply_markup=builder.as_markup()
    )
    await safe_answer_callback(callback)
