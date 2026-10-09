"""Staff-only APIs refuse callers that lack the matching admin permission.

The client admin API (``/api/v1/clients``), the Excel import API
(``/api/v1/import``) and the partner shipment list
(``/api/v1/shipment/temp-list``) had their auth dependencies commented out, so
anyone could read passports and PINFLs, credit a wallet, delete a client, write
cargo rows or list partner shipments with real flight names.

The app mounts the real routers with the prefixes ``src/bot/bot.py`` uses.
Staff authenticate with an admin JWT minted the way the admin login endpoint
mints it, and permissions come from database roles through the real RBAC path.
"""

import secrets
from collections.abc import AsyncIterator

import fakeredis
import fakeredis.aioredis
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.api.dependencies import SESSION_PREFIX, SESSION_TTL_SECONDS, get_db, get_redis
from src.api.routers.client_router import router as client_router
from src.api.routers.import_router import router as import_router
from src.api.routers.shipment_router import router as shipment_router
from src.api.utils.admin_jwt import create_admin_token
from src.config import config
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.models.admin_account import AdminAccount
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.role import Permission, Role

ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "no-access": (),
    "client-reader": ("clients:read",),
    "client-editor": ("clients:read", "clients:update"),
    "balance-editor": ("clients:read", "clients:update", "clients:finance_update"),
    "super-admin": (),
}
TARGET_CODE = "A07-15/1"
ORIGINAL_NAME = "Maqsad Mijoz"
RENAMED = "Qayta Nomlangan"
EXCEL_UPLOAD = {
    "excel_file": (
        "cargo.xlsx",
        b"not-a-spreadsheet",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
}


@pytest.fixture
def redis_client() -> Redis:
    """A private in-memory server, so no key survives into another test."""
    return fakeredis.aioredis.FakeRedis(
        server=fakeredis.FakeServer(), decode_responses=True
    )


@pytest_asyncio.fixture
async def http_client(
    db_engine: AsyncEngine, db_session: AsyncSession, redis_client: Redis
) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    # Same routers and prefixes as src/bot/bot.py.
    app.include_router(client_router, prefix="/api/v1")
    app.include_router(import_router, prefix="/api/v1")
    app.include_router(shipment_router, prefix="/api/v1")

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis] = lambda: redis_client
    # client_router opens its own sessions from app.state.db_client.
    db_client = DatabaseClient(db_engine.url.render_as_string(hide_password=False))
    app.state.db_client = db_client
    app.state.redis = redis_client
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        await db_client.shutdown()


@pytest_asyncio.fixture
async def accounts(db_session: AsyncSession) -> dict[str, AdminAccount]:
    """One staff account per role in ROLE_PERMISSIONS."""
    permissions = {
        slug: Permission(resource=slug.split(":")[0], action=slug.split(":")[1])
        for slugs in ROLE_PERMISSIONS.values()
        for slug in slugs
    }
    staff = {
        role_name: AdminAccount(
            client=Client(full_name=f"{role_name} xodim", telegram_id=6400 + number),
            role=Role(name=role_name, permissions=[permissions[s] for s in slugs]),
            system_username=role_name,
            pin_hash="unused-by-jwt-auth",
        )
        for number, (role_name, slugs) in enumerate(ROLE_PERMISSIONS.items(), start=1)
    }
    db_session.add_all(staff.values())
    await db_session.commit()
    return staff


@pytest_asyncio.fixture
async def target(db_session: AsyncSession) -> Client:
    client = Client(full_name=ORIGINAL_NAME, telegram_id=6500, client_code=TARGET_CODE)
    db_session.add(client)
    await db_session.commit()
    return client


def staff(account: AdminAccount) -> dict[str, str]:
    token, _ = create_admin_token(
        admin_id=account.id,
        role_name=account.role.name,
        secret=config.api.JWT_SECRET.get_secret_value(),
        algorithm=config.api.JWT_ALGORITHM,
        expire_minutes=5,
    )
    return {"X-Admin-Authorization": f"Bearer {token}"}


async def end_user(session: AsyncSession, redis_client: Redis) -> dict[str, str]:
    client = Client(full_name="Oddiy mijoz", telegram_id=6501, is_logged_in=True)
    session.add(client)
    await session.commit()
    token = secrets.token_urlsafe(32)
    await redis_client.setex(
        f"{SESSION_PREFIX}{token}", SESSION_TTL_SECONDS, str(client.id)
    )
    return {"Authorization": f"Bearer {token}"}


