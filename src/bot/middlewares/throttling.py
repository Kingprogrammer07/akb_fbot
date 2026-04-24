"""Throttling middleware for rate limiting user requests."""
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    """
    Redis-based throttling middleware to prevent double-clicks and spam.
    
    Default limit is 0.5 seconds - balances UX responsiveness with anti-spam protection.
    When throttled, CallbackQuery events receive a silent answer to stop the loading animation.
    """

    def __init__(self, redis: Redis, limit: float = 0.5):
        """
        Initialize throttling middleware.
        
        Args:
            redis: Redis connection instance
            limit: Time window in seconds between allowed requests (default: 0.5s)
        """
        super().__init__()
        self.redis = redis
        self.limit = limit

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """
        Process event with throttling check.
        
        Only throttles Messages and CallbackQueries from users.
        System events (without user context) pass through unchanged.
        """
        # Only throttle events from users
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # Unique key per user
        key = f"throttle:{user.id}"

        # Check if user is currently throttled
        if await self.redis.get(key):
            logger.debug(f"Throttled user {user.id}")
            # If it's a callback, stop the loading animation
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("⏳ Shoshmang...", show_alert=True)
                except Exception:
                    pass  # Ignore answer errors on throttled requests
            # CRITICAL: Stop execution here - do not call handler
            return None

        # Set throttle key with expiry
        await self.redis.set(key, "1", px=int(self.limit * 1000))

        return await handler(event, data)
