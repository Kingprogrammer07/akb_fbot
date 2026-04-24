"""Currency conversion cache helper."""
import logging
from redis.asyncio import Redis

from src.bot.utils.currency_converter import currency_converter

logger = logging.getLogger(__name__)

# Default fallback rate
DEFAULT_USD_TO_UZS_RATE = 12_000

# Cache TTL: 4 hours (14400 seconds)
CURRENCY_CACHE_TTL = 14400


from sqlalchemy.ext.asyncio import AsyncSession

async def convert_to_uzs(usd_amount: float, redis: Redis, session: AsyncSession) -> float:
    """
    Convert USD to UZS with Redis caching.
    
    Flow:
    1) Try Redis (key: currency:usd_uzs)
    2) If miss → call currency API
    3) Cache result (TTL: 4 hours)
    4) Fallback: DEFAULT_USD_TO_UZS_RATE
    
    Args:
        usd_amount: Amount in USD
        redis: Redis client instance
        
    Returns:
        Amount in UZS
    """
    cache_key = "currency:usd_uzs"
    
    # Try to get rate from cache
    cached_rate = await redis.get(cache_key)
    if cached_rate:
        try:
            # Decode Redis value (bytes → str)
            if isinstance(cached_rate, bytes):
                rate_str = cached_rate.decode("utf-8")
            else:
                rate_str = cached_rate
            
            rate = float(rate_str)
            logger.info(f"Cache HIT for currency:usd_uzs, rate={rate}")
            return usd_amount * rate
        except (ValueError, Exception) as e:
            logger.warning(f"Failed to decode cached currency rate: {e}")
            # Continue to fetch from API
    
    # Cache miss - fetch from API
    logger.info("Cache MISS for currency:usd_uzs, fetching from API")
    
    try:
        rate = await currency_converter.get_rate_async(session, "USD", "UZS")
        
        # Cache the rate
        try:
            await redis.setex(cache_key, CURRENCY_CACHE_TTL, str(rate))
            logger.info(f"Cached currency:usd_uzs={rate} for {CURRENCY_CACHE_TTL} seconds")
        except Exception as e:
            logger.warning(f"Failed to cache currency rate: {e}")
        
        return usd_amount * rate
    except Exception as e:
        logger.warning(f"Error fetching currency rate from API: {e}, using fallback")
        # Fallback to default rate
        return usd_amount * DEFAULT_USD_TO_UZS_RATE

