"""
Redis credentials must reach Redis intact and must never reach the logs.

``RedisConfig.dsn`` appended the username after ``:<password>``, producing
``redis://:passworduser@host`` when both were set, and left ``/`` unencoded,
so a password containing one cut the URL short.  ``RedisClient.connect``
logged the whole DSN at INFO, password included.
"""

import logging

import pytest
from pydantic import SecretStr
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from src.config import RedisConfig
from src.infrastructure.cache.redis_client import RedisClient

HOST = "cache.internal"
PORT = 6380
DB = 2

# Every character with a meaning inside a URL, plus a non-ASCII one.
RESERVED = "p@ss:w/rd?#%&= +é"
RESERVED_ENCODED = "p%40ss%3Aw%2Frd%3F%23%25%26%3D%20%2B%C3%A9"

SECRET_USERNAME = "cache-user"
SECRET_PASSWORD = "s3cret/p@ss"
SECRET_PASSWORD_ENCODED = "s3cret%2Fp%40ss"

# DSN spelling -> (dsn, the redacted target that may be logged)
CREDENTIAL_DSNS: dict[str, tuple[str, str]] = {
    "userinfo": (
        f"redis://{SECRET_USERNAME}:{SECRET_PASSWORD_ENCODED}@{HOST}:{PORT}/{DB}",
        f"redis://{HOST}:{PORT}/{DB}",
    ),
    "query-string": (
        f"redis://{HOST}:{PORT}/{DB}"
        f"?username={SECRET_USERNAME}&password={SECRET_PASSWORD_ENCODED}",
        f"redis://{HOST}:{PORT}/{DB}",
    ),
    "unix-socket": (
        f"unix:///var/run/redis.sock?db={DB}&password={SECRET_PASSWORD_ENCODED}",
        f"unix:///var/run/redis.sock/{DB}",
    ),
}


def build_config(username: str | None, password: str | None) -> RedisConfig:
    return RedisConfig(
        _env_file=None,
        HOST=HOST,
        PORT=PORT,
        DB=DB,
        USERNAME=username,
        PASSWORD=None if password is None else SecretStr(password),
    )


def leaked_credentials(text: str) -> list[str]:
    """Every spelling of the test credentials that occurs in ``text``."""
    spellings = (SECRET_USERNAME, SECRET_PASSWORD, SECRET_PASSWORD_ENCODED)
    return [spelling for spelling in spellings if spelling in text]


@pytest.fixture
def ping_without_a_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let ``connect`` succeed with no Redis running."""

    async def _ping(_self: Redis, **_kwargs: object) -> bool:
        return True

    monkeypatch.setattr(Redis, "ping", _ping)


@pytest.mark.parametrize(
    ("username", "password", "expected"),
    [
        (None, None, f"redis://{HOST}:{PORT}/{DB}"),
        ("", "", f"redis://{HOST}:{PORT}/{DB}"),
        (None, "hunter2", f"redis://:hunter2@{HOST}:{PORT}/{DB}"),
        ("cache-user", None, f"redis://cache-user@{HOST}:{PORT}/{DB}"),
        ("cache-user", "hunter2", f"redis://cache-user:hunter2@{HOST}:{PORT}/{DB}"),
        (
            RESERVED,
            RESERVED,
            f"redis://{RESERVED_ENCODED}:{RESERVED_ENCODED}@{HOST}:{PORT}/{DB}",
        ),
    ],
    ids=[
        "no-auth",
        "empty-credentials",
        "password-only",
        "username-only",
        "username-and-password",
        "reserved-characters",
    ],
)
def test_dsn_puts_username_before_password_and_encodes_both(
    username: str | None, password: str | None, expected: str
) -> None:
    assert build_config(username, password).dsn == expected


@pytest.mark.parametrize(
    ("username", "password"),
    [
        (None, None),
        (None, "hunter2"),
        ("cache-user", None),
        ("cache-user", "hunter2"),
        (RESERVED, RESERVED),
    ],
    ids=[
        "no-auth",
        "password-only",
        "username-only",
        "username-and-password",
        "reserved-characters",
    ],
)
async def test_redis_parses_the_dsn_back_to_the_configured_settings(
    username: str | None, password: str | None
) -> None:
    client = Redis.from_url(build_config(username, password).dsn)
    try:
        settings = client.get_connection_kwargs()
        assert settings.get("username") == username
        assert settings.get("password") == password
        assert (settings.get("host"), settings.get("port"), settings.get("db")) == (
            HOST,
            PORT,
            DB,
        )
    finally:
        await client.aclose()


@pytest.mark.usefixtures("ping_without_a_server")
@pytest.mark.parametrize(
    ("dsn", "target"), list(CREDENTIAL_DSNS.values()), ids=list(CREDENTIAL_DSNS)
)
async def test_connect_logs_the_target_but_no_credentials(
    dsn: str, target: str, caplog: pytest.LogCaptureFixture
) -> None:
    redis_client = RedisClient(dsn=dsn)

    with caplog.at_level(logging.DEBUG):
        await redis_client.connect()
        await redis_client.close()

    assert f"Creating Redis connection to {target}..." in caplog.messages
    assert leaked_credentials(caplog.text) == []


async def test_a_failed_connect_logs_no_credentials(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def _refused(_self: Redis, **_kwargs: object) -> bool:
        raise RedisConnectionError(
            f"Error 111 connecting to {HOST}:{PORT}. Connection refused."
        )

    monkeypatch.setattr(Redis, "ping", _refused)
    dsn, _target = CREDENTIAL_DSNS["userinfo"]

    with caplog.at_level(logging.DEBUG), pytest.raises(RedisConnectionError):
        await RedisClient(dsn=dsn).connect()

    assert "Failed to connect to Redis" in caplog.text
    assert leaked_credentials(caplog.text) == []
