"""
Unit tests for :mod:`src.infrastructure.services.admin_identity_service`.

These cover the cache mechanics that ``test_admin_jwt_revocation.py`` exercises
only indirectly: the negative cache, malformed entries, byte-returning Redis
clients, the version stamp that stops an in-flight request from restoring a
revoked identity, and invalidation when Redis is unavailable.  They also pin
down the Telegram id to AdminAccount PK translation used by bot handlers.
"""
import json
import logging

import fakeredis.aioredis
import pytest
from redis.asyncio.client import Pipeline

from src.infrastructure.cache.keys import CacheKeys
from src.infrastructure.database.dao.admin_account import AdminAccountDAO
from src.infrastructure.services.admin_identity_service import (
    IDENTITY_VERSION_TTL,
    AdminIdentity,
    AdminIdentityService,
    resolve_admin_pk_by_telegram_id,
)

SERVICE_LOGGER = "src.infrastructure.services.admin_identity_service"

ADMIN_ID = 7
TELEGRAM_ID = 5_550_001


class StubAccount:
    def __init__(self, is_active: bool = True, role_name: str = "finance") -> None:
        self.id = ADMIN_ID
        self.is_active = is_active
        self.role_name = role_name


class DAOSpy:
    def __init__(self, account) -> None:
        self.account = account
        self.calls = 0

    async def __call__(self, session, admin_id: int):
        self.calls += 1
        return self.account


class TelegramLookupSpy:
    """Stands in for ``AdminAccountDAO.get_id_by_telegram_id``."""

    def __init__(self, admin_pk: int | None) -> None:
        self.admin_pk = admin_pk
        self.calls: list[int] = []

    async def __call__(self, session: object, telegram_id: int) -> int | None:
        self.calls.append(telegram_id)
        return self.admin_pk


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def raw_redis_client():
    """A client that returns bytes, as one configured without decoding does."""
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


@pytest.fixture
def unreachable_redis() -> fakeredis.aioredis.FakeRedis:
    """A client whose every command fails as if the Redis server were down."""
    server = fakeredis.FakeServer()
    server.connected = False
    return fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)


def stub_dao(monkeypatch, account) -> DAOSpy:
    spy = DAOSpy(account)
    monkeypatch.setattr(AdminAccountDAO, "get_by_id_with_relations", staticmethod(spy))
    return spy


def stub_telegram_lookup(
    monkeypatch: pytest.MonkeyPatch, admin_pk: int | None
) -> TelegramLookupSpy:
    spy = TelegramLookupSpy(admin_pk)
    monkeypatch.setattr(AdminAccountDAO, "get_id_by_telegram_id", staticmethod(spy))
    return spy


async def test_reads_through_to_the_database_on_a_cold_cache(redis_client, monkeypatch):
    stub_dao(monkeypatch, StubAccount())

    identity = await AdminIdentityService.get(redis_client, None, ADMIN_ID)

    assert identity == AdminIdentity(admin_id=ADMIN_ID, is_active=True, role_name="finance")


async def test_missing_account_is_negatively_cached(redis_client, monkeypatch):
    """A signed token for a deleted admin must not cost a query per request."""
    spy = stub_dao(monkeypatch, None)

    assert await AdminIdentityService.get(redis_client, None, ADMIN_ID) is None
    assert await AdminIdentityService.get(redis_client, None, ADMIN_ID) is None

    assert spy.calls == 1


async def test_bytes_returning_client_is_supported(raw_redis_client, monkeypatch):
    spy = stub_dao(monkeypatch, StubAccount())

    first = await AdminIdentityService.get(raw_redis_client, None, ADMIN_ID)
    second = await AdminIdentityService.get(raw_redis_client, None, ADMIN_ID)

    assert first == second
    assert spy.calls == 1, "the cached entry should have been readable"


async def test_malformed_entry_falls_back_to_the_database(redis_client, monkeypatch):
    spy = stub_dao(monkeypatch, StubAccount())
    await redis_client.setex(CacheKeys.admin_identity(ADMIN_ID), 60, "not-json{")

    identity = await AdminIdentityService.get(redis_client, None, ADMIN_ID)

    assert identity is not None
    assert spy.calls == 1


async def test_entry_without_a_role_name_falls_back_to_the_database(redis_client, monkeypatch):
    spy = stub_dao(monkeypatch, StubAccount())
    await redis_client.setex(
        CacheKeys.admin_identity(ADMIN_ID),
        60,
        json.dumps({"v": 0, "exists": True, "is_active": True}),
    )

    identity = await AdminIdentityService.get(redis_client, None, ADMIN_ID)

    assert identity is not None
    assert identity.role_name == "finance"
    assert spy.calls == 1


async def test_invalidate_bumps_the_version_and_bounds_its_lifetime(redis_client):
    await AdminIdentityService.invalidate(redis_client, ADMIN_ID)

    version_key = CacheKeys.admin_identity_version(ADMIN_ID)
    assert await redis_client.get(version_key) == "1"
    assert 0 < await redis_client.ttl(version_key) <= IDENTITY_VERSION_TTL


