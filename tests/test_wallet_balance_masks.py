"""GET /api/v1/wallet/balance shows partner masks in the payment reminders.

A reminder names a flight from the client's own partially paid transaction, and
the web wallet sends ``reminders[].flight`` back to ``/payments/flight-details``.
It must therefore be the partner's mask - minted when the flight has no alias
yet - and never the real flight name.

The app mounts the real wallet router with the prefix used in ``src/bot/bot.py``;
only ``get_db`` and ``get_redis`` are overridden, to the test session and an
in-memory Redis.
"""

import secrets
from collections.abc import AsyncIterator
from decimal import Decimal

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.api.dependencies import SESSION_PREFIX, SESSION_TTL_SECONDS, get_db, get_redis
from src.api.routers.wallet import router as wallet_router
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_flight_alias import PartnerFlightAlias
from src.infrastructure.services.flight_display import FLIGHT_PLACEHOLDER
from src.infrastructure.services.flight_mask import FlightMaskService

BALANCE_URL = "/api/v1/wallet/balance"

PARTNER_CLIENT_TG = 700_000_101
PARTNER_CLIENT_CODE = "SYT700"
NO_PARTNER_CLIENT_TG = 700_000_102
NO_PARTNER_CLIENT_CODE = "ZZ700"

ALIASED_FLIGHT = "M100-REAL"
ALIASED_MASK = "SYT7"
UNALIASED_FLIGHT = "M200-REAL"
# Minting continues the partner's counter after ALIASED_MASK.
MINTED_MASK = "SYT8"
PAID_FLIGHT = "M300-REAL"
REAL_FLIGHTS = (ALIASED_FLIGHT, UNALIASED_FLIGHT, PAID_FLIGHT)

TOTAL = Decimal("100000")


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


async def add_client(session: AsyncSession, telegram_id: int, code: str) -> Client:
    client = Client(
        telegram_id=telegram_id,
        full_name=f"Client {code}",
        client_code=code,
        is_logged_in=True,
    )
    session.add(client)
    await session.commit()
    return client


async def login(redis_client: Redis, client: Client) -> dict[str, str]:
    """A session token issued the way ``auth.py`` issues it."""
    token = secrets.token_urlsafe(32)
    await redis_client.setex(
        f"{SESSION_PREFIX}{token}", SESSION_TTL_SECONDS, str(client.id)
    )
    return {"Authorization": f"Bearer {token}"}


def transaction(client: Client, reys: str, *, remaining: Decimal) -> ClientTransaction:
    return ClientTransaction(
        telegram_id=client.telegram_id,
        client_code=client.client_code,
        qator_raqami=0,
        reys=reys,
        summa=TOTAL,
        vazn="2",
        payment_type="online",
        payment_status="partial" if remaining else "paid",
        total_amount=TOTAL,
        paid_amount=TOTAL - remaining,
        remaining_amount=remaining,
        payment_balance_difference=Decimal("0"),
        is_taken_away=False,
    )


async def committed_aliases(engine: AsyncEngine) -> dict[str, str]:
    """Committed ``real -> mask`` pairs, read outside the request's session."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(
                PartnerFlightAlias.real_flight_name, PartnerFlightAlias.mask_flight_name
            )
        )
        return {real: mask for real, mask in rows}


def assert_no_real_flight_names(body: str) -> None:
    leaked = sorted(name for name in REAL_FLIGHTS if name in body)
    assert not leaked, f"real flight names reached the client: {leaked}"


async def test_reminders_show_partner_masks_and_mint_a_missing_alias(
    http_client: AsyncClient,
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    partner = Partner(code="SYT", display_name="Triton", prefix="SYT", group_chat_id=-1)
    db_session.add(partner)
    await db_session.flush()
    db_session.add(
        PartnerFlightAlias(
            partner_id=partner.id,
            real_flight_name=ALIASED_FLIGHT,
            mask_flight_name=ALIASED_MASK,
        )
    )
    client = await add_client(db_session, PARTNER_CLIENT_TG, PARTNER_CLIENT_CODE)
    db_session.add_all(
        [
            transaction(client, ALIASED_FLIGHT, remaining=Decimal("40000")),
            transaction(client, UNALIASED_FLIGHT, remaining=Decimal("25000")),
            transaction(client, PAID_FLIGHT, remaining=Decimal("0")),
        ]
    )
    await db_session.commit()

    response = await http_client.get(
        BALANCE_URL, headers=await login(redis_client, client)
    )

    assert response.status_code == 200, response.text
    assert_no_real_flight_names(response.text)
    remaining_by_flight = {
        reminder["flight"]: reminder["remaining"]
        for reminder in response.json()["reminders"]
    }
    assert remaining_by_flight == {ALIASED_MASK: 40000.0, MINTED_MASK: 25000.0}
    assert await committed_aliases(db_engine) == {
        ALIASED_FLIGHT: ALIASED_MASK,
        UNALIASED_FLIGHT: MINTED_MASK,
    }
    # The web wallet sends the shown mask back; it must translate to the flight.
    assert (
        await FlightMaskService.normalize_flight_input(
            db_session, partner.id, MINTED_MASK
        )
        == UNALIASED_FLIGHT
    )


async def test_reminders_of_a_client_without_a_partner_show_the_placeholder(
    http_client: AsyncClient,
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    client = await add_client(db_session, NO_PARTNER_CLIENT_TG, NO_PARTNER_CLIENT_CODE)
    db_session.add(transaction(client, UNALIASED_FLIGHT, remaining=Decimal("25000")))
    await db_session.commit()

    response = await http_client.get(
        BALANCE_URL, headers=await login(redis_client, client)
    )

    assert response.status_code == 200, response.text
    assert_no_real_flight_names(response.text)
    assert [reminder["flight"] for reminder in response.json()["reminders"]] == [
        FLIGHT_PLACEHOLDER
    ]
    assert await committed_aliases(db_engine) == {}
