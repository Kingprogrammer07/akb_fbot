"""
Cached RBAC permissions must never be left without a TTL.

``RBACService.get_permissions`` filled the cache with ``SADD`` and set its
expiry in a second round trip, ``EXPIRE``.  When Redis became unreachable
between the two, the set stayed behind with no TTL, and the role's
permissions were served from it indefinitely instead of for at most
``PERMISSIONS_TTL`` seconds, outliving any permission change whose cache
invalidation did not get through.
"""

from collections.abc import AsyncIterator, Iterable
from contextlib import suppress
from types import SimpleNamespace

import fakeredis
import fakeredis.aioredis
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeConnection
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from src.infrastructure.cache.keys import CacheKeys
from src.infrastructure.services.admin_rbac_service import PERMISSIONS_TTL, RBACService

ROLE = "operator"
PERMISSIONS = frozenset({"cargo:read", "finance:read", "finance:write"})
CACHE_KEY = CacheKeys.role_permissions(ROLE)
# ``TTL`` answers -2 for a missing key and -1 for a key that never expires.
MISSING_KEY = -2


class FakeSession:
    """Answers the role lookup and counts the database round trips."""

    def __init__(self) -> None:
        self.queries = 0

    async def execute(self, _query: object) -> SimpleNamespace:
        self.queries += 1
        role = SimpleNamespace(
            name=ROLE,
            permissions=[SimpleNamespace(slug=slug) for slug in sorted(PERMISSIONS)],
        )
        return SimpleNamespace(scalar_one_or_none=lambda: role)


class Outage:
    """Fails every command send from a chosen one onwards, as a dropped Redis would."""

    def __init__(self) -> None:
        self._fail_from: int | None = None
        self._sends = 0

    def begin_at_send(self, number: int) -> None:
        """Start counting sends; the ``number``-th and every later one fails."""
        self._fail_from = number
        self._sends = 0

    def on_send(self) -> None:
        if self._fail_from is None:
            return
        self._sends += 1
        if self._sends >= self._fail_from:
            raise RedisConnectionError("Connection reset by peer")


class FlakyConnection(FakeConnection):
    """A fakeredis connection whose sends pass through an :class:`Outage`."""

    def __init__(self, *args: object, outage: Outage, **kwargs: object) -> None:
        self._outage = outage
        super().__init__(*args, **kwargs)

    async def send_packed_command(
        self, command: bytes | str | Iterable[bytes], check_health: bool = True
    ) -> None:
        self._outage.on_send()
        await super().send_packed_command(command, check_health)


@pytest.fixture
def server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest_asyncio.fixture
async def observer(server: fakeredis.FakeServer) -> AsyncIterator[Redis]:
    """A healthy client on the same server, to inspect what a call left behind."""
    client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    yield client
    await client.aclose()


async def test_populated_permissions_expire_and_are_served_from_the_cache() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    session = FakeSession()

    first = await RBACService.get_permissions(redis_client, session, ROLE)
    ttl = await redis_client.ttl(CACHE_KEY)
    second = await RBACService.get_permissions(redis_client, session, ROLE)

    assert first == second == PERMISSIONS
    assert 0 < ttl <= PERMISSIONS_TTL
    assert session.queries == 1


@pytest.mark.parametrize(
    "failing_send",
    [1, 2, 3],
    ids=[
        "redis-down-before-the-lookup",
        "redis-drops-at-the-first-write",
        "redis-drops-after-the-first-write",
    ],
)
async def test_permissions_are_never_cached_without_a_ttl(
    server: fakeredis.FakeServer, observer: Redis, failing_send: int
) -> None:
    outage = Outage()
    redis_client = Redis(
        connection_pool=ConnectionPool(
            connection_class=FlakyConnection,
            outage=outage,
            server=server,
            decode_responses=True,
        )
    )
    try:
        # Connect first, so only the sends made by the call under test count.
        await redis_client.ping()
        outage.begin_at_send(failing_send)

        # Whether the outage surfaces as an error depends on when it strikes;
        # what must hold either way is the state it leaves in Redis.
        with suppress(RedisConnectionError):
            await RBACService.get_permissions(redis_client, FakeSession(), ROLE)
    finally:
        await redis_client.aclose(close_connection_pool=True)

    ttl = await observer.ttl(CACHE_KEY)
    assert ttl == MISSING_KEY or 0 < ttl <= PERMISSIONS_TTL
