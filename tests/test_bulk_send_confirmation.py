"""The bulk-send confirmation button survives an outdated FSM.

The "✅ Yuborish" screen stays in the admin's chat indefinitely, while the FSM
behind it lives in Redis with a TTL and is cleared by other admin flows.  A tap
on it after that must answer with an alert instead of raising ``KeyError``, a
second tap must not start a second send, and an older confirmation screen must
not send the flight selected after it.  The cancel button keeps working once
the FSM data is gone.

Callbacks are propagated through the module's real router, so the state
filters and the order of the fallback handler are what the test exercises;
the sender is a fake and the bot an ``AsyncMock``.  No database is needed.
"""

from datetime import UTC, datetime
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Message

from src.bot.filters import is_admin
from src.bot.handlers.admin import bulk_cargo_sender
from src.bot.handlers.admin.bulk_cargo_sender import (
    STALE_SCREEN_ALERT,
    BulkSendStates,
    BulkSendTask,
)

ADMIN_TG = 1
FLIGHT = "M5000"
NEWER_FLIGHT = "M5001"
CONFIRM_SCREEN_ID = 444
PROGRESS_MESSAGE_ID = 900
CLIENTS_DATA = {"T101": [11, 12], "T102": [13]}


class FakeSender:
    """Stands in for ``BulkCargoSender`` and records every send it starts."""

    started: ClassVar[list[str]] = []

    def __init__(self, *, flight_name: str, **_: object) -> None:
        self.flight_name = flight_name

    async def initialize(self, progress_message_id: int) -> bool:
        return True

    async def run(self) -> None:
        FakeSender.started.append(self.flight_name)


@pytest.fixture(autouse=True)
def isolate_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    async def always_admin(session: object, telegram_id: int) -> bool:
        return True

    FakeSender.started = []
    monkeypatch.setattr(is_admin, "is_admin_by_telegram_id", always_admin)
    monkeypatch.setattr(bulk_cargo_sender, "BulkCargoSender", FakeSender)
    monkeypatch.setattr(bulk_cargo_sender, "_active_tasks", {})


def make_bot() -> AsyncMock:
    bot = AsyncMock()

    async def execute(method: TelegramMethod[object]) -> object:
        if isinstance(method, SendMessage):
            return message(PROGRESS_MESSAGE_ID, bot)
        return True

    bot.side_effect = execute
    return bot


def message(message_id: int, bot: AsyncMock) -> Message:
    return Message.model_validate(
        {
            "message_id": message_id,
            "date": datetime.now(UTC),
            "chat": {"id": ADMIN_TG, "type": "private"},
            "from": {"id": ADMIN_TG, "is_bot": False, "first_name": "Admin"},
            "text": "screen",
        },
        context={"bot": bot},
    )


def tap(
    bot: AsyncMock, data: str, message_id: int = CONFIRM_SCREEN_ID
) -> CallbackQuery:
    return CallbackQuery.model_validate(
        {
            "id": f"cb-{data}-{message_id}",
            "from": {"id": ADMIN_TG, "is_bot": False, "first_name": "Admin"},
            "chat_instance": "ci-1",
            "data": data,
            "message": message(message_id, bot).model_dump(),
        },
        context={"bot": bot},
    )


def make_state() -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=ADMIN_TG, user_id=ADMIN_TG),
    )


async def press(bot: AsyncMock, state: FSMContext, callback: CallbackQuery) -> None:
    """Deliver a callback the way the dispatcher does, FSM context included."""
    await bulk_cargo_sender.router.propagate_event(
        update_type="callback_query",
        event=callback,
        bot=bot,
        state=state,
        raw_state=await state.get_state(),
        session=AsyncMock(),
        client_service=None,
    )


async def confirmation_screen(state: FSMContext, flight: str = FLIGHT) -> None:
    await state.set_state(BulkSendStates.confirming_send)
    await state.set_data(
        {
            "flight_name": flight,
            "clients_data": CLIENTS_DATA,
            "total_clients": len(CLIENTS_DATA),
            "total_cargos": 3,
            "confirm_message_id": CONFIRM_SCREEN_ID,
        }
    )


