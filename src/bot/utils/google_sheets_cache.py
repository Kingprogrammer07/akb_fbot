"""Google Sheets cache utilities."""
import json
from typing import List, Dict, Optional
import aiohttp
from redis.asyncio import Redis

from src.config import Config

config = Config()

# Google Sheets Configuration
SPREADSHEET_ID = config.google_sheets.SHEETS_ID
API_KEY = config.google_sheets.API_KEY

META_URL = (
    f"https://sheets.googleapis.com/v4/spreadsheets/"
    f"{SPREADSHEET_ID}"
    f"?fields=sheets.properties"
    f"&key={API_KEY}"
)

# Redis cache keys
WORKSHEETS_CACHE_KEY = "google_sheets:worksheets"
CACHE_TTL = 3600  # 1 hour (in seconds)


async def fetch_worksheets_from_api() -> List[Dict[str, any]]:
    """
    Fetch all worksheets from Google Sheets API.

    Returns:
        List of worksheet dictionaries with 'title' and 'gid'
    """
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(META_URL) as r:
            r.raise_for_status()
            data = await r.json()

    sheets = data.get("sheets", [])

    return [
        {
            "title": s["properties"]["title"],
            "gid": s["properties"]["sheetId"]
        }
        for s in sheets
    ]


async def get_last_5_worksheets(redis: Redis, force_refresh: bool = False) -> List[Dict[str, any]]:
    """
    Get last 3 worksheets from cache or fetch from API.

    Args:
        redis: Redis connection
        force_refresh: If True, skip cache and fetch from API

    Returns:
        List of last 3 worksheets with 'title' and 'gid'
    """
    # Try to get from cache first
    if not force_refresh:
        cached_data = await redis.get(WORKSHEETS_CACHE_KEY)
        if cached_data:
            print("✅ Cache hit: Loading worksheets from Redis")
            return json.loads(cached_data)

    # Cache miss or force refresh - fetch from API
    print("🔄 Cache miss: Fetching worksheets from Google Sheets API")
    try:
        all_worksheets = await fetch_worksheets_from_api()

        # Get last 5 worksheets
        last_5 = all_worksheets[-5:] if len(all_worksheets) >= 5 else all_worksheets

        # Save to cache with TTL
        await redis.setex(
            WORKSHEETS_CACHE_KEY,
            CACHE_TTL,
            json.dumps(last_5, ensure_ascii=False)
        )

        print(f"💾 Cached {len(last_5)} worksheets for {CACHE_TTL} seconds")
        return last_5

    except Exception as e:
        print(f"❌ Error fetching worksheets: {e}")
        # Return empty list on error
        return []


async def clear_worksheets_cache(redis: Redis) -> bool:
    """
    Clear worksheets cache.

    Args:
        redis: Redis connection

    Returns:
        True if cache was cleared, False otherwise
    """
    result = await redis.delete(WORKSHEETS_CACHE_KEY)
    return result > 0


async def get_cached_worksheets(redis: Redis) -> Optional[List[Dict[str, any]]]:
    """
    Get worksheets from cache only (don't fetch from API if not cached).

    Args:
        redis: Redis connection

    Returns:
        List of worksheets or None if not cached
    """
    cached_data = await redis.get(WORKSHEETS_CACHE_KEY)
    if cached_data:
        return json.loads(cached_data)
    return None

