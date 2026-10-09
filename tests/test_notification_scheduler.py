"""
The partial-payment and leftover-cargo senders must never share their
``AsyncSession`` between concurrent tasks, must keep going when one client's
lookup, render or persist fails, and must stop when they are cancelled.

Both senders used to render FlightDisplay labels and persist notifications
inside the tasks they ran under ``asyncio.gather``.  An ``AsyncSession`` is
not safe for concurrent use, so reminders failed with "another operation is
in progress" and were silently counted as errors.  The partial-payment sender
also retried ``TelegramRetryAfter`` by re-entering ``SEND_SEMAPHORE`` while it
still held a slot, which deadlocks once every slot is retrying.  The senders
and the leftover scheduler also ended their session loop with
``finally: break``, which discards an in-flight ``CancelledError``, so a
cancelled scheduler kept running.

Reminders render ``reys`` from the client's own transaction rows, so a
partner client whose flight has no alias yet must get a freshly minted mask,
never a placeholder.  A database error while looking up one leftover client
used to abort the whole leftover run.  The leftover scheduler used to keep its
session, with a transaction open, through a sleep of up to 15 days, pinning a
pooled connection idle in a transaction.

Database tests run the real senders against PostgreSQL (``AKB_TEST_DB=1``)
with a fake Telegram bot and one instrumented session; the fakes live in
``_scheduler_fakes`` and the seed builders in ``_scheduler_seeds``.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.bot.utils import notification_scheduler as scheduler
from src.bot.utils.i18n import i18n
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.services.flight_display import FLIGHT_PLACEHOLDER
from tests._scheduler_fakes import (
    AWAITABLE_SESSION_METHODS,
    ConcurrentSessionUseDetector,
    FakeTelegram,
    FirstRecipientDeleter,
    ParkedSleeps,
    SharedSessionDatabaseClient,
    StaticDataDAOStub,
)
from tests._scheduler_seeds import (
    MASKS,
    MINTED_MASKS,
    REAL_FLIGHTS,
    REMINDER_DAYS,
    aliases_by_partner,
    expected_leftover_text,
    expected_reminder_parts,
    idle_in_transaction_backends,
    persisted_by_chat,
    seed_leftovers,
    seed_notification_settings,
    seed_partial_payments,
)

RUN_TIMEOUT_SECONDS = 60.0


@pytest.fixture
def detector() -> ConcurrentSessionUseDetector:
    return ConcurrentSessionUseDetector()


@pytest_asyncio.fixture
async def scheduler_db(
    db_engine: AsyncEngine,
    detector: ConcurrentSessionUseDetector,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncSession]:
    """Route the scheduler to the test database through one instrumented session."""
    session = async_sessionmaker(db_engine, expire_on_commit=False)()
    detector.instrument(session)
    monkeypatch.setattr(
        scheduler, "DatabaseClient", lambda _url: SharedSessionDatabaseClient(session)
    )
    # asyncio primitives bind to the first loop that waits on them, and every
    # test runs on a fresh loop.
    monkeypatch.setattr(scheduler, "SEND_SEMAPHORE", asyncio.Semaphore(10))
    try:
        yield session
    finally:
        await session.close()


@pytest.fixture
def scheduler_logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG, logger=scheduler.__name__)
    return caplog


async def run_sender(
    sender: Callable[[AsyncMock], Awaitable[None]],
    bot: AsyncMock,
    timeout: float = RUN_TIMEOUT_SECONDS,
) -> None:
    """Run a sender to completion; a deadlock fails the test instead of hanging it."""
    task = asyncio.ensure_future(sender(bot))
    done, _ = await asyncio.wait({task}, timeout=timeout)
    if not done:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        pytest.fail(f"sender did not finish within {timeout}s")
    task.result()


async def cancel_once_ready(task: asyncio.Future[None], ready: asyncio.Event) -> None:
    """Cancel ``task`` as soon as ``ready`` is set, then wait for it to finish."""
    await asyncio.wait_for(ready.wait(), RUN_TIMEOUT_SECONDS)
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=RUN_TIMEOUT_SECONDS)
    if not done:
        pytest.fail(f"task still running {RUN_TIMEOUT_SECONDS}s after cancellation")


def scheduler_messages(
    caplog: pytest.LogCaptureFixture, min_level: int = logging.DEBUG
) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == scheduler.__name__ and record.levelno >= min_level
    ]


def warnings_starting_with(caplog: pytest.LogCaptureFixture, prefix: str) -> list[str]:
    return [
        message
        for message in scheduler_messages(caplog, logging.WARNING)
        if message.startswith(prefix)
    ]


def test_detector_wraps_every_awaitable_session_method() -> None:
    coroutine_methods = {
        name
        for name, member in inspect.getmembers(AsyncSession)
        if not name.startswith("_") and inspect.iscoroutinefunction(member)
    }

    assert set(AWAITABLE_SESSION_METHODS) == coroutine_methods - {"close_all"}


async def test_detector_flags_session_calls_that_overlap_across_tasks() -> None:
    session = AsyncSession()
    detector = ConcurrentSessionUseDetector()
    detector.instrument(session)

    await asyncio.gather(session.rollback(), session.close())

    assert detector.overlaps == ["close"]


async def test_partial_payment_reminders_reach_every_due_client_once(
    scheduler_db: AsyncSession,
    db_engine: AsyncEngine,
    scheduler_logs: pytest.LogCaptureFixture,
) -> None:
    clients = await seed_partial_payments(db_engine)
    blocked, flooded = 910_004, 910_007
    telegram = FakeTelegram(flood_chat_id=flooded, blocked_chat_id=blocked)

    await run_sender(scheduler.send_partial_payment_reminders, telegram.bot())

    assert Counter(a.chat_id for a in telegram.attempts) == {
        **{telegram_id: 1 for telegram_id in clients},
        flooded: 2,
    }
    delivered = telegram.delivered()
    assert set(delivered) == set(clients) - {blocked}
    for telegram_id, attempt in delivered.items():
        assert sorted(attempt.text.split("\n\n")) == expected_reminder_parts(
            clients[telegram_id]
        )
        assert attempt.options == {}  # the bot's default HTML parse mode applies
    for attempt in telegram.attempts:
        assert not [real for real in REAL_FLIGHTS if real in attempt.text]

    assert await persisted_by_chat(db_engine) == {
        telegram_id: [("Payment Reminder", "payment", attempt.text)]
        for telegram_id, attempt in delivered.items()
    }
    assert scheduler_messages(scheduler_logs, logging.ERROR) == []
    assert (
        f"Partial payment reminders completed: sent={len(delivered)}, blocked=1, errors=0"
        in scheduler_messages(scheduler_logs)
    )


async def test_partial_payment_reminders_mint_the_missing_partner_masks(
    scheduler_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    clients = await seed_partial_payments(db_engine)
    telegram = FakeTelegram()

    await run_sender(scheduler.send_partial_payment_reminders, telegram.bot())

    assert await aliases_by_partner(db_engine) == {**MASKS, **MINTED_MASKS}
    delivered = telegram.delivered()
    unaliased = [
        (delivered[telegram_id].text, MINTED_MASKS[(client.partner_code, flight)])
        for telegram_id, client in clients.items()
        for flight, _days, _deadline in client.due
        if (client.partner_code, flight) in MINTED_MASKS
    ]
    # Each partner's unaliased flight is due for one client per reminder day.
    assert len(unaliased) == len(MINTED_MASKS) * len(REMINDER_DAYS)
    for reminder, mask in unaliased:
        assert mask in reminder
        assert FLIGHT_PLACEHOLDER not in reminder
        assert not [real for real in REAL_FLIGHTS if real in reminder]


async def test_leftover_notifications_reach_every_client_once(
    scheduler_db: AsyncSession,
    db_engine: AsyncEngine,
    scheduler_logs: pytest.LogCaptureFixture,
) -> None:
    clients = await seed_leftovers(db_engine)
    blocked, flooded = 930_003, 930_006
    telegram = FakeTelegram(flood_chat_id=flooded, blocked_chat_id=blocked)

    await run_sender(scheduler.send_leftover_notifications, telegram.bot())

    assert Counter(a.chat_id for a in telegram.attempts) == {
        **{telegram_id: 1 for telegram_id in clients},
        flooded: 2,
    }
    delivered = telegram.delivered()
    assert set(delivered) == set(clients) - {blocked}
    for telegram_id, attempt in delivered.items():
        assert attempt.text == expected_leftover_text(clients[telegram_id])
        assert attempt.options == {"parse_mode": "HTML"}
        assert not [real for real in REAL_FLIGHTS if real in attempt.text]

    title = i18n.get("uz", "notification-leftover-greeting")
    assert await persisted_by_chat(db_engine) == {
        telegram_id: [(title, "cargo", attempt.text)]
        for telegram_id, attempt in delivered.items()
    }
    assert (
        f"Leftover cargo notifications completed: sent={len(delivered)}, skipped=2, "
        f"blocked=1, errors=0"
    ) in scheduler_messages(scheduler_logs)


async def test_partial_payment_reminders_never_share_the_session_between_tasks(
    scheduler_db: AsyncSession,
    db_engine: AsyncEngine,
    detector: ConcurrentSessionUseDetector,
) -> None:
    await seed_partial_payments(db_engine)

    await run_sender(scheduler.send_partial_payment_reminders, FakeTelegram().bot())

    assert detector.overlaps == [], (
        f"session used concurrently by tasks: {detector.overlaps}"
    )


async def test_leftover_notifications_never_share_the_session_between_tasks(
    scheduler_db: AsyncSession,
    db_engine: AsyncEngine,
    detector: ConcurrentSessionUseDetector,
) -> None:
    await seed_leftovers(db_engine)

    await run_sender(scheduler.send_leftover_notifications, FakeTelegram().bot())

    assert detector.overlaps == [], (
        f"session used concurrently by tasks: {detector.overlaps}"
    )


async def test_flood_wait_retry_does_not_need_a_second_send_slot(
    scheduler_db: AsyncSession,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    scheduler_logs: pytest.LogCaptureFixture,
) -> None:
    clients = await seed_partial_payments(db_engine)
    monkeypatch.setattr(scheduler, "SEND_SEMAPHORE", asyncio.Semaphore(1))
    telegram = FakeTelegram(flood_chat_id=910_000)

    await run_sender(
        scheduler.send_partial_payment_reminders, telegram.bot(), timeout=10
    )

    assert set(telegram.delivered()) == set(clients)
    assert (
        f"Partial payment reminders completed: sent={len(clients)}, blocked=0, errors=0"
        in scheduler_messages(scheduler_logs)
    )


async def test_one_failed_persist_does_not_drop_the_rest(
    scheduler_db: AsyncSession,
    db_engine: AsyncEngine,
    scheduler_logs: pytest.LogCaptureFixture,
) -> None:
    clients = await seed_partial_payments(db_engine)
    deleter = FirstRecipientDeleter(db_engine)
    telegram = FakeTelegram(on_delivered=deleter)

    await run_sender(scheduler.send_partial_payment_reminders, telegram.bot())

    assert set(telegram.delivered()) == set(clients)
    assert set(await persisted_by_chat(db_engine)) == set(clients) - {deleter.chat_id}
    assert len(warnings_starting_with(scheduler_logs, "Failed to persist")) == 1


async def test_failed_rollback_does_not_stop_the_remaining_persists(
    scheduler_db: AsyncSession,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    scheduler_logs: pytest.LogCaptureFixture,
) -> None:
    clients = await seed_partial_payments(db_engine)
    deleter = FirstRecipientDeleter(db_engine)
    rollback = scheduler_db.rollback

    async def rollback_on_a_lost_connection() -> None:
        # SQLAlchemy discards the transaction even when ROLLBACK itself fails;
        # only the error reaches the caller.
        await rollback()
        raise OperationalError("ROLLBACK", None, ConnectionResetError("lost"))

    monkeypatch.setattr(scheduler_db, "rollback", rollback_on_a_lost_connection)

    await run_sender(
        scheduler.send_partial_payment_reminders,
        FakeTelegram(on_delivered=deleter).bot(),
    )

    assert set(await persisted_by_chat(db_engine)) == set(clients) - {deleter.chat_id}
    assert len(warnings_starting_with(scheduler_logs, "Failed to persist")) == 1
    rollback_failure = (
        f"Rollback after the failed persist for client {deleter.client_id} also failed:"
    )
    assert len(warnings_starting_with(scheduler_logs, rollback_failure)) == 1
    assert scheduler_messages(scheduler_logs, logging.ERROR) == []
    assert (
        f"Partial payment reminders completed: sent={len(clients)}, blocked=0, errors=0"
        in scheduler_messages(scheduler_logs)
    )


async def test_database_error_while_rendering_one_reminder_spares_the_others(
    scheduler_db: AsyncSession,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    scheduler_logs: pytest.LogCaptureFixture,
) -> None:
    clients = await seed_partial_payments(db_engine)
    render = scheduler._render_partial_payment_reminder
    failed: list[int] = []

    async def render_with_one_database_error(
        session: AsyncSession,
        client: Client,
        reminders: list[tuple[ClientTransaction, int]],
    ) -> scheduler.OutgoingMessage:
        if not failed:
            failed.append(client.telegram_id)
            # Aborts the PostgreSQL transaction, as any failed query does.
            await session.execute(text("SELECT 1 / 0"))
        return await render(session, client, reminders)

    monkeypatch.setattr(
        scheduler, "_render_partial_payment_reminder", render_with_one_database_error
    )
    telegram = FakeTelegram()

    await run_sender(scheduler.send_partial_payment_reminders, telegram.bot())

    assert set(telegram.delivered()) == set(clients) - set(failed)
    assert set(await persisted_by_chat(db_engine)) == set(clients) - set(failed)
    assert (
        f"Partial payment reminders completed: sent={len(clients) - 1}, blocked=0, "
        f"errors=1"
    ) in scheduler_messages(scheduler_logs)


async def test_database_error_while_looking_up_one_leftover_client_spares_the_others(
    scheduler_db: AsyncSession,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    scheduler_logs: pytest.LogCaptureFixture,
) -> None:
    clients = await seed_leftovers(db_engine)
    failing = clients[930_001]
    lookup = ClientDAO.get_by_client_code

    async def lookup_with_one_database_error(
        session: AsyncSession, client_code: str
    ) -> Client | None:
        if client_code == failing.code:
            # Aborts the PostgreSQL transaction, as any failed query does.
            await session.execute(text("SELECT 1 / 0"))
        return await lookup(session, client_code)

    monkeypatch.setattr(
        scheduler,
        "ClientDAO",
        SimpleNamespace(get_by_client_code=lookup_with_one_database_error),
    )
    telegram = FakeTelegram()

    await run_sender(scheduler.send_leftover_notifications, telegram.bot())

    assert set(telegram.delivered()) == set(clients) - {failing.telegram_id}
    assert set(await persisted_by_chat(db_engine)) == set(clients) - {failing.telegram_id}
    assert (
        f"Leftover cargo notifications completed: sent={len(clients) - 1}, skipped=2, "
        f"blocked=0, errors=1"
    ) in scheduler_messages(scheduler_logs)


@pytest.mark.parametrize(
    ("sender", "seed"),
    [
        (scheduler.send_partial_payment_reminders, seed_partial_payments),
        (scheduler.send_leftover_notifications, seed_leftovers),
    ],
    ids=["partial-payments", "leftovers"],
)
async def test_cancelling_a_sender_mid_send_propagates_cancelled_error(
    scheduler_db: AsyncSession,
    db_engine: AsyncEngine,
    sender: Callable[[AsyncMock], Awaitable[None]],
    seed: Callable[[AsyncEngine], Awaitable[object]],
) -> None:
    await seed(db_engine)
    request_sent = asyncio.Event()

    async def never_answer(_chat_id: int) -> None:
        request_sent.set()
        await asyncio.Event().wait()

    task = asyncio.ensure_future(sender(FakeTelegram(on_request=never_answer).bot()))
    await cancel_once_ready(task, request_sent)

    assert task.cancelled(), f"CancelledError did not propagate: {task!r}"


async def test_cancelling_the_leftover_scheduler_stops_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = SharedSessionDatabaseClient(AsyncSession())
    static_data = StaticDataDAOStub()
    monkeypatch.setattr(scheduler, "DatabaseClient", lambda _url: database)
    monkeypatch.setattr(scheduler, "StaticDataDAO", static_data)

    task = asyncio.ensure_future(scheduler.notification_scheduler_task(AsyncMock()))
    # With the settings read, the scheduler sleeps out the notification period.
    await cancel_once_ready(task, static_data.read)

    assert task.cancelled(), f"CancelledError did not propagate: {task!r}"
    assert database.sessions_handed_out == 1


async def test_leftover_scheduler_holds_no_database_connection_while_it_sleeps(
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    scheduler_logs: pytest.LogCaptureFixture,
) -> None:
    period_days = 15
    await seed_notification_settings(db_engine, period_days)
    databases: list[DatabaseClient] = []

    def open_database(url: str) -> DatabaseClient:
        databases.append(DatabaseClient(url))
        return databases[-1]

    held_while_sleeping: list[dict[str, float]] = []

    async def record_held_connections(seconds: float) -> None:
        (database,) = databases
        held_while_sleeping.append(
            {
                "seconds": seconds,
                "checked_out": database.engine.pool.checkedout(),
                "idle_in_transaction": await idle_in_transaction_backends(db_engine),
            }
        )

    sleeps = ParkedSleeps(on_sleep=record_held_connections)
    monkeypatch.setattr(scheduler, "DatabaseClient", open_database)
    monkeypatch.setattr(scheduler, "asyncio", sleeps)

    task = asyncio.ensure_future(scheduler.notification_scheduler_task(AsyncMock()))
    await cancel_once_ready(task, sleeps.sleeping)

    assert task.cancelled(), f"CancelledError did not propagate: {task!r}"
    assert held_while_sleeping == [
        {
            "seconds": period_days * 24 * 60 * 60,
            "checked_out": 0,
            "idle_in_transaction": 0,
        }
    ]
    assert scheduler_messages(scheduler_logs, logging.INFO)[-2:] == [
        "Notification scheduler cancelled during sleep",
        "Notification scheduler stopped",
    ]