async def test_invalidate_forces_a_fresh_read(redis_client, monkeypatch):
    account = StubAccount()
    spy = stub_dao(monkeypatch, account)

    await AdminIdentityService.get(redis_client, None, ADMIN_ID)
    account.is_active = False
    await AdminIdentityService.invalidate(redis_client, ADMIN_ID)

    identity = await AdminIdentityService.get(redis_client, None, ADMIN_ID)

    assert identity is not None and identity.is_active is False
    assert spy.calls == 2


async def test_inflight_request_cannot_restore_a_revoked_identity(redis_client, monkeypatch):
    """
    A request that read the account *before* a revocation still writes its
    snapshot afterwards.  That write must not resurrect the old state, or a
    dismissed admin would keep working for another cache lifetime.
    """
    account = StubAccount(is_active=True)
    revoked = False

    async def racing_lookup(session, admin_id: int):
        nonlocal revoked
        # The revocation lands between this request reading the row and
        # writing its result back to Redis.
        if not revoked:
            revoked = True
            await AdminIdentityService.invalidate(redis_client, ADMIN_ID)
            account.is_active = False
            return StubAccount(is_active=True)  # the snapshot read pre-revocation
        return account

    monkeypatch.setattr(
        AdminAccountDAO, "get_by_id_with_relations", staticmethod(racing_lookup)
    )

    stale = await AdminIdentityService.get(redis_client, None, ADMIN_ID)
    assert stale is not None and stale.is_active is True  # this request is lost

    # The next request must not be served the resurrected entry.
    identity = await AdminIdentityService.get(redis_client, None, ADMIN_ID)

    assert identity is not None and identity.is_active is False


async def test_invalidate_sends_its_commands_as_one_transaction(
    redis_client: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Bumping the version and dropping the entry must land atomically and in one
    round trip, never as separate commands issued on the client.
    """
    transactions: list[bool] = []
    direct_commands: list[str] = []
    open_pipeline = redis_client.pipeline
    execute_command = redis_client.execute_command

    def recording_pipeline(
        transaction: bool = True, shard_hint: str | None = None
    ) -> Pipeline:
        transactions.append(transaction)
        return open_pipeline(transaction=transaction, shard_hint=shard_hint)

    async def recording_execute_command(*args: object, **options: object) -> object:
        direct_commands.append(str(args[0]))
        return await execute_command(*args, **options)

    monkeypatch.setattr(redis_client, "pipeline", recording_pipeline)
    monkeypatch.setattr(redis_client, "execute_command", recording_execute_command)

    await AdminIdentityService.invalidate(redis_client, ADMIN_ID)

    assert transactions == [True]
    assert direct_commands == []


async def test_invalidate_logs_and_returns_when_redis_is_unavailable(
    unreachable_redis: fakeredis.aioredis.FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Invalidation runs after the database commit.  Raising there would report a
    failure for a change that is already saved, while the stale entry still
    expires within ``IDENTITY_TTL``; the outage must be logged, not raised.
    """
    with caplog.at_level(logging.WARNING, logger=SERVICE_LOGGER):
        await AdminIdentityService.invalidate(unreachable_redis, ADMIN_ID)

    warnings = [
        record
        for record in caplog.records
        if record.name == SERVICE_LOGGER and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert f"admin_id={ADMIN_ID}" in warnings[0].getMessage()


async def test_resolve_admin_pk_returns_the_admin_account_primary_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = stub_telegram_lookup(monkeypatch, ADMIN_ID)

    assert await resolve_admin_pk_by_telegram_id(None, TELEGRAM_ID) == ADMIN_ID
    assert spy.calls == [TELEGRAM_ID]


@pytest.mark.parametrize("telegram_id", [None, 0])
async def test_resolve_admin_pk_skips_the_lookup_without_a_telegram_id(
    monkeypatch: pytest.MonkeyPatch, telegram_id: int | None
) -> None:
    spy = stub_telegram_lookup(monkeypatch, ADMIN_ID)

    assert await resolve_admin_pk_by_telegram_id(None, telegram_id) is None
    assert spy.calls == []


async def test_resolve_admin_pk_warns_when_the_operator_has_no_admin_account(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """
    ``None`` is the right answer, but it drops the operator from per-cashier
    log filters, so it must leave a trace naming the Telegram id.
    """
    stub_telegram_lookup(monkeypatch, None)

    with caplog.at_level(logging.WARNING, logger=SERVICE_LOGGER):
        assert await resolve_admin_pk_by_telegram_id(None, TELEGRAM_ID) is None

    assert any(
        f"telegram_id={TELEGRAM_ID}" in record.getMessage()
        for record in caplog.records
        if record.name == SERVICE_LOGGER and record.levelno == logging.WARNING
    )