async def target_state(engine: AsyncEngine, client_id: int) -> tuple[str | None, int]:
    """The client's name (None once deleted) and its BONUS balance rows."""
    async with engine.connect() as conn:
        name = await conn.scalar(select(Client.full_name).where(Client.id == client_id))
        bonuses = await conn.scalar(
            select(func.count())
            .select_from(ClientTransaction)
            .where(
                ClientTransaction.client_code == TARGET_CODE,
                ClientTransaction.reys.like("BONUS:%"),
            )
        )
    return name, bonuses


async def test_staff_apis_refuse_callers_without_an_admin_jwt(
    http_client: AsyncClient,
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    target: Client,
) -> None:
    client_url = f"/api/v1/clients/{target.id}"
    requests = [
        ("GET", "/api/v1/clients/preview-code", {}),
        ("GET", client_url, {}),
        ("GET", f"{client_url}/passport-images/metadata", {}),
        ("GET", f"{client_url}/passport-images/resolve/0", {}),
        ("POST", "/api/v1/clients", {"data": {"full_name": "Yangi Mijoz"}}),
        (
            "PUT",
            client_url,
            {"data": {"adjustment_type": "bonus", "adjustment_amount": "100000000"}},
        ),
        ("DELETE", client_url, {}),
        ("POST", "/api/v1/import/uz", {"files": EXCEL_UPLOAD}),
        ("POST", "/api/v1/import/china", {"files": EXCEL_UPLOAD}),
        ("GET", "/api/v1/shipment/temp-list", {}),
    ]
    callers = {"anonymous": {}, "end-user": await end_user(db_session, redis_client)}

    answered = {
        (caller, method, url): (
            await http_client.request(method, url, headers=headers, **options)
        ).status_code
        for caller, headers in callers.items()
        for method, url, options in requests
    }

    assert answered == dict.fromkeys(answered, 401)
    assert await target_state(db_engine, target.id) == (ORIGINAL_NAME, 0)


async def test_client_admin_api_enforces_each_permission(
    http_client: AsyncClient,
    db_engine: AsyncEngine,
    accounts: dict[str, AdminAccount],
    target: Client,
) -> None:
    url = f"/api/v1/clients/{target.id}"
    bonus = {
        "adjustment_type": "bonus",
        "adjustment_amount": "5000",
        "adjustment_reason": "referral",
    }

    assert (
        await http_client.get(url, headers=staff(accounts["no-access"]))
    ).status_code == 403
    assert (
        await http_client.get(url, headers=staff(accounts["client-reader"]))
    ).status_code == 200
    reader_edit = await http_client.put(
        url, data={"full_name": RENAMED}, headers=staff(accounts["client-reader"])
    )
    assert reader_edit.status_code == 403

    renamed = await http_client.put(
        url, data={"full_name": RENAMED}, headers=staff(accounts["client-editor"])
    )
    assert renamed.status_code == 200, renamed.text

    # A balance adjustment needs clients:finance_update, and a refused request
    # changes nothing, not even the fields sent with it.
    refused = await http_client.put(
        url,
        data={"full_name": "Boshqa Nom", **bonus},
        headers=staff(accounts["client-editor"]),
    )
    assert refused.status_code == 403
    assert await target_state(db_engine, target.id) == (RENAMED, 0)

    credited = await http_client.put(
        url, data=bonus, headers=staff(accounts["balance-editor"])
    )
    assert credited.status_code == 200, credited.text
    assert await target_state(db_engine, target.id) == (RENAMED, 1)

    # Hard delete needs clients:delete, which no role holds until it is granted.
    refused_delete = await http_client.delete(
        url, headers=staff(accounts["balance-editor"])
    )
    assert refused_delete.status_code == 403
    deleted = await http_client.delete(url, headers=staff(accounts["super-admin"]))
    assert deleted.status_code == 200, deleted.text
    assert (await target_state(db_engine, target.id))[0] is None


async def test_import_and_partner_shipment_list_need_their_permissions(
    http_client: AsyncClient, accounts: dict[str, AdminAccount]
) -> None:
    editor = staff(accounts["client-editor"])
    super_admin = staff(accounts["super-admin"])

    imported = await http_client.post(
        "/api/v1/import/china", files=EXCEL_UPLOAD, headers=editor
    )
    assert imported.status_code == 403
    assert (
        await http_client.get("/api/v1/shipment/temp-list", headers=editor)
    ).status_code == 403

    listed = await http_client.get("/api/v1/shipment/temp-list", headers=super_admin)
    assert (listed.status_code, listed.json()) == (200, [])
    capped = await http_client.get(
        "/api/v1/shipment/temp-list", params={"limit": 501}, headers=super_admin
    )
    assert capped.status_code == 422
