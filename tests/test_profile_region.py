"""GET and PATCH /api/v1/profile/me for a client whose region is not set.

``clients.region`` is nullable, but the profile response translated it
unconditionally: the translator hands a ``None`` key back unchanged,
``ProfileResponse.region`` is a required string, and every such client got a
500 instead of a profile.

The app mounts the real profile router with the prefix used in
``src/bot/bot.py``; only ``get_db`` and ``get_redis`` are overridden, to the
test session and an in-memory Redis.
"""

import secrets
from collections.abc import AsyncIterator

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import SESSION_PREFIX, SESSION_TTL_SECONDS, get_db, get_redis
from src.api.routers.profile_router import router as profile_router
from src.bot.utils.i18n import i18n
from src.infrastructure.database.models.client import Client

PROFILE_URL = "/api/v1/profile/me"
NOT_PROVIDED = i18n.get("uz", "not-provided")


@pytest.fixture
def redis_client() -> Redis:
    """A private in-memory server, so no session key survives into another test."""
    return fakeredis.aioredis.FakeRedis(
        server=fakeredis.FakeServer(), decode_responses=True
    )


@pytest.fixture
def app(db_session: AsyncSession, redis_client: Redis) -> FastAPI:
    application = FastAPI()
    application.include_router(profile_router, prefix="/api/v1")

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    def _override_redis() -> Redis:
        return redis_client

    application.dependency_overrides[get_db] = _override_db
    application.dependency_overrides[get_redis] = _override_redis
    return application


@pytest.fixture
async def http_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def login(
    session: AsyncSession, redis_client: Redis, *, region: str | None
) -> dict[str, str]:
    """A client with ``region``, holding a session token issued like ``auth.py`` does."""
    client = Client(
        telegram_id=700_000_201,
        full_name="Profil Mijoz",
        client_code="A700",
        is_logged_in=True,
        region=region,
    )
    session.add(client)
    await session.commit()

    token = secrets.token_urlsafe(32)
    await redis_client.setex(
        f"{SESSION_PREFIX}{token}", SESSION_TTL_SECONDS, str(client.id)
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("region", "shown"),
    [
        pytest.param(None, NOT_PROVIDED, id="unset"),
        pytest.param("", NOT_PROVIDED, id="empty"),
        pytest.param(
            "toshkent_city", i18n.get("uz", "region-toshkent-city"), id="region-key"
        ),
        # PATCH /me stores the translated name rather than the key.
        pytest.param("Toshkent shahri", "Toshkent shahri", id="saved-display-name"),
    ],
)
async def test_profile_shows_the_region_or_not_provided(
    http_client: AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    region: str | None,
    shown: str,
) -> None:
    headers = await login(db_session, redis_client, region=region)

    response = await http_client.get(PROFILE_URL, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["region"] == shown


async def test_another_field_updates_for_a_client_without_a_region(
    http_client: AsyncClient, db_session: AsyncSession, redis_client: Redis
) -> None:
    headers = await login(db_session, redis_client, region=None)

    response = await http_client.patch(
        PROFILE_URL, json={"full_name": "Yangi Ism"}, headers=headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["full_name"], body["region"]) == ("Yangi Ism", NOT_PROVIDED)
