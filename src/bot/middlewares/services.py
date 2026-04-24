from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Update


class ServiceMiddleware(BaseMiddleware):
    """Middleware for injecting services into handlers."""

    def __init__(self, services: Dict[str, Any]):
        super().__init__()
        self.services = services

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        # Inject services into handler data
        data.update(self.services)
        return await handler(event, data)
