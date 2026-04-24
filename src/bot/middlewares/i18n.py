"""i18n middleware for automatic language detection."""
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.utils.i18n import i18n, get_user_language
from src.infrastructure.services.client import ClientService


class I18nMiddleware(BaseMiddleware):
    """Middleware to inject i18n and user language into handler data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Inject i18n and language into data."""
        # Get user from event
        user: User | None = data.get('event_from_user')
        language = "uz"  # Default

        # Priority 1: Get language from database (client.language_code)
        if user:
            session: AsyncSession | None = data.get('session')
            client_service: ClientService | None = data.get('client_service')

            if session and client_service:
                try:
                    client = await client_service.get_client(user.id, session)
                    if client and client.language_code:
                        language = get_user_language(client.language_code)
                except Exception:
                    # If database fetch fails, fall back to other methods
                    pass

        # Inject into data
        data['i18n'] = i18n
        data['language'] = language

        # Helper function for easy translation
        data['_'] = lambda key, **kwargs: i18n.get(language, key, **kwargs)

        return await handler(event, data)
