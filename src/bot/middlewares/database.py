import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Update

from src.infrastructure.database.client import DatabaseClient

logger = logging.getLogger(__name__)


class DatabaseMiddleware(BaseMiddleware):
    """Middleware for providing database sessions to handlers.

    Ensures every request-scoped session is:
    1. Rolled back on ANY exception (prevents InFailedSQLTransactionError)
    2. Always closed in a finally block (prevents connection pool leaks)
    """

    def __init__(self, db_client: DatabaseClient):
        super().__init__()
        self.db_client = db_client

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        if 'session' in data:
            return await handler(event, data)

        async with self.db_client.session_factory() as session:
            data['session'] = session
            try:
                result = await handler(event, data)
                return result
            except TelegramBadRequest:
                # Telegram API errors leave the DB session in a clean state —
                # rolling back here would be misleading and trigger false ERROR logs.
                # GlobalErrorMiddleware handles suppression of known stale-callback errors.
                raise
            except Exception as e:
                logger.error(
                    f"DatabaseMiddleware caught error, rolling back session: {e}",
                    exc_info=True,
                )
                await session.rollback()
                raise
