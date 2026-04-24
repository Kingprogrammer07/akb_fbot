"""LastSeenMiddleware — updates clients.last_seen_at on every bot interaction."""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Update
from sqlalchemy import select, update as sa_update

from src.infrastructure.tools.datetime_utils import get_current_time

logger = logging.getLogger(__name__)


class LastSeenMiddleware(BaseMiddleware):
    """
    Updates ``clients.last_seen_at`` for every authenticated Telegram user
    that interacts with the bot.

    Runs as an outer update middleware so it fires before FSM handlers.
    It never blocks the handler — any DB error is silently logged.
    """

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        telegram_id: int | None = None

        if event.message and event.message.from_user:
            telegram_id = event.message.from_user.id
        elif event.callback_query and event.callback_query.from_user:
            telegram_id = event.callback_query.from_user.id

        if telegram_id:
            session = data.get("session")
            if session is not None:
                try:
                    from src.infrastructure.database.models.client import Client

                    await session.execute(
                        sa_update(Client)
                        .where(Client.telegram_id == telegram_id)
                        .values(last_seen_at=get_current_time())
                    )
                    await session.commit()
                except Exception as exc:
                    logger.debug("last_seen_at update failed: %s", exc)

        return await handler(event, data)
