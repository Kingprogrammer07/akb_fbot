"""
Regression tests for the Mini App wallet's company-card lookup.

The wallet modal used to fetch the card to pay into from
``GET /api/v1/payments/active-cards/random`` with an end-user session token.
That endpoint now requires an admin JWT with ``pos:read``, so end users got 401
and the frontend logged them out.  ``GET /api/v1/wallet/company-card`` is the
user-facing replacement.

The app mounts the real wallet and payments routers with the prefixes used in
``src/bot/bot.py`` and keeps their real dependency chains; only ``get_db`` and
``get_redis`` are overridden, to the test session and an in-memory Redis.
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
from src.api.routers.verification import payments_router
from src.api.routers.wallet import router as wallet_router
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.payment_card import PaymentCard

COMPANY_CARD_URL = "/api/v1/wallet/company-card"
ADMIN_RANDOM_CARD_URL = "/api/v1/payments/active-cards/random"

ACTIVE_CARD_NUMBER = "8600123456781234"
INACTIVE_CARD_NUMBER = "8600987654324321"
HOLDER_NAME = "AKB Cargo Kassa"

NO_ACTIVE_CARDS_DETAIL = {
    "error": "No active payment cards found",
    "error_code": "NO_ACTIVE_CARDS",
    "details": None,
}


@pytest.fixture
def redis_client() -> Redis:
    """A private in-memory server, so no session key survives into another test."""
    return fakeredis.aioredis.FakeRedis(
        server=fakeredis.FakeServer(), decode_responses=True
    )


@pytest.fixture
def app(db_session: AsyncSession, redis_client: Redis) -> FastAPI:
    application = FastAPI()
    application.include_router(wallet_router, prefix="/api/v1")
    application.include_router(payments_router, prefix="/api/v1")

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


@pytest.fixture
async def user_token(db_session: AsyncSession, redis_client: Redis) -> str:
    """A logged-in end user holding a session token issued the way ``auth.py`` does."""
    # Not in BOT_ADMIN_ACCESS_IDs, so get_current_user keeps the plain user role.
    client = Client(telegram_id=700_000_001, full_name="Test Mijoz", is_logged_in=True)
    db_session.add(client)
    await db_session.commit()

    token = secrets.token_urlsafe(32)
    await redis_client.setex(
        f"{SESSION_PREFIX}{token}", SESSION_TTL_SECONDS, str(client.id)
    )
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def add_card(
    session: AsyncSession, *, card_number: str, is_active: bool
) -> PaymentCard:
    card = PaymentCard(
        card_number=card_number, full_name=HOLDER_NAME, is_active=is_active
    )
    session.add(card)
    await session.commit()
    return card


# ---------------------------------------------------------------------------
# GET /api/v1/wallet/company-card
# ---------------------------------------------------------------------------


async def test_company_card_returns_the_active_card(
    http_client: AsyncClient, db_session: AsyncSession, user_token: str
) -> None:
    """Only an active card may be offered; the inactive one is never eligible."""
    await add_card(db_session, card_number=INACTIVE_CARD_NUMBER, is_active=False)
    await add_card(db_session, card_number=ACTIVE_CARD_NUMBER, is_active=True)

    response = await http_client.get(COMPANY_CARD_URL, headers=bearer(user_token))

    assert response.status_code == 200, response.text
    assert response.json() == {
        "card_number": ACTIVE_CARD_NUMBER,
        "holder_name": HOLDER_NAME,
        "bank_name": None,
    }


async def test_company_card_404_when_no_card_is_active(
    http_client: AsyncClient, db_session: AsyncSession, user_token: str
) -> None:
    """The error body matches the admin endpoint the frontend used to call."""
    await add_card(db_session, card_number=INACTIVE_CARD_NUMBER, is_active=False)

    response = await http_client.get(COMPANY_CARD_URL, headers=bearer(user_token))

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": NO_ACTIVE_CARDS_DETAIL}


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-credentials"),
        pytest.param(bearer("not-an-issued-session"), id="unknown-session"),
    ],
)
async def test_company_card_requires_authentication(
    http_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await add_card(db_session, card_number=ACTIVE_CARD_NUMBER, is_active=True)

    response = await http_client.get(COMPANY_CARD_URL, headers=headers)

    assert response.status_code == 401, response.text
    assert ACTIVE_CARD_NUMBER not in response.text


# ---------------------------------------------------------------------------
# The admin endpoint is not the user path
# ---------------------------------------------------------------------------


async def test_end_user_token_is_refused_by_admin_endpoint_but_not_wallet(
    http_client: AsyncClient, db_session: AsyncSession, user_token: str
) -> None:
    """The Mini App's token must use the wallet endpoint, not the pos:read one."""
    await add_card(db_session, card_number=ACTIVE_CARD_NUMBER, is_active=True)

    admin_response = await http_client.get(
        ADMIN_RANDOM_CARD_URL, headers=bearer(user_token)
    )
    user_response = await http_client.get(COMPANY_CARD_URL, headers=bearer(user_token))

    assert admin_response.status_code == 401, admin_response.text
    assert ACTIVE_CARD_NUMBER not in admin_response.text
    assert user_response.status_code == 200, user_response.text
    assert user_response.json()["card_number"] == ACTIVE_CARD_NUMBER
