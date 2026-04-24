import logging

from redis.asyncio import Redis

from src import config

logger = logging.getLogger(__name__)


class RedisClient:
    """Manages Redis connection lifecycle."""

    def __init__(
        self, dsn: str = config.redis.dsn, max_connections: int = config.redis.MAX_CONNECTIONS
    ):
        self._dsn = dsn
        self._max_connections = max_connections
        self._client: Redis | None = None

    async def connect(self) -> Redis:
        """Create and return Redis connection."""
        if self._client is not None:
            logger.debug('Redis client already connected')
            return self._client

        logger.info(f'Creating Redis connection to {self._dsn}...')
        self._client = Redis.from_url(
            url=self._dsn,
            decode_responses=True,
            max_connections=self._max_connections,
        )
        try:
            await self._client.ping()
            logger.info('Redis connection established')
            return self._client
        except Exception as e:
            logger.error(f'Failed to connect to Redis: {e}', exc_info=True)
            await self.close()
            raise

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client is None:
            logger.debug('No Redis client to close')
            return

        logger.info('Closing Redis connection...')
        try:
            await self._client.close()
            logger.info('Redis connection closed')
        except Exception as e:
            logger.error(f'Error closing Redis connection: {e}', exc_info=True)
        finally:
            self._client = None

    @property
    def client(self) -> Redis | None:
        """Get current Redis client."""
        return self._client

    async def get_redis(self) -> Redis:
        """Get Redis connection (connects if not already connected)."""
        if self._client is None:
            await self.connect()
        return self._client
