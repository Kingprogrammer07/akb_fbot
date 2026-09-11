"""
A Redis outage must not turn a committed admin-management change into an error.

The admin-management endpoints drop the RBAC permission cache only after the
database commit.  ``RBACService.invalidate_role`` used to let the Redis error
escape, so a role change, admin deletion or role rename that had already been
saved was answered with HTTP 500, inviting a retry of something that had in
fact happened.  The stale cache entry expires within ``PERMISSIONS_TTL``
anyway, so the failure is logged rather than raised.
"""

import logging
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
    UpdateRoleRequest,
)
from src.infrastructure.services.admin_rbac_service import RBACService

SERVICE_LOGGER = "src.infrastructure.services.admin_rbac_service"

TARGET_ID = 11
OLD_ROLE_ID = 2
NEW_ROLE_ID = 5
ACTING_ADMIN = AdminJWTPayload(admin_id=1, role_name="super-admin", jti="jti-1")


class FakeSession:
    """Just enough AsyncSession surface for these handlers, recording writes."""

    def __init__(self) -> None:
        self.committed = False
        self.deleted: list[object] = []

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _obj: object) -> None:
        return None

    async def delete(self, obj: object) -> None:
        self.deleted.append(obj)


def make_target(role_name: str) -> SimpleNamespace:
    """An object shaped like the AdminAccount row the handlers work with."""
    return SimpleNamespace(
        id=TARGET_ID,
        system_username="target_admin",
        is_active=True,
        failed_login_attempts=0,
        role_id=OLD_ROLE_ID,
        role_name=role_name,
        role=SimpleNamespace(id=OLD_ROLE_ID, name=role_name, home_page=None),
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


def stub_target(monkeypatch: pytest.MonkeyPatch, target: SimpleNamespace) -> None:
    async def _get(_session: object, _admin_id: int) -> SimpleNamespace:
        return target

    monkeypatch.setattr(AdminAccountDAO, "get_by_id_with_relations", staticmethod(_get))


def rbac_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == SERVICE_LOGGER and record.levelno == logging.WARNING
    ]


@pytest.fixture
def unreachable_redis() -> fakeredis.aioredis.FakeRedis:
    """A client whose every command fails as if the Redis server were down."""
    server = fakeredis.FakeServer()
    server.connected = False
    return fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture(autouse=True)
def silence_audit_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """The audit log is written through the session and is not under test here."""

    async def _log(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(AdminAuditLogDAO, "log", staticmethod(_log))


async def test_invalidate_role_drops_the_cached_permissions() -> None:
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cache_key = CacheKeys.role_permissions("operator")
    await redis_client.sadd(cache_key, "finance:read")

    await RBACService.invalidate_role(redis_client, "operator")

    assert await redis_client.exists(cache_key) == 0


async def test_invalidate_role_logs_and_returns_when_redis_is_unavailable(
    unreachable_redis: fakeredis.aioredis.FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=SERVICE_LOGGER):
        await RBACService.invalidate_role(unreachable_redis, "operator")

    messages = rbac_warnings(caplog)
    assert len(messages) == 1
    assert "operator" in messages[0]


async def test_role_change_is_reported_as_saved_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    session: FakeSession,
    unreachable_redis: fakeredis.aioredis.FakeRedis,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub_target(monkeypatch, make_target(role_name="operator"))

    async def _get_role(_session: object, role_id: int) -> SimpleNamespace:
        return SimpleNamespace(id=role_id, name="finance", home_page=None)

    monkeypatch.setattr(RoleDAO, "get_by_id", staticmethod(_get_role))

    with caplog.at_level(logging.WARNING, logger=SERVICE_LOGGER):
        response = await admin_management.update_admin_account(
            admin_account_id=TARGET_ID,
            body=UpdateAdminAccountRequest(role_id=NEW_ROLE_ID),
            admin=ACTING_ADMIN,
            session=session,
            redis=unreachable_redis,
        )

    assert session.committed
    assert response.id == TARGET_ID
    assert response.role_id == NEW_ROLE_ID
    assert any("operator" in message for message in rbac_warnings(caplog))


async def test_admin_deletion_is_reported_as_saved_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    session: FakeSession,
    unreachable_redis: fakeredis.aioredis.FakeRedis,
    caplog: pytest.LogCaptureFixture,
) -> None:
    target = make_target(role_name="operator")
    stub_target(monkeypatch, target)

    with caplog.at_level(logging.WARNING, logger=SERVICE_LOGGER):
        await admin_management.delete_admin_account(
            admin_account_id=TARGET_ID,
            admin=ACTING_ADMIN,
            session=session,
            redis=unreachable_redis,
        )

    assert session.committed
    assert session.deleted == [target]
    assert any("operator" in message for message in rbac_warnings(caplog))


async def test_role_rename_is_reported_as_saved_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    session: FakeSession,
    unreachable_redis: fakeredis.aioredis.FakeRedis,
    caplog: pytest.LogCaptureFixture,
) -> None:
    role = SimpleNamespace(
        id=OLD_ROLE_ID,
        name="operator",
        description=None,
        is_custom=True,
        home_page=None,
        permissions=[],
    )

    async def _get_role(_session: object, _role_id: int) -> SimpleNamespace:
        return role

    async def _no_conflicting_role(_session: object, _name: str) -> None:
        return None

    async def _admins_with_role(_session: object, _role_id: int) -> list[int]:
        return [TARGET_ID]

    monkeypatch.setattr(RoleDAO, "get_by_id", staticmethod(_get_role))
    monkeypatch.setattr(RoleDAO, "get_by_name", staticmethod(_no_conflicting_role))
    monkeypatch.setattr(
        AdminAccountDAO, "get_ids_by_role", staticmethod(_admins_with_role)
    )

    with caplog.at_level(logging.WARNING, logger=SERVICE_LOGGER):
        response = await admin_management.update_role(
            role_id=OLD_ROLE_ID,
            body=UpdateRoleRequest(name="dispatcher"),
            admin=ACTING_ADMIN,
            session=session,
            redis=unreachable_redis,
        )

    assert session.committed
    assert response.name == "dispatcher"
    messages = rbac_warnings(caplog)
    assert any("operator" in message for message in messages)
    assert any("dispatcher" in message for message in messages)
