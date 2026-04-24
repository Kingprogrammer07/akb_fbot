"""Global error handler middleware to suppress specific Telegram errors."""
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)


class GlobalErrorMiddleware(BaseMiddleware):
    """
    Global error middleware to catch and suppress specific Telegram errors.
    
    This prevents "query is too old" and similar errors from causing 500 webhook errors.
    These errors occur when users spam buttons or network is slow.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """Wrap handler execution to catch specific Telegram errors."""
        try:
            return await handler(event, data)
        except TelegramBadRequest as e:
            error_msg = str(e.message).lower() if e.message else ""
            
            # Suppress stale callback query errors
            if "query is too old" in error_msg or "query id is invalid" in error_msg:
                logger.warning(f"Ignored stale callback: {e.message}")
                return None  # Suppress error, mark as handled
            
            # Re-raise other TelegramBadRequest errors
            raise
