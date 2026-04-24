"""Safe sender utilities for Telegram message delivery with retry logic.

Handles:
- TelegramRetryAfter (Flood Control) - waits specified duration
- TelegramNetworkError / ClientOSError / ConnectionResetError - retries with exponential backoff
- RestartingTelegram - retries with backoff
"""
import asyncio
import logging
from typing import Callable, Any

from aiogram import Bot
from aiogram.types import Message
from aiogram.exceptions import (
    TelegramRetryAfter,
    TelegramNetworkError,
    RestartingTelegram,
)
from aiohttp import ClientOSError

logger = logging.getLogger(__name__)


async def safe_execute(func: Callable[..., Any], *args, max_retries: int = 3, **kwargs) -> Any:
    """
    Generic wrapper to robustly execute Telegram methods with retries.
    Handles FloodWait and Network Errors with exponential backoff.

    Args:
        func: Async callable to execute (e.g., bot.send_message, message.answer)
        *args: Positional arguments passed to func
        max_retries: Maximum number of retry attempts (default: 3)
        **kwargs: Keyword arguments passed to func

    Returns:
        Result of the function call

    Raises:
        Last caught exception if all retries exhausted
    """
    delay = 0.5

    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)

        except TelegramRetryAfter as e:
            wait_time = e.retry_after + 1
            logger.warning(
                f"Flood limit hit on attempt {attempt + 1}/{max_retries}. "
                f"Sleeping {wait_time}s."
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Max retries exceeded after flood limit.")
                raise

        except (TelegramNetworkError, ClientOSError, RestartingTelegram, ConnectionResetError, OSError) as e:
            if attempt == max_retries - 1:
                logger.error(
                    f"Network error failed after {max_retries} attempts: "
                    f"{type(e).__name__}: {e}"
                )
                raise

            logger.warning(
                f"Network error ({type(e).__name__}): {e}. "
                f"Retrying {attempt + 1}/{max_retries} after {delay}s..."
            )
            await asyncio.sleep(delay)
            delay *= 2  # Exponential backoff: 0.5 -> 1.0 -> 2.0

    return None


# ============================================================================
# Helper Shortcuts
# ============================================================================

async def safe_send_message(
    bot: Bot,
    chat_id: int | str,
    text: str,
    max_retries: int = 3,
    **kwargs: Any,
) -> Message | None:
    """
    Send a message with automatic retry on flood control and network errors.

    Args:
        bot: Bot instance
        chat_id: Target chat ID
        text: Message text
        max_retries: Maximum number of retry attempts (default: 3)
        **kwargs: Additional arguments passed to bot.send_message()

    Returns:
        Message object on success, None if all retries exhausted
    """
    return await safe_execute(
        bot.send_message, chat_id=chat_id, text=text, max_retries=max_retries, **kwargs
    )


async def safe_send_photo(
    bot: Bot,
    chat_id: int | str,
    photo: str,
    max_retries: int = 3,
    **kwargs: Any,
) -> Message | None:
    """
    Send a photo with automatic retry on flood control and network errors.

    Args:
        bot: Bot instance
        chat_id: Target chat ID
        photo: Photo file_id or URL
        max_retries: Maximum number of retry attempts (default: 3)
        **kwargs: Additional arguments passed to bot.send_photo()

    Returns:
        Message object on success, None if all retries exhausted
    """
    return await safe_execute(
        bot.send_photo, chat_id=chat_id, photo=photo, max_retries=max_retries, **kwargs
    )
