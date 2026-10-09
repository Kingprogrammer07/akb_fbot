"""Fakes for ``test_notification_scheduler``; its seeds live in ``_scheduler_seeds``.

Not collected by pytest: the module name does not start with ``test_``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import ParamSpec, TypeVar
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.infrastructure.database.models.client import Client

P = ParamSpec("P")
R = TypeVar("R")

# Every coroutine method of ``AsyncSession``.  Left out: the ``close_all``
# classmethod, which closes every session in the process instead of acting on
# one, and ``begin`` / ``begin_nested``, which return context managers that a
# coroutine wrapper would break.
AWAITABLE_SESSION_METHODS = (
    "aclose",
    "close",
    "commit",
    "connection",
    "delete",
    "execute",
    "flush",
    "get",
    "get_one",
    "invalidate",
    "merge",
    "refresh",
    "reset",
    "rollback",
    "run_sync",
    "scalar",
    "scalars",
    "stream",
    "stream_scalars",
)


class ConcurrentSessionUseDetector:
    """Records every session call that starts while another task is inside one.

    Each call yields to the event loop before it runs, so tasks sharing the
    session overlap deterministically instead of only when the database is slow.
    """

    def __init__(self) -> None:
        self._depth_by_task: dict[asyncio.Task[object] | None, int] = {}
        self.overlaps: list[str] = []

    def instrument(self, session: AsyncSession) -> None:
        for name in AWAITABLE_SESSION_METHODS:
            setattr(session, name, self._guard(name, getattr(session, name)))

    def _guard(
        self, name: str, call: Callable[P, Awaitable[R]]
    ) -> Callable[P, Awaitable[R]]:
        async def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
            task = asyncio.current_task()
            if any(other is not task for other in self._depth_by_task):
                self.overlaps.append(name)
            self._depth_by_task[task] = self._depth_by_task.get(task, 0) + 1
            try:
                await asyncio.sleep(0)
                return await call(*args, **kwargs)
            finally:
                self._depth_by_task[task] -= 1
                if not self._depth_by_task[task]:
                    del self._depth_by_task[task]

        return guarded


class SecondSessionRequested(BaseException):
    """A caller under test asked its ``DatabaseClient`` for a second session.

    Every caller needs exactly one, so a second request means a loop kept going,
    for instance after swallowing its cancellation.  It is a ``BaseException``
    so that the loop's ``except Exception`` handlers cannot catch it and spin
    forever.
    """


class SharedSessionDatabaseClient:
    """Stands in for ``DatabaseClient`` and hands out one prepared session once."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.sessions_handed_out = 0

    async def __aenter__(self) -> SharedSessionDatabaseClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def get_session(self) -> AsyncIterator[AsyncSession]:
        if self.sessions_handed_out:
            raise SecondSessionRequested
        self.sessions_handed_out += 1
        yield self._session


@dataclass
class StaticDataDAOStub:
    """``StaticDataDAO`` stand-in whose only row enables leftover notifications.

    ``read`` is set once the scheduler has read the row; its next step is to
    sleep for ``notification_period`` days.
    """

    notification: bool = True
    notification_period: int = 1
    read: asyncio.Event = field(default_factory=asyncio.Event)

    async def get_first(self, _session: AsyncSession) -> StaticDataDAOStub:
        self.read.set()
        return self


class ParkedSleeps:
    """Stands in for the scheduler module's ``asyncio`` and parks every sleep.

    ``sleep`` awaits ``on_sleep`` with the requested delay, sets ``sleeping`` and
    then waits until its task is cancelled, so a test can inspect what the
    scheduler holds while it sleeps.  Every other attribute is the real
    ``asyncio``'s.
    """

    def __init__(self, on_sleep: Callable[[float], Awaitable[None]]) -> None:
        self._on_sleep = on_sleep
        self.sleeping = asyncio.Event()

    def __getattr__(self, name: str) -> object:
        return getattr(asyncio, name)

    async def sleep(self, delay: float) -> None:
        await self._on_sleep(delay)
        self.sleeping.set()
        await asyncio.Event().wait()


@dataclass(frozen=True)
class SendAttempt:
    chat_id: int
    text: str
    options: dict[str, object]
    delivered: bool


@dataclass
class FakeTelegram:
    """``bot.send_message`` stand-in: one flood wait for one chat, one blocked chat.

    ``on_request`` runs while a request is in flight, ``on_delivered`` after a
    message has been delivered.
    """

    flood_chat_id: int | None = None
    blocked_chat_id: int | None = None
    on_request: Callable[[int], Awaitable[None]] | None = None
    on_delivered: Callable[[int], Awaitable[None]] | None = None
    attempts: list[SendAttempt] = field(default_factory=list)
    _flooded: bool = False

    def bot(self) -> AsyncMock:
        bot = AsyncMock()
        bot.send_message.side_effect = self.send_message
        return bot

    async def send_message(self, chat_id: int, text: str, **options: object) -> None:
        await asyncio.sleep(0)  # a real request yields to the event loop
        if self.on_request is not None:
            await self.on_request(chat_id)
        method = SendMessage(chat_id=chat_id, text=text)
        if chat_id == self.blocked_chat_id:
            self.attempts.append(SendAttempt(chat_id, text, options, delivered=False))
            raise TelegramForbiddenError(
                method=method, message="Forbidden: bot was blocked"
            )
        if chat_id == self.flood_chat_id and not self._flooded:
            self._flooded = True
            self.attempts.append(SendAttempt(chat_id, text, options, delivered=False))
            raise TelegramRetryAfter(
                method=method, message="Too Many Requests", retry_after=0
            )
        self.attempts.append(SendAttempt(chat_id, text, options, delivered=True))
        if self.on_delivered is not None:
            await self.on_delivered(chat_id)

    def delivered(self) -> dict[int, SendAttempt]:
        return {
            attempt.chat_id: attempt for attempt in self.attempts if attempt.delivered
        }


@dataclass
class FirstRecipientDeleter:
    """``FakeTelegram.on_delivered`` hook that deletes the first recipient's account.

    The recipient's notification then violates its foreign key and cannot be
    persisted, while every other recipient's can.
    """

    engine: AsyncEngine
    chat_id: int | None = None
    client_id: int | None = None

    async def __call__(self, chat_id: int) -> None:
        if self.chat_id is not None:
            return
        self.chat_id = chat_id
        async with async_sessionmaker(self.engine)() as session:
            result = await session.execute(
                delete(Client).where(Client.telegram_id == chat_id).returning(Client.id)
            )
            self.client_id = result.scalar_one()
            await session.commit()
