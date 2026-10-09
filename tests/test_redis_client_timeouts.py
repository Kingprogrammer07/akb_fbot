"""
``RedisClient`` must bound every wait on Redis.

It used to build its connection pool without socket timeouts.  A Redis host
that stopped answering (a blackholed address, a frozen or paused server) then
left every request awaiting a reply until the operating system gave up, which
for a read is never, instead of failing fast with a Redis error.
"""

import asyncio
import socket
import time
from collections.abc import Iterator

import pytest
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import TimeoutError as RedisTimeoutError

from src.config import RedisConfig, config
from src.infrastructure.cache.redis_client import RedisClient

TIMEOUT_FIELDS = ("SOCKET_TIMEOUT", "SOCKET_CONNECT_TIMEOUT")

# Private address with no host behind it: a connection attempt is never
# answered, so only a connect timeout can end it.
UNROUTABLE_DSN = "redis://10.255.255.1:6379/0"

CONFIGURED_TIMEOUT = 0.5
# Passed for the timeout a test is not about, so only the timeout under test
# can end the wait before HANG_GUARD does.
UNBOUNDED = 60.0
# Slack for a busy machine, still far below what an unbounded wait takes.
ELAPSED_LIMIT = 3.0
# Turns a regression into a test failure instead of a hung test run.
HANG_GUARD = 10.0


@pytest.fixture
def ping_without_a_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let ``connect`` succeed with no Redis running, so only the pool is inspected."""

    async def _ping(_self: Redis, **_kwargs: object) -> bool:
        return True

    monkeypatch.setattr(Redis, "ping", _ping)


@pytest.fixture
def unresponsive_server_dsn() -> Iterator[str]:
    """
    A listening socket that is never accepted: the kernel completes the TCP
    handshake, so the client connects, but no reply ever arrives, which is how
    a frozen or paused Redis looks from the client.
    """
    with socket.create_server(("127.0.0.1", 0)) as listener:
        host, port = listener.getsockname()[:2]
        yield f"redis://{host}:{port}/0"


def test_timeouts_default_to_five_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    for field in TIMEOUT_FIELDS:
        monkeypatch.delenv(f"REDIS_{field}", raising=False)

    settings = RedisConfig(_env_file=None)

    assert settings.SOCKET_TIMEOUT == 5.0
    assert settings.SOCKET_CONNECT_TIMEOUT == 5.0


def test_timeouts_are_read_from_the_redis_environment_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDIS_SOCKET_TIMEOUT", "2.5")
    monkeypatch.setenv("REDIS_SOCKET_CONNECT_TIMEOUT", "1.25")

    settings = RedisConfig(_env_file=None)

    assert settings.SOCKET_TIMEOUT == 2.5
    assert settings.SOCKET_CONNECT_TIMEOUT == 1.25


@pytest.mark.parametrize("value", ["0", "-1", "inf", "nan"])
@pytest.mark.parametrize("field", TIMEOUT_FIELDS)
def test_timeouts_must_be_positive_and_finite(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    """A zero or negative timeout fails every command; infinity or NaN removes the bound."""
    monkeypatch.setenv(f"REDIS_{field}", value)

    with pytest.raises(ValidationError, match=field):
        RedisConfig(_env_file=None)


@pytest.mark.usefixtures("ping_without_a_server")
async def test_client_is_built_with_the_given_timeouts() -> None:
    redis_client = RedisClient(
        dsn="redis://127.0.0.1:6379/0", socket_timeout=1.5, socket_connect_timeout=0.75
    )

    client = await redis_client.connect()
    try:
        connection_kwargs = client.connection_pool.connection_kwargs
        assert connection_kwargs["socket_timeout"] == 1.5
        assert connection_kwargs["socket_connect_timeout"] == 0.75
    finally:
        await redis_client.close()


@pytest.mark.usefixtures("ping_without_a_server")
async def test_client_uses_the_configured_timeouts_by_default() -> None:
    """The application builds its client as ``RedisClient()``."""
    redis_client = RedisClient()

    client = await redis_client.connect()
    try:
        connection_kwargs = client.connection_pool.connection_kwargs
        assert connection_kwargs["socket_timeout"] == config.redis.SOCKET_TIMEOUT
        assert (
            connection_kwargs["socket_connect_timeout"]
            == config.redis.SOCKET_CONNECT_TIMEOUT
        )
    finally:
        await redis_client.close()


async def test_connect_to_an_unroutable_address_fails_within_the_connect_timeout() -> (
    None
):
    redis_client = RedisClient(
        dsn=UNROUTABLE_DSN,
        socket_timeout=UNBOUNDED,
        socket_connect_timeout=CONFIGURED_TIMEOUT,
    )

    started = time.monotonic()
    with pytest.raises(RedisTimeoutError):
        await asyncio.wait_for(redis_client.connect(), HANG_GUARD)

    assert time.monotonic() - started < ELAPSED_LIMIT


async def test_unresponsive_server_fails_within_the_socket_timeout(
    unresponsive_server_dsn: str,
) -> None:
    redis_client = RedisClient(
        dsn=unresponsive_server_dsn,
        socket_timeout=CONFIGURED_TIMEOUT,
        socket_connect_timeout=UNBOUNDED,
    )

    started = time.monotonic()
    with pytest.raises(RedisTimeoutError):
        await asyncio.wait_for(redis_client.connect(), HANG_GUARD)

    assert time.monotonic() - started < ELAPSED_LIMIT
