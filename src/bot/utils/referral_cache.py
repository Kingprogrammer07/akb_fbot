"""Referral cache utilities using Redis."""
import json
from redis.asyncio import Redis
from typing import Dict, Optional

# Referral data TTL: 24 hours (enough time for user to complete registration)
REFERRAL_TTL = 86400


async def save_referral_data(
    redis: Redis,
    telegram_id: int,
    referrer_telegram_id: int,
    referrer_client_code: Optional[str] = None
) -> None:
    """
    Save referral data to Redis cache.

    Args:
        redis: Redis connection
        telegram_id: New user's telegram ID
        referrer_telegram_id: Referrer's telegram ID
        referrer_client_code: Referrer's client code (optional)
    """
    key = f"referral:{telegram_id}"
    data = {
        "referrer_telegram_id": referrer_telegram_id,
        "referrer_client_code": referrer_client_code
    }

    await redis.setex(
        key,
        REFERRAL_TTL,
        json.dumps(data)
    )


async def get_referral_data(
    redis: Redis,
    telegram_id: int
) -> Optional[Dict[str, any]]:
    """
    Get referral data from Redis cache.

    Args:
        redis: Redis connection
        telegram_id: User's telegram ID

    Returns:
        Dict with referrer_telegram_id and referrer_client_code, or None if not found
    """
    key = f"referral:{telegram_id}"
    data = await redis.get(key)

    if not data:
        return None

    return json.loads(data)


async def delete_referral_data(
    redis: Redis,
    telegram_id: int
) -> None:
    """
    Delete referral data from Redis cache.

    Args:
        redis: Redis connection
        telegram_id: User's telegram ID
    """
    key = f"referral:{telegram_id}"
    await redis.delete(key)
