"""Services menu handlers."""

import asyncio
import json
import logging
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_private_chat import IsPrivate
from src.bot.filters.is_logged_in import ClientExists, IsRegistered, IsLoggedIn
from src.bot.keyboards.user.reply_keyb.profile_kyb import services_menu_kyb
from src.bot.utils.decorators import handle_errors
from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.infrastructure.services import ClientService
from src.config import config

logger = logging.getLogger(__name__)

services_router = Router(name="services")

_SHEETS_CACHE_TTL  = 300    # 5 minutes
_KEYBOARD_CACHE_TTL = 21600  # 6 hours


# ---------------------------------------------------------------------------
# Background helpers
# ---------------------------------------------------------------------------

async def cache_client_sheets_data(client_code: str, redis: Redis) -> None:
    """Pre-warm Google Sheets cache for the client (background task)."""
    try:
        checker = GoogleSheetsChecker(
            spreadsheet_id=config.google_sheets.SHEETS_ID,
            api_key=config.google_sheets.API_KEY,
            last_n_sheets=5,
        )
        result = await checker.find_client_group(client_code)
        if result["found"]:
            await redis.setex(
                f"sheets_data:{client_code}",
                _SHEETS_CACHE_TTL,
                json.dumps(result, ensure_ascii=False),
            )
    except Exception as e:
        logger.warning(f"Failed to cache sheets data for {client_code}: {e}")


async def _get_or_build_keyboard(language: str, redis: Redis, _: callable) -> ReplyKeyboardMarkup:
    """Return cached services keyboard or build and cache a fresh one."""
    cache_key = f"services_menu:{language}"
    cached    = await redis.get(cache_key)

    if cached:
        try:
            raw = cached.decode("utf-8") if isinstance(cached, bytes) else cached
            keyboard = ReplyKeyboardMarkup.model_validate(json.loads(raw))
            logger.debug(f"Services keyboard cache HIT (lang={language})")
            return keyboard
        except Exception as e:
            logger.warning(f"Failed to deserialize cached keyboard: {e}")

    # Cache miss — build fresh
    keyboard = services_menu_kyb(translator=_)
    try:
        await redis.setex(
            cache_key,
            _KEYBOARD_CACHE_TTL,
            json.dumps(keyboard.model_dump(), ensure_ascii=False),
        )
        logger.debug(f"Services keyboard cache MISS — cached for {_KEYBOARD_CACHE_TTL}s (lang={language})")
    except Exception as e:
        logger.warning(f"Failed to cache services menu keyboard: {e}")

    return keyboard


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@services_router.message(
    IsPrivate(),
    ClientExists(),
    IsRegistered(),
    IsLoggedIn(),
    F.text.in_(["🚚 Xizmatlar", "🚚 Услуги"]),
)
@handle_errors
async def services_menu_handler(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    redis: Redis,
    state: FSMContext,
    language: str,
):
    """Show services menu and pre-warm Google Sheets cache in background."""
    await state.clear()

    client   = await client_service.get_client(message.from_user.id, session)
    keyboard = await _get_or_build_keyboard(language, redis, _)

    if client:
        asyncio.create_task(cache_client_sheets_data(client.active_codes, redis))

    await message.answer(_("choose-action"), reply_markup=keyboard)