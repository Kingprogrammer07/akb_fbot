"""Statistics routes answer only staff, and every one of them runs for staff.

Every statistics router had its admin JWT dependency commented out, so client,
financial, cargo, operational and analytics statistics - Excel exports of
client lists included - answered any caller.  The region breakdowns behind
/statistics/clients and /statistics/financial also always failed with a 500:
``HAVING region_code IS NOT NULL`` names a SELECT alias, which PostgreSQL
rejects.

The app mounts the real statistics routers with the prefix ``src/bot/bot.py``
uses; only ``get_db`` and ``get_redis`` are overridden, to the test session and
an in-memory Redis.  Staff authenticate with an admin JWT minted the way the
admin login endpoint mints it.
"""

import secrets
from collections.abc import AsyncIterator
from decimal import Decimal

import fakeredis
import fakeredis.aioredis
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import SESSION_PREFIX, SESSION_TTL_SECONDS, get_db, get_redis
from src.api.routers.statistics.analytics_stats_router import router as analytics_router
from src.api.routers.statistics.cargo_stats_router import router as cargo_router
from src.api.routers.statistics.client_stats_router import router as clients_router
from src.api.routers.statistics.financial_stats_router import router as financial_router
from src.api.routers.statistics.operational_stats_router import (
    router as operational_router,
)
from src.api.utils.admin_jwt import create_admin_token
from src.config import config
from src.infrastructure.database.models.admin_account import AdminAccount
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.role import Role
from src.infrastructure.database.models.static_data import StaticData

STATISTICS_ROUTERS = (
    clients_router,
    cargo_router,
    financial_router,
    operational_router,
    analytics_router,
)
STATISTICS_PATHS = [
    "/api/v1/statistics/clients",
    "/api/v1/statistics/clients/export",
    "/api/v1/statistics/clients/export/zombie",
    "/api/v1/statistics/clients/export/passive",
    "/api/v1/statistics/clients/export/frequent",
    "/api/v1/statistics/financial",
    "/api/v1/statistics/financial/export",
    "/api/v1/statistics/cargo",
    "/api/v1/statistics/cargo/export",
    "/api/v1/operational/summary",
    "/api/v1/operational/export",
    "/api/v1/statistics/analytics",
    "/api/v1/statistics/analytics/events",
]
REGION_CODES = ("A07-15/1", "ABG12")
"""One Toshkent shahar code and one code of another region."""


@pytest.fixture
def redis_client() -> Redis:
    """A private in-memory server, so no key survives into another test."""
    return fakeredis.aioredis.FakeRedis(
        server=fakeredis.FakeServer(), decode_responses=True
    )


@pytest.fixture
def app(db_session: AsyncSession, redis_client: Redis) -> FastAPI:
    application = FastAPI()
    for router in STATISTICS_ROUTERS:
        application.include_router(router, prefix="/api/v1")

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    def _override_redis() -> Redis:
        return redis_client

    application.dependency_overrides[get_db] = _override_db
    application.dependency_overrides[get_redis] = _override_redis
    return application


@pytest_asyncio.fixture
async def http_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    # A server error comes back as a response, so every route gets checked.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def staff_headers(db_session: AsyncSession) -> dict[str, str]:
    """An admin JWT for a staff account whose role holds no special permission."""
    account = AdminAccount(
        client=Client(full_name="Statistika xodimi", telegram_id=6201),
        role=Role(name="analyst"),
        system_username="analyst",
        pin_hash="unused-by-jwt-auth",
    )
    db_session.add(account)
    await db_session.commit()
    token, _ = create_admin_token(
        admin_id=account.id,
        role_name="analyst",
        secret=config.api.JWT_SECRET.get_secret_value(),
        algorithm=config.api.JWT_ALGORITHM,
        expire_minutes=5,
    )
    return {"X-Admin-Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def client_headers(
    db_session: AsyncSession, redis_client: Redis
) -> dict[str, str]:
    """A logged-in end user's session token, issued the way ``auth.py`` does."""
    client = Client(
        full_name="Oddiy mijoz",
        telegram_id=6202,
        client_code="A07-99/1",
        is_logged_in=True,
    )
    db_session.add(client)
    await db_session.commit()
    token = secrets.token_urlsafe(32)
    await redis_client.setex(
        f"{SESSION_PREFIX}{token}", SESSION_TTL_SECONDS, str(client.id)
    )
    return {"Authorization": f"Bearer {token}"}


async def seed_region_rows(session: AsyncSession) -> None:
    """Clients and transactions under both code formats the breakdowns parse."""
    # A fixed rate keeps any USD lookup away from the currency API.
    session.add(StaticData(id=1, use_custom_rate=True, custom_usd_rate=12650.0))
    for offset, code in enumerate(REGION_CODES):
        telegram_id = 6300 + offset
        session.add(
            Client(full_name=f"Mijoz {code}", telegram_id=telegram_id, client_code=code)
        )
        session.add(
            ClientTransaction(
                telegram_id=telegram_id,
                client_code=code,
                qator_raqami=0,
                reys="M100",
                summa=Decimal("50000"),
                vazn="1",
                payment_type="online",
                payment_status="partial",
                total_amount=Decimal("50000"),
                paid_amount=Decimal("20000"),
                remaining_amount=Decimal("30000"),
                payment_balance_difference=Decimal("0"),
                is_taken_away=False,
            )
        )
    await session.commit()


def test_every_statistics_route_is_listed() -> None:
    """A new statistics route must be added here, so its access is checked too."""
    routes = [
        "/api/v1" + route.path
        for router in STATISTICS_ROUTERS
        for route in router.routes
    ]

    assert sorted(routes) == sorted(STATISTICS_PATHS)


async def test_statistics_refuse_callers_without_an_admin_jwt(
    http_client: AsyncClient, client_headers: dict[str, str]
) -> None:
    answered = {
        (caller, path): (await http_client.get(path, headers=headers)).status_code
        for path in STATISTICS_PATHS
        for caller, headers in (("anonymous", {}), ("end-user", client_headers))
    }

    assert answered == dict.fromkeys(answered, 401)


async def test_staff_get_every_statistics_route_without_an_error(
    http_client: AsyncClient,
    db_session: AsyncSession,
    staff_headers: dict[str, str],
) -> None:
    await seed_region_rows(db_session)

    answered = {
        path: (await http_client.get(path, headers=staff_headers)).status_code
        for path in STATISTICS_PATHS
    }

    assert {path: code for path, code in answered.items() if code >= 400} == {}
