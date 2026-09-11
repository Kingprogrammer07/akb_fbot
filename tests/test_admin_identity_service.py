"""
Unit tests for :mod:`src.infrastructure.services.admin_identity_service`.

These cover the cache mechanics that ``test_admin_jwt_revocation.py`` exercises
only indirectly: the negative cache, malformed entries, byte-returning Redis
clients, and the version stamp that stops an in-flight request from restoring a
revoked identity.
"""
import json

import fakeredis.aioredis
import pytest

from src.infrastructure.cache.keys import CacheKeys
from src.infrastructure.database.dao.admin_account import AdminAccountDAO
from src.infrastructure.services.admin_identity_service import (
    IDENTITY_VERSION_TTL,
    AdminIdentity,
    AdminIdentityService,
)

ADMIN_ID = 7


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


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def raw_redis_client():
    """A client that returns bytes, as one configured without decoding does."""
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


def stub_dao(monkeypatch, account) -> DAOSpy:
    spy = DAOSpy(account)
    monkeypatch.setattr(AdminAccountDAO, "get_by_id_with_relations", staticmethod(spy))
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
