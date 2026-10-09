"""
Regression tests for admin JWT revocation.

A valid signature and an unexpired ``exp`` are not enough to authorise an admin:
the account may have been deactivated, demoted or deleted after the token was
issued.  With ``API_JWT_EXPIRE_MINUTES`` defaulting to 480, trusting the token
alone leaves a dismissed admin fully privileged for up to eight hours.

The tests drive a real FastAPI app through the real dependency chain
(``get_admin_from_jwt`` then ``require_permission``); only the database session,
the Redis connection and the two data-access calls are substituted.
"""
import fakeredis.aioredis
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.dependencies import get_db, get_redis, require_permission
from src.api.utils.admin_jwt import create_admin_token
from src.infrastructure.database.dao.admin_account import AdminAccountDAO
from src.infrastructure.services.admin_rbac_service import RBACService

ADMIN_ID = 42
JWT_SECRET = "t" * 64
JWT_ALGORITHM = "HS256"

# The permission guarding the money-moving endpoints.
RESOURCE, ACTION = "payments", "process"


class StubAdminAccount:
    """Minimal stand-in for the ``AdminAccount`` row the DAO returns."""

    def __init__(
        self,
        *,
        admin_id: int = ADMIN_ID,
        is_active: bool = True,
        role_name: str = "super-admin",
    ) -> None:
        self.id = admin_id
        self.is_active = is_active
        self.role_name = role_name


class DAOSpy:
    """Records how often the identity lookup actually reaches the database."""

    def __init__(self, account: StubAdminAccount | None) -> None:
        self.account = account
        self.calls = 0

    async def __call__(self, session, admin_id: int) -> StubAdminAccount | None:
        self.calls += 1
        return self.account


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def app(redis_client):
    """A single route protected exactly like the real payment endpoints."""
    application = FastAPI()

    @application.get("/protected")
    async def protected(admin=Depends(require_permission(RESOURCE, ACTION))):
        return {"admin_id": admin.admin_id, "role_name": admin.role_name}

    async def _override_db():
        yield object()  # never used: every DB call in these tests is stubbed

    application.dependency_overrides[get_db] = _override_db
    application.dependency_overrides[get_redis] = lambda: redis_client
    return application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def make_token(
    role_name: str = "super-admin",
    permissions: list[str] | None = None,
) -> tuple[str, str]:
    return create_admin_token(
        admin_id=ADMIN_ID,
        role_name=role_name,
        secret=JWT_SECRET,
        algorithm=JWT_ALGORITHM,
        expire_minutes=480,
        permissions=permissions or [],
    )


