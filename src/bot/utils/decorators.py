import logging
from functools import wraps
from typing import Any, Union

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from src.bot.utils.responses import reply_with_internal_error

logger = logging.getLogger(__name__)


def handle_errors(func):
    """Decorator to handle errors in handlers with logging and user notification."""

    @wraps(func)
    async def wrapper(event: Union[Message, CallbackQuery], *args: Any, **kwargs: Any):
        try:
            return await func(event, *args, **kwargs)
        except TelegramBadRequest as e:
            logger.warning(
                f'Telegram API error in {func.__name__} for user {event.from_user.id}: {e}'
            )
            return None
        except Exception as e:
            session = kwargs.get('session')
            if session:
                await session.rollback()
            logger.error(
                f'Error processing {func.__name__} for user {event.from_user.id}: {e}',
                exc_info=True,
            )
            await reply_with_internal_error(event)
            return None

    return wrapper
