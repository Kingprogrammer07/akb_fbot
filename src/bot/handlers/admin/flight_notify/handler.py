"""FSM handlers for the flight-notify workflow.

Entry point: the broadcast audience-selection keyboard emits
``broadcast_audience_flight``; the broadcast handler transfers FSM control
here by setting ``FlightNotifyStates.selecting_flight``.

State machine:
    selecting_flight  →  waiting_for_text  →  preview  →  sending
    preview  --edit-->  waiting_for_text
    any      --cancel-> cleared
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_admin import IsAdmin
from src.bot.handlers.admin.flight_notify.keyboards import (
    FLIGHTS_PER_PAGE,
    FlightNotifyKeyboards,
)
from src.bot.handlers.admin.flight_notify.models import ClientNotifyData, FlightNotifyTask
from src.bot.handlers.admin.flight_notify.sender import (
    FlightNotifySender,
    _active_notify_tasks,
    generate_notify_task_id,
)
from src.bot.handlers.admin.flight_notify.states import FlightNotifyStates
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.dao.expected_cargo import ExpectedFlightCargoDAO
from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO

logger = logging.getLogger(__name__)

router = Router(name="flight_notify")


# ---------------------------------------------------------------------------
# Public helper — called by broadcast/handler.py to bootstrap this flow
# ---------------------------------------------------------------------------


async def render_flight_list(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    *,
    edit: bool = False,
) -> None:
    """Fetch recent flights and render the paginated selection keyboard.

    This function is intentionally public so the broadcast handler can delegate
    to it when the user chooses "Reys bo'yicha xabar".

    Args:
        message: The Telegram message object used to send or edit the response.
        state:   Current FSM context (reads ``fn_page``; updates are left to callers).
        session: Active DB session from middleware.
        edit:    When True, edits the existing message instead of sending a new one.
    """
    data = await state.get_data()
    page: int = data.get("fn_page", 0)

    flights = await FlightCargoDAO.get_distinct_recent_flights(session, limit=80)

    if not flights:
        text = (
            "✈️ <b>Reys bo'yicha xabar</b>\n\n"
            "⚠️ Hozircha bazada hech qanday reys topilmadi."
        )
        if edit:
            await message.edit_text(text, parse_mode="HTML")
        else:
            await message.answer(text, parse_mode="HTML")
        return

    # Fetch client counts for all flights in a single async batch
    client_counts: dict[str, int] = {}
    for flight in flights:
        client_counts[flight] = await FlightCargoDAO.count_unique_clients_by_flight(
            session, flight
        )

    total_pages = max(1, (len(flights) + FLIGHTS_PER_PAGE - 1) // FLIGHTS_PER_PAGE)
    page = min(page, total_pages - 1)
    await state.update_data(fn_page=page)

    text = "✈️ <b>Reys tanlang:</b>"
    keyboard = FlightNotifyKeyboards.flight_list(flights, page, total_pages, client_counts)

    if edit:
        await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ---------------------------------------------------------------------------
# selecting_flight state
# ---------------------------------------------------------------------------


@router.callback_query(
    FlightNotifyStates.selecting_flight, F.data.startswith("fn_page:"), IsAdmin()
)
async def paginate_flight_list(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Handle pagination buttons inside the flight-selection keyboard."""
    page = int(callback.data.split(":", 1)[1])
    await state.update_data(fn_page=page)
    await render_flight_list(callback.message, state, session, edit=True)
    await callback.answer()


@router.callback_query(FlightNotifyStates.selecting_flight, F.data == "fn_noop", IsAdmin())
async def noop_callback(callback: CallbackQuery) -> None:
    """No-op handler for the page-counter button (just shows current page number)."""
    await callback.answer()


