"""
The admin-management endpoints must drop the cached identity of the account
they change.

Without these tests, deleting an ``AdminIdentityService.invalidate`` call from
a handler would break nothing visibly: revocation would silently degrade from
"immediate" to "within ``IDENTITY_TTL`` seconds", which is exactly the class of
regression this work exists to prevent.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import fakeredis.aioredis
import pytest

from src.api.dependencies import AdminJWTPayload
from src.api.routers import admin_management
from src.infrastructure.cache.keys import CacheKeys
from src.infrastructure.database.dao.admin_account import AdminAccountDAO
from src.infrastructure.database.dao.admin_audit_log import AdminAuditLogDAO
from src.infrastructure.database.dao.role import RoleDAO
from src.infrastructure.schemas.admin_management import (
    UpdateAdminAccountRequest,
    UpdateAdminStatusRequest,
)
from src.infrastructure.services.admin_rbac_service import RBACService

TARGET_ID = 11
ACTING_ADMIN = AdminJWTPayload(admin_id=1, role_name="super-admin", jti="jti-1")


def make_target(role_id: int = 2, role_name: str = "operator"):
    """An object shaped like the AdminAccount row the handlers work with."""
    return SimpleNamespace(
        id=TARGET_ID,
        system_username="target_admin",
        is_active=True,
        failed_login_attempts=0,
        role_id=role_id,
        role_name=role_name,
        role=SimpleNamespace(id=role_id, name=role_name, home_page=None),
        created_at=datetime.now(timezone.utc),
        client=SimpleNamespace(
            id=99,
            telegram_id=1234,
            full_name="Target Admin",
            phone=None,
            username=None,
            client_code="AKB-1",
        ),
    )


class FakeSession:
    """Just enough AsyncSession surface for these handlers."""

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj) -> None:
        return None

    async def delete(self, _obj) -> None:
        return None


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def session():
    return FakeSession()


@pytest.fixture(autouse=True)
def stub_persistence(monkeypatch):
    """Silence the audit log and the RBAC cache; neither is under test here."""

    async def _log(**_kwargs):
        return None

    async def _invalidate_role(_redis, _role_name):
        return None

    monkeypatch.setattr(AdminAuditLogDAO, "log", staticmethod(_log))
    monkeypatch.setattr(RBACService, "invalidate_role", staticmethod(_invalidate_role))


def stub_target(monkeypatch, target):
    async def _get(session, admin_id: int):
        return target

    monkeypatch.setattr(
        AdminAccountDAO, "get_by_id_with_relations", staticmethod(_get)
    )


async def seed_cached_identity(redis_client, admin_id: int = TARGET_ID) -> str:
    """Prime the cache so the test can assert the handler clears it."""
    key = CacheKeys.admin_identity(admin_id)
    await redis_client.setex(key, 60, '{"v": 0, "exists": true, "is_active": true, "role_name": "operator"}')
    return key


async def test_deactivation_invalidates_the_cached_identity(
    monkeypatch, redis_client, session
):
    stub_target(monkeypatch, make_target())
    key = await seed_cached_identity(redis_client)

    await admin_management.update_admin_status(
        admin_account_id=TARGET_ID,
        body=UpdateAdminStatusRequest(is_active=False),
        admin=ACTING_ADMIN,
        session=session,
        redis=redis_client,
    )

    assert await redis_client.get(key) is None
    assert await redis_client.get(CacheKeys.admin_identity_version(TARGET_ID)) == "1"


async def test_role_change_invalidates_the_cached_identity(
    monkeypatch, redis_client, session
):
    stub_target(monkeypatch, make_target(role_id=2))
    key = await seed_cached_identity(redis_client)

    async def _get_role(_session, role_id: int):
        return SimpleNamespace(id=role_id, name="finance", home_page=None)

    monkeypatch.setattr(RoleDAO, "get_by_id", staticmethod(_get_role))

    await admin_management.update_admin_account(
        admin_account_id=TARGET_ID,
        body=UpdateAdminAccountRequest(role_id=5),
        admin=ACTING_ADMIN,
        session=session,
        redis=redis_client,
    )

    assert await redis_client.get(key) is None
    assert await redis_client.get(CacheKeys.admin_identity_version(TARGET_ID)) == "1"


async def test_deletion_invalidates_the_cached_identity(
    monkeypatch, redis_client, session
):
    stub_target(monkeypatch, make_target())
    key = await seed_cached_identity(redis_client)

    await admin_management.delete_admin_account(
        admin_account_id=TARGET_ID,
        admin=ACTING_ADMIN,
        session=session,
        redis=redis_client,
    )

    assert await redis_client.get(key) is None
    assert await redis_client.get(CacheKeys.admin_identity_version(TARGET_ID)) == "1"


async def test_untouched_update_does_not_invalidate(monkeypatch, redis_client, session):
    """A no-op rename must not churn the cache of an unaffected admin."""
    target = make_target()
    stub_target(monkeypatch, target)
    key = await seed_cached_identity(redis_client)

    await admin_management.update_admin_account(
        admin_account_id=TARGET_ID,
        body=UpdateAdminAccountRequest(system_username=target.system_username),
        admin=ACTING_ADMIN,
        session=session,
        redis=redis_client,
    )

    assert await redis_client.get(key) is not None