def auth(token: str) -> dict[str, str]:
    return {"X-Admin-Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def patch_config(monkeypatch):
    """Pin the signing secret so tokens minted here validate deterministically."""
    from pydantic import SecretStr

    from src.config import config

    monkeypatch.setattr(config.api, "JWT_SECRET", SecretStr(JWT_SECRET))
    monkeypatch.setattr(config.api, "JWT_ALGORITHM", JWT_ALGORITHM)


@pytest.fixture
def stub_rbac(monkeypatch):
    """Grant the payments permission to 'finance' only; deny it to 'operator'."""

    async def _get_permissions(redis, session, role_name: str) -> set[str]:
        if role_name == "finance":
            return {f"{RESOURCE}:{ACTION}"}
        return set()

    monkeypatch.setattr(RBACService, "get_permissions", staticmethod(_get_permissions))


def stub_dao(monkeypatch, account: StubAdminAccount | None) -> DAOSpy:
    spy = DAOSpy(account)
    monkeypatch.setattr(
        AdminAccountDAO, "get_by_id_with_relations", staticmethod(spy)
    )
    return spy


# ---------------------------------------------------------------------------
# Deactivation
# ---------------------------------------------------------------------------

async def test_deactivated_admin_is_rejected(client, monkeypatch, stub_rbac):
    """A dismissed admin's still-unexpired token must stop working."""
    stub_dao(monkeypatch, StubAdminAccount(is_active=False))
    token, _ = make_token()

    response = await client.get("/protected", headers=auth(token))

    assert response.status_code == 401, response.text


async def test_deleted_admin_is_rejected(client, monkeypatch, stub_rbac):
    """A token for an account row that no longer exists must be rejected."""
    stub_dao(monkeypatch, None)
    token, _ = make_token()

    response = await client.get("/protected", headers=auth(token))

    assert response.status_code == 401, response.text


# ---------------------------------------------------------------------------
# Role changes: authorisation must follow the database, not the token
# ---------------------------------------------------------------------------

async def test_demoted_super_admin_loses_super_admin_bypass(client, monkeypatch, stub_rbac):
    """
    The headline privilege-escalation case: the token still says
    ``role: super-admin`` (which bypasses every RBAC check) while the database
    says the admin is now a plain operator without ``payments:process``.
    """
    stub_dao(monkeypatch, StubAdminAccount(role_name="operator"))
    token, _ = make_token(role_name="super-admin")

    response = await client.get("/protected", headers=auth(token))

    assert response.status_code == 403, response.text


async def test_promoted_admin_gets_new_role_immediately(client, monkeypatch, stub_rbac):
    """The reverse direction: a token minted before the promotion still works."""
    stub_dao(monkeypatch, StubAdminAccount(role_name="finance"))
    token, _ = make_token(role_name="operator")

    response = await client.get("/protected", headers=auth(token))

    assert response.status_code == 200, response.text
    assert response.json()["role_name"] == "finance"


# ---------------------------------------------------------------------------
# Behaviour that must not regress
# ---------------------------------------------------------------------------

async def test_active_super_admin_still_passes(client, monkeypatch, stub_rbac):
    stub_dao(monkeypatch, StubAdminAccount(role_name="super-admin"))
    token, _ = make_token()

    response = await client.get("/protected", headers=auth(token))

    assert response.status_code == 200, response.text
    assert response.json()["admin_id"] == ADMIN_ID


async def test_blocklisted_token_still_rejected(client, monkeypatch, redis_client, stub_rbac):
    from src.infrastructure.cache.keys import CacheKeys

    stub_dao(monkeypatch, StubAdminAccount())
    token, jti = make_token()
    await redis_client.setex(CacheKeys.admin_jwt_blocklist(jti), 60, "revoked")

    response = await client.get("/protected", headers=auth(token))

    assert response.status_code == 401, response.text
    assert "revoked" in response.json()["detail"].lower()


async def test_missing_header_is_rejected(client, monkeypatch, stub_rbac):
    stub_dao(monkeypatch, StubAdminAccount())

    response = await client.get("/protected")

    assert response.status_code == 401, response.text


# ---------------------------------------------------------------------------
# Caching: correctness must not cost a database query per request
# ---------------------------------------------------------------------------

async def test_identity_is_cached_between_requests(client, monkeypatch, stub_rbac):
    spy = stub_dao(monkeypatch, StubAdminAccount())
    token, _ = make_token()

    for _ in range(3):
        assert (await client.get("/protected", headers=auth(token))).status_code == 200

    assert spy.calls == 1, "identity lookup should be served from Redis after the first hit"


async def test_invalidation_forces_a_fresh_lookup(client, monkeypatch, redis_client, stub_rbac):
    """Deactivation must take effect immediately, not after the cache TTL."""
    from src.infrastructure.services.admin_identity_service import AdminIdentityService

    account = StubAdminAccount()
    spy = stub_dao(monkeypatch, account)
    token, _ = make_token()

    assert (await client.get("/protected", headers=auth(token))).status_code == 200

    account.is_active = False
    await AdminIdentityService.invalidate(redis_client, ADMIN_ID)

    response = await client.get("/protected", headers=auth(token))

    assert response.status_code == 401, response.text
    assert spy.calls == 2
