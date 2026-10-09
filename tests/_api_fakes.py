"""Shared HTTP fixtures for the API route tests.

Not collected by pytest: the module name does not start with ``test_``.  A test
module re-exports the fixtures it needs (``from tests._api_fakes import api as
api``) so pytest registers them for that module.

The app mounts the real routers under the prefixes ``src/bot/bot.py`` uses, in
the same order, and reaches the test database through a production
``DatabaseClient``.
"""

import secrets
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from src.api.dependencies import SESSION_PREFIX, SESSION_TTL_SECONDS
from src.api.routers.cargo import router as cargo_router
from src.api.routers.reports import router as reports_router
from src.api.routers.verification.verification_router import (
    router as verification_router,
)
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.models.client import Client


@pytest.fixture
def redis_client() -> FakeRedis:
    return FakeRedis(decode_responses=True)


@pytest_asyncio.fixture
async def api(
    db_engine: AsyncEngine, redis_client: FakeRedis
) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    # Same prefixes and order as src/bot/bot.py.
    app.include_router(cargo_router, prefix="/api/v1")
    app.include_router(reports_router, prefix="/api/v1")
    app.include_router(verification_router, prefix="/api/v1")

    db_client = DatabaseClient(db_engine.url.render_as_string(hide_password=False))
    app.state.db_client = db_client
    app.state.redis = redis_client

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        await db_client.shutdown()


async def bearer(redis_client: FakeRedis, client: Client) -> dict[str, str]:
    """Issue a session token stored the way the login endpoint stores it."""
    token = secrets.token_urlsafe(32)
    await redis_client.setex(
        f"{SESSION_PREFIX}{token}", SESSION_TTL_SECONDS, str(client.id)
    )
    return {"Authorization": f"Bearer {token}"}
