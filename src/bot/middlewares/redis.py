"""Redis middleware for injecting Redis connection into handlers."""
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Update
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class RedisMiddleware(BaseMiddleware):
    """Middleware for providing Redis connection to handlers."""

    def __init__(self, redis: Redis):
        super().__init__()
        self.redis = redis

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        """Inject Redis connection into handler data."""
        data['redis'] = self.redis
        return await handler(event, data)