def alerts(bot: AsyncMock) -> list[str | None]:
    return [
        call.args[0].text
        for call in bot.await_args_list
        if isinstance(call.args[0], AnswerCallbackQuery)
    ]


async def test_confirm_after_the_fsm_expired_alerts_instead_of_crashing() -> None:
    bot, state = make_bot(), make_state()

    await press(bot, state, tap(bot, "bulk_confirm_send"))

    assert alerts(bot) == [STALE_SCREEN_ALERT]
    bot.edit_message_reply_markup.assert_awaited_once()
    assert FakeSender.started == []


async def test_confirm_with_expired_data_alerts_and_clears_the_state() -> None:
    bot, state = make_bot(), make_state()
    # State and data keys have separate TTLs: the state can outlive its data.
    await state.set_state(BulkSendStates.confirming_send)

    await press(bot, state, tap(bot, "bulk_confirm_send"))

    assert alerts(bot) == [STALE_SCREEN_ALERT]
    assert await state.get_state() is None
    assert FakeSender.started == []


async def test_confirm_starts_one_send_and_a_second_tap_is_rejected() -> None:
    bot, state = make_bot(), make_state()
    await confirmation_screen(state)

    await press(bot, state, tap(bot, "bulk_confirm_send"))
    await press(bot, state, tap(bot, "bulk_confirm_send"))

    assert FakeSender.started == [FLIGHT]
    assert alerts(bot) == [None, STALE_SCREEN_ALERT]
    assert await state.get_state() == BulkSendStates.sending_in_progress.state
    task_id = (await state.get_data())["task_id"]
    assert task_id in bulk_cargo_sender._active_tasks


async def test_an_older_confirmation_screen_cannot_send_the_newer_flight() -> None:
    bot, state = make_bot(), make_state()
    await confirmation_screen(state, flight=NEWER_FLIGHT)

    await press(
        bot, state, tap(bot, "bulk_confirm_send", message_id=CONFIRM_SCREEN_ID - 1)
    )

    assert FakeSender.started == []
    assert alerts(bot) == [STALE_SCREEN_ALERT]
    # The newer screen is still pending, so its FSM is kept.
    assert await state.get_state() == BulkSendStates.confirming_send.state


async def test_proceeding_binds_the_confirmation_screen_to_the_fsm() -> None:
    bot, state = make_bot(), make_state()
    bot.send_message.return_value = message(CONFIRM_SCREEN_ID, bot)
    await state.set_state(BulkSendStates.reviewing_aliases)
    await state.set_data(
        {"flight_name": FLIGHT, "clients_data": CLIENTS_DATA, "total_clients": 2}
    )

    await press(bot, state, tap(bot, "bulk_alias_proceed", message_id=300))

    assert await state.get_state() == BulkSendStates.confirming_send.state
    assert (await state.get_data())["confirm_message_id"] == CONFIRM_SCREEN_ID
    assert alerts(bot) == [None]


async def test_review_buttons_after_the_fsm_expired_alert_once() -> None:
    bot, state = make_bot(), make_state()

    await press(bot, state, tap(bot, "bulk_alias_proceed", message_id=300))
    await press(bot, state, tap(bot, "bulk_alias_edit:7", message_id=300))

    assert alerts(bot) == [STALE_SCREEN_ALERT, STALE_SCREEN_ALERT]


async def test_cancel_reaches_the_task_after_the_fsm_data_expired() -> None:
    bot, state = make_bot(), make_state()
    task = BulkSendTask(task=AsyncMock())
    bulk_cargo_sender._active_tasks["1_123"] = task

    await press(
        bot, state, tap(bot, "bulk_cancel_task:1_123", message_id=PROGRESS_MESSAGE_ID)
    )

    assert task.cancelled
