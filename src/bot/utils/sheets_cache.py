"""Unified Google Sheets cache helper."""

import asyncio
import json
import logging
from redis.asyncio import Redis

from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.config import config

logger = logging.getLogger(__name__)


async def get_client_sheets_data(client_code: str | list[str], redis: Redis) -> dict:
    """
    Get cached Google Sheets data or fetch from API.

    Rules:
    1) ALWAYS try Redis first: key = sheets_data:{client_code}
    2) If cache hit → return immediately
    3) If cache miss:
       - call GoogleSheetsChecker.find_client_group
       - store result in Redis (TTL 5 min)
       - return result

    Args:
        client_code: Client code or list of codes to fetch data for
        redis: Redis client instance

    Returns:
        Dict with 'found' and 'matches' keys
    """
    if isinstance(client_code, list):
        codes = client_code
    else:
        codes = [client_code]

    if not codes:
        return {"found": False, "matches": []}

    cache_key = f"sheets_data:{codes[0]}"

    cached = await redis.get(cache_key)
    if cached:
        try:
            if isinstance(cached, bytes):
                cached_str = cached.decode("utf-8")
            else:
                cached_str = cached

            result = json.loads(cached_str)
            logger.info(f"Cache HIT for sheets_data:{codes[0]}")
            return result
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to decode cached sheets data: {e}")

    logger.info(f"Cache MISS for sheets_data:{codes[0]}, fetching from API")

    try:
        checker = GoogleSheetsChecker(
            spreadsheet_id=config.google_sheets.SHEETS_ID,
            api_key=config.google_sheets.API_KEY,
            last_n_sheets=5,
        )

        result = await checker.find_client_group(codes)

        if result.get("found"):
            try:
                await redis.setex(
                    cache_key, 300, json.dumps(result, ensure_ascii=False)
                )
                logger.info(f"Cached sheets_data:{codes[0]} for 5 minutes")
            except Exception as e:
                logger.warning(f"Failed to cache sheets data: {e}")

        return result
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        logger.warning(f"Timeout fetching sheets data for {codes}")
        return {"found": False, "matches": [], "error": "timeout"}
    except Exception as e:
        logger.error(f"Error fetching sheets data for {codes}: {e}", exc_info=True)
        return {"found": False, "matches": [], "error": str(e)}