@router.callback_query(
    FlightNotifyStates.selecting_flight, F.data.startswith("fn_select_flight:"), IsAdmin()
)
async def flight_selected(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Store the chosen flight and prompt for the custom message text."""
    flight_name: str = callback.data.split(":", 1)[1]
    client_count = await FlightCargoDAO.count_unique_clients_by_flight(session, flight_name)

    await state.update_data(
        fn_flight=flight_name,
        fn_client_count=client_count,
    )
    await state.set_state(FlightNotifyStates.waiting_for_text)

    await callback.message.edit_text(
        f"✈️ Reys: <b>{flight_name}</b>\n"
        f"👥 Mijozlar: <b>{client_count}</b>\n\n"
        "📝 <b>Xabar matnini yozing:</b>\n"
        "<i>(bu matn har bir mijozning trek kodlaridan keyin yuboriladi)</i>",
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# waiting_for_text state
# ---------------------------------------------------------------------------


@router.message(FlightNotifyStates.waiting_for_text, IsAdmin())
async def text_entered(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Accept the admin's custom message and show a sample preview."""
    admin_text = (message.text or "").strip()
    if not admin_text:
        await message.answer(
            "⚠️ Xabar bo'sh bo'lishi mumkin emas. Iltimos matn kiriting:"
        )
        return

    data = await state.get_data()
    flight_name: str = data["fn_flight"]
    client_count: int = data.get("fn_client_count", 0)

    await state.update_data(fn_admin_text=admin_text)
    await state.set_state(FlightNotifyStates.preview)

    sample = await _build_sample_notify_data(session, flight_name)
    if sample:
        sample_text = sample.build_message(flight_name, admin_text)
    else:
        sample_text = (
            "(trek kodlar topilmadi)\n\n"
            f"bu sizning {flight_name} dagi track codingiz\n\n"
            f"{admin_text}"
        )

    await message.answer(
        f"👁 <b>Namuna xabar:</b>\n\n"
        f"<pre>{sample_text}</pre>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✈️ Reys: <b>{flight_name}</b>\n"
        f"👥 Yuboriladi: <b>{client_count}</b> mijozga\n\n"
        "Tasdiqlaysizmi?",
        reply_markup=FlightNotifyKeyboards.confirm_preview(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# preview state
# ---------------------------------------------------------------------------


@router.callback_query(FlightNotifyStates.preview, F.data == "fn_edit_text", IsAdmin())
async def edit_text(callback: CallbackQuery, state: FSMContext) -> None:
    """Return to text-input state without resetting the selected flight."""
    data = await state.get_data()
    flight_name: str = data.get("fn_flight", "")
    await state.set_state(FlightNotifyStates.waiting_for_text)
    await callback.message.edit_text(
        f"✈️ Reys: <b>{flight_name}</b>\n\n"
        "📝 Yangi xabar matnini yozing:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(FlightNotifyStates.preview, F.data == "fn_confirm", IsAdmin())
async def confirm_and_start_send(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Resolve all clients, spawn the sender task, and transition to *sending* state."""
    data = await state.get_data()
    flight_name: str = data["fn_flight"]
    admin_text: str = data["fn_admin_text"]

    await callback.answer()
    await callback.message.edit_text(
        f"⏳ <b>Mijozlar ma'lumotlari yuklanmoqda...</b>\n✈️ {flight_name}",
        parse_mode="HTML",
    )

    clients = await _resolve_clients_for_flight(session, flight_name)

    if not clients:
        await callback.message.edit_text(
            f"⚠️ <b>{flight_name}</b> reysi uchun hech qanday mijoz topilmadi.",
            parse_mode="HTML",
        )
        await state.clear()
        return

    task_id = generate_notify_task_id(callback.from_user.id)

    progress_msg = await callback.message.answer(
        f"🚀 <b>Yuborish boshlandi...</b>\n"
        f"✈️ Reys: {flight_name}\n"
        f"👥 Jami: {len(clients)} ta mijoz",
        parse_mode="HTML",
    )

    sender = FlightNotifySender(
        bot=bot,
        flight_name=flight_name,
        admin_text=admin_text,
        clients=clients,
        admin_chat_id=callback.from_user.id,
        task_id=task_id,
    )
    await sender.initialize(progress_msg.message_id)

    task = asyncio.create_task(sender.run(), name=f"flight_notify_{task_id}")
    _active_notify_tasks[task_id] = FlightNotifyTask(task=task)

    await state.set_state(FlightNotifyStates.sending)
    await state.update_data(fn_task_id=task_id)

    await progress_msg.edit_reply_markup(
        reply_markup=FlightNotifyKeyboards.stop_button(task_id)
    )


# ---------------------------------------------------------------------------
# Stop handler (any state / no state guard needed — task_id is unique enough)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("fn_stop_task:"), IsAdmin())
async def stop_send_task(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the active send task identified by the callback's task_id."""
    task_id: str = callback.data.split(":", 1)[1]
    task_entry = _active_notify_tasks.get(task_id)
    if task_entry:
        task_entry.cancel()
        await callback.answer("⏸ To'xtatilmoqda...")
    else:
        await callback.answer("Vazifa allaqachon tugagan.")

    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Universal cancel handler
# ---------------------------------------------------------------------------


@router.callback_query(
    F.data == "fn_cancel",
    IsAdmin(),
)
async def cancel_flow(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the current flow from any state and clear FSM data."""
    await state.clear()
    await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _build_sample_notify_data(
    session: AsyncSession,
    flight_name: str,
) -> ClientNotifyData | None:
    """Fetch the first available client's track codes for preview purposes.

    Returns None when the flight has no known clients yet.
    """
    codes = await FlightCargoDAO.get_distinct_client_ids_by_flight(session, flight_name)
    if not codes:
        return None

    sample_code = codes[0]
    track_codes = await ExpectedFlightCargoDAO.get_track_codes_by_flight_and_client(
        session, flight_name, sample_code
    )
    return ClientNotifyData(
        client_code=sample_code,
        telegram_id=None,  # Not needed for preview
        track_codes=track_codes,
        is_gx=sample_code.upper().startswith("GX"),
    )


async def _resolve_clients_for_flight(
    session: AsyncSession,
    flight_name: str,
) -> list[ClientNotifyData]:
    """Build the complete ``ClientNotifyData`` list for a flight.

    Steps:
    1. Get distinct ``client_id`` values from ``flight_cargos``.
    2. Bulk-fetch matching ``Client`` rows (checks all code columns).
    3. Build a normalised ``code → telegram_id`` lookup map.
    4. Pre-fetch all track codes for the flight in one query.
    5. Assemble ``ClientNotifyData`` for every client code.

    Google Sheets fallback for clients with empty track_codes is deferred to
    ``FlightNotifySender._process_client`` so this handler stays non-blocking.
    """
    codes = await FlightCargoDAO.get_distinct_client_ids_by_flight(session, flight_name)
    if not codes:
        return []

    db_clients = await ClientDAO.get_clients_by_code_list(session, codes)

    # Build normalised code → telegram_id map covering all alias columns
    code_to_telegram_id: dict[str, int | None] = {}
    for client in db_clients:
        telegram_id = client.telegram_id
        for code in client.active_codes:
            code_to_telegram_id[code.upper()] = telegram_id

    # Batch-fetch all track codes for this flight (one DB round-trip)
    grouped_tracks = await ExpectedFlightCargoDAO.get_track_codes_grouped_by_flight(
        session, flight_name
    )

    result: list[ClientNotifyData] = []
    for code in codes:
        code_upper = code.upper()
        result.append(
            ClientNotifyData(
                client_code=code,
                telegram_id=code_to_telegram_id.get(code_upper),
                track_codes=grouped_tracks.get(code_upper, []),
                is_gx=code_upper.startswith("GX"),
            )
        )
    return result
