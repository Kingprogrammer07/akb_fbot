"""
Error response utilities with i18n support and admin logging.

This module provides standardized error responses for users with:
- Internationalized error messages (Uzbek/Russian)
- Automatic admin notification via logging system
- Support for both Message and CallbackQuery events
"""

import logging
from typing import Union

from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramAPIError

from src.bot.utils.i18n import i18n, get_user_language, DEFAULT_LANGUAGE

logger = logging.getLogger(__name__)


def _get_language_from_event(event: Union[Message, CallbackQuery]) -> str:
    """
    Extract user language from event.

    Priority:
    1. User's Telegram language_code
    2. Default language (uz)
    """
    user = event.from_user
    if user and user.language_code:
        return get_user_language(user.language_code)
    return DEFAULT_LANGUAGE


def _get_event_info(event: Union[Message, CallbackQuery]) -> dict:
    """Extract relevant info from event for logging."""
    user = event.from_user
    info = {
        "user_id": getattr(user, "id", "unknown") if user else "unknown",
        "username": getattr(user, "username", None) if user else None,
        "event_type": "callback_query" if isinstance(event, CallbackQuery) else "message",
    }

    if isinstance(event, CallbackQuery):
        info["callback_data"] = event.data
    elif isinstance(event, Message):
        info["message_text"] = (event.text or "")[:100] if event.text else None

    return info


async def reply_with_internal_error(
    event: Union[Message, CallbackQuery],
    error: Exception | None = None,
    handler_name: str | None = None,
) -> None:
    """
    Foydalanuvchiga texnik xatolik haqida xabar yuboradi.
    Message va CallbackQuery ikkalasi bilan ishlaydi.

    Bu funksiya:
    1. Foydalanuvchiga i18n orqali xabar yuboradi
    2. logger.error() orqali admin Telegram kanaliga xabar yuboradi

    Args:
        event: Message yoki CallbackQuery
        error: Xatolik obyekti (ixtiyoriy, log uchun)
        handler_name: Handler nomi (ixtiyoriy, log uchun)
    """
    # Extract event info for logging
    event_info = _get_event_info(event)
    user_id = event_info["user_id"]
    event_type = event_info["event_type"]

    # Get user language for i18n
    language = _get_language_from_event(event)

    # Build localized error message
    title = i18n.get(language, "error-internal-title")
    description = i18n.get(language, "error-internal-description")
    text = f"⚠️ <b>{title}</b>\n\n{description}"

    # Log error for admin notification (triggers ReliableTelegramLogHandler)
    log_context = {
        "user_id": user_id,
        "event_type": event_type,
        "handler": handler_name or "unknown",
    }

    if error:
        logger.error(
            f"Internal error in handler. "
            f"user_id={user_id}, event_type={event_type}, handler={handler_name or 'unknown'}, "
            f"error={type(error).__name__}: {error}",
            exc_info=error,
            extra=log_context,
        )
    else:
        logger.error(
            f"Internal error in handler. "
            f"user_id={user_id}, event_type={event_type}, handler={handler_name or 'unknown'}",
            extra=log_context,
        )

    # Send error message to user
    try:
        if isinstance(event, Message):
            await event.answer(text=text, parse_mode="HTML")

        elif isinstance(event, CallbackQuery):
            # Answer callback to stop loading indicator
            try:
                await event.answer()
            except TelegramAPIError:
                pass

            # Send message if possible
            if event.message:
                await event.message.answer(text=text, parse_mode="HTML")
            else:
                logger.warning(
                    f"CallbackQuery without message. user_id={user_id}"
                )

    except TelegramAPIError as tg_error:
        logger.error(
            f"Telegram API error while sending error message: {tg_error}",
            exc_info=True,
        )

    except Exception as e:
        logger.critical(
            f"Unexpected error inside reply_with_internal_error: {e}",
            exc_info=True,
        )


async def reply_with_error(
    event: Union[Message, CallbackQuery],
    error_key: str = "error-occurred",
    **kwargs,
) -> None:
    """
    Foydalanuvchiga xatolik xabari yuboradi (umumiy).

    Args:
        event: Message yoki CallbackQuery
        error_key: Fluent kalit nomi
        **kwargs: Fluent o'zgaruvchilari
    """
    language = _get_language_from_event(event)
    text = i18n.get(language, error_key, **kwargs)

    try:
        if isinstance(event, Message):
            await event.answer(text=text, parse_mode="HTML")

        elif isinstance(event, CallbackQuery):
            try:
                await event.answer()
            except TelegramAPIError:
                pass

            if event.message:
                await event.message.answer(text=text, parse_mode="HTML")

    except TelegramAPIError as tg_error:
        user_id = getattr(event.from_user, "id", "unknown")
        logger.error(
            f"Telegram API error while sending error message: {tg_error}, user_id={user_id}",
            exc_info=True,
        )
