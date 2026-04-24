from logging import getLogger
from typing import Any, Type, TypeVar

from pydantic import BaseModel
from redis.asyncio import Redis

logger = getLogger(__name__)
T = TypeVar('T')


class Cache:
    """Handles caching operations with Redis."""

    def __init__(self, client: Redis, default_ttl: int):
        self._client = client
        self.default_ttl = default_ttl

    async def set(self, key: str, value: BaseModel | Any, ex: int | None = None) -> None:
        """Set value in cache, optionally serialize model."""
        logger.debug(f'Setting cache key: {key}')
        try:
            serialized = value.model_dump_json() if hasattr(value, 'model_dump_json') else value
            await self._client.set(key, serialized, ex=ex or self.default_ttl)
            logger.debug(f'Redis set successful for key: {key}')
        except Exception as e:
            logger.error(f'Redis set failed for key: {key}: {e}')

    async def get(self, key: str, model: Type[T] | None = None) -> T | Any | None:
        """Get value from cache, optionally deserialize to model."""
        logger.debug(f'Getting cache key: {key}')
        try:
            value = await self._client.get(key)
            if value and model and hasattr(model, 'model_validate_json'):
                logger.debug(f'Deserialized to: {model.__name__}')
                return model.model_validate_json(value)
            return value
        except Exception as e:
            logger.error(f'Redis get failed for key: {key}: {e}')
            return None
