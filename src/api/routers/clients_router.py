"""Client image proxy API endpoints.

- GET /resolve/{file_id} - Resolve file_id to temporary URL

Frontend should use the file_id metadata endpoints from client_router.py
and resolve URLs on-demand.
"""
import logging
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from redis.asyncio import Redis
from src.bot.bot_instance import bot
from src.api.dependencies import get_db, get_redis, get_admin_user
from src.api.services.telegram_file_service import TelegramFileService
from src.infrastructure.database.models.client import Client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clients", tags=["clients-images"])


# ==================== NEW: File ID Resolution Endpoint ====================

@router.get(
    "/resolve/{file_id}",
    summary="Resolve file_id to temporary URL",
    description="Resolves a Telegram file_id to a temporary URL. "
                "Use this when you need a fresh URL for a file_id."
)
async def resolve_file_id(
    file_id: str,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _admin: Client = Depends(get_admin_user),
):
    """
    Resolve a file_id to a temporary Telegram URL.

    NEW PREFERRED ENDPOINT - Returns URL instead of binary data.

    The returned URL is valid for approximately 1 hour.
    Frontend should cache this URL and call again when needed.

    Args:
        file_id: Telegram file_id

    Returns:
        JSON with file_id, telegram_url, and metadata
    """
    telegram_service = TelegramFileService(bot, redis)

    # Validate and get URL
    validation = await telegram_service.validate_file_id(file_id)

    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invalid or expired file_id: {validation.error}"
        )

    url = await telegram_service.get_file_url(file_id)

    return {
        "file_id": file_id,
        "telegram_url": url,
        "valid": True,
        "cache_hint": "URL valid for approximately 1 hour"
    }
