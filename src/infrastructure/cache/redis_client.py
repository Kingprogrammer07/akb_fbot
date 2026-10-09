import logging
from urllib.parse import urlsplit

from redis.asyncio import Redis

from src import config

logger = logging.getLogger(__name__)


def _redacted_target(dsn: str, client: Redis) -> str:
    """Scheme, host, port and database of ``dsn``, safe to log.

    A DSN can carry credentials in its userinfo (``redis://user:secret@host``)
    or its query string (``unix:///redis.sock?password=secret``).  The target
    is rebuilt from an allowlist of the settings Redis parsed out of ``dsn``
    instead of by masking the DSN, so no spelling of a credential is logged.
    """
    settings = client.get_connection_kwargs()
    host = settings.get('host', 'localhost')
    port = settings.get('port', 6379)
    location = settings.get('path') or f'{host}:{port}'
    db = settings.get('db', 0)
    return f'{urlsplit(dsn).scheme}://{location}/{db}'


class RedisClient:
    """Manages Redis connection lifecycle."""

    def __init__(
        self,
        dsn: str = config.redis.dsn,
        max_connections: int = config.redis.MAX_CONNECTIONS,
        socket_timeout: float = config.redis.SOCKET_TIMEOUT,
        socket_connect_timeout: float = config.redis.SOCKET_CONNECT_TIMEOUT,
    ) -> None:
        self._dsn = dsn
        self._max_connections = max_connections
        self._socket_timeout = socket_timeout
        self._socket_connect_timeout = socket_connect_timeout
        self._client: Redis | None = None

    async def connect(self) -> Redis:
        """Create and return Redis connection."""
        if self._client is not None:
            logger.debug('Redis client already connected')
            return self._client

        self._client = Redis.from_url(
            url=self._dsn,
            decode_responses=True,
            max_connections=self._max_connections,
            socket_timeout=self._socket_timeout,
            socket_connect_timeout=self._socket_connect_timeout,
        )
        logger.info(
            'Creating Redis connection to %s...', _redacted_target(self._dsn, self._client)
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
