"""
Web API flight masks are minted from a client's own records, never from input.

Every flight a client sees has to render as its partner's mask, and the web app
sends a listed value straight back: ``UserReportsPage`` passes a reports flight
to the history filter and to the payment modal, and the delivery form posts the
paid flights it was offered.  A listed name therefore has to be a real mask that
``FlightMaskService.normalize_flight_input`` translates back, so the lists mint
a missing alias.  They are read from the client's own ``flight_cargos``,
``expected_flight_cargos`` and ``client_transaction_data`` rows and from the
Google Sheets rows fetched for its codes.  A flight name taken from a request
(a query filter, a path segment, a body) is only translated and never mints.

The app mounts the real routers under the prefixes ``src/bot/bot.py`` uses and
authenticates with a Redis session token, the Mini App's path.  Google Sheets
and Telegram are replaced at their client classes, so nothing leaves the
process.
"""

import json
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.api.dependencies import SESSION_PREFIX, SESSION_TTL_SECONDS, get_db
from src.api.routers.make_payment import router as make_payment_router
from src.api.routers.payment_history import router as payment_history_router
from src.api.routers.reports import router as reports_router
from src.api.routers.user_delivery import router as user_delivery_router
from src.bot.bot_instance import bot
from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.delivery_request import DeliveryRequest
from src.infrastructure.database.models.expected_cargo import ExpectedFlightCargo
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_flight_alias import PartnerFlightAlias
from src.infrastructure.database.models.static_data import StaticData
from src.infrastructure.services.flight_display import (
    FLIGHT_ORDINAL_PREFIX,
    FLIGHT_PLACEHOLDER,
)

OWNER_CODE = "SYT700"
OWNER_TELEGRAM_ID = 7001
NEIGHBOUR_CODE = "SYT800"

SYT_ALIASED_FLIGHT = "M100"
SYT_ALIASED_MASK = "SYT7"
AKB_ALIASES: dict[str, str] = {"M200": "AKB5"}
"""Another partner's alias for a flight the SYT client also has."""

WEB_REPORT_WEIGHTS: dict[str, float] = {"M100": 2.0, "M200": 1.5, "M300": 3.0}
"""The owner's web-sent reports: real flight name -> weight in kg."""

UNALIASED_REPORT = "M200"
UNSENT_FLIGHT = "M400"
NEIGHBOURS_FLIGHT = "M900"
SHEETS_FLIGHT = "M300"
EXPECTED_FLIGHTS = ("M200", "M500")
"""The owner's expected cargo, in name order."""

PAID_FLIGHTS: dict[str, str] = {"M100": "2", "M600": "1.25"}
"""Fully paid, not yet collected flights: real flight name -> ``vazn``."""

UNALIASED_PAID_FLIGHT = "M600"
BONUS_REYS = "BONUS:referral"
WALLET_ADJ_REYS = "WALLET_ADJ:refund"

REAL_FLIGHTS = frozenset(
    {
        *WEB_REPORT_WEIGHTS,
        UNSENT_FLIGHT,
        NEIGHBOURS_FLIGHT,
        SHEETS_FLIGHT,
        *EXPECTED_FLIGHTS,
        *PAID_FLIGHTS,
    }
)
UNKNOWN_FLIGHT = "M999"
TRACK_CODE = "YT0000000001"
MARKER_FLIGHT = "PENDING-MARKER"


@dataclass(frozen=True)
class Seed:
    owner: Client
    transactions: dict[str, ClientTransaction]
    """The owner's transactions by ``reys``."""


def _web_report(
    client_code: str, flight_name: str, weight_kg: float, *, sent_web: bool = True
) -> FlightCargo:
    return FlightCargo(
        flight_name=flight_name,
        client_id=client_code,
        photo_file_ids="[]",
        weight_kg=Decimal(str(weight_kg)),
        price_per_kg=Decimal("10"),
        is_sent=sent_web,
        is_sent_web=sent_web,
    )


def _owner_transaction(
    reys: str,
    *,
    vazn: str = "0",
    balance_difference: str = "0",
    taken_away: bool = False,
) -> ClientTransaction:
    return ClientTransaction(
        telegram_id=OWNER_TELEGRAM_ID,
        client_code=OWNER_CODE,
        qator_raqami=0,
        reys=reys,
        summa=Decimal("50000"),
        vazn=vazn,
        payment_type="online",
        payment_status="paid",
        paid_amount=Decimal("50000"),
        total_amount=Decimal("50000"),
        remaining_amount=Decimal("0"),
        payment_balance_difference=Decimal(balance_difference),
        is_taken_away=taken_away,
    )


@pytest_asyncio.fixture
async def seed(db_session: AsyncSession) -> Seed:
    """A Triton client whose flights mostly have no alias yet."""
    akb = Partner(code="AKB", display_name="AKB Cargo", prefix="A", is_dm_partner=True)
    triton = Partner(
        code="SYT", display_name="Triton", prefix="SYT", group_chat_id=-1001
    )
    db_session.add_all([akb, triton])
    await db_session.flush()
    db_session.add(
        PartnerFlightAlias(
            partner_id=triton.id,
            real_flight_name=SYT_ALIASED_FLIGHT,
            mask_flight_name=SYT_ALIASED_MASK,
        )
    )
    db_session.add_all(
        PartnerFlightAlias(
            partner_id=akb.id, real_flight_name=real, mask_flight_name=mask
        )
        for real, mask in AKB_ALIASES.items()
    )

    owner = Client(
        full_name="Owner",
        telegram_id=OWNER_TELEGRAM_ID,
        client_code=OWNER_CODE,
        phone="+998901234567",
        region="toshkent_city",
        district="chilonzor",
        address="Chilonzor 1",
    )
    neighbour = Client(
        full_name="Neighbour", telegram_id=7002, client_code=NEIGHBOUR_CODE
    )
    db_session.add_all([owner, neighbour])

    db_session.add_all(
        _web_report(OWNER_CODE, name, weight)
        for name, weight in WEB_REPORT_WEIGHTS.items()
    )
    db_session.add(_web_report(OWNER_CODE, UNSENT_FLIGHT, 4.0, sent_web=False))
    db_session.add(_web_report(NEIGHBOUR_CODE, NEIGHBOURS_FLIGHT, 5.0))
    db_session.add_all(
        ExpectedFlightCargo(
            flight_name=name, client_code=OWNER_CODE, track_code=f"YT{index:010d}"
        )
        for index, name in enumerate(EXPECTED_FLIGHTS, start=2)
    )

    transactions = {
        name: _owner_transaction(name, vazn=vazn) for name, vazn in PAID_FLIGHTS.items()
    }
    transactions[BONUS_REYS] = _owner_transaction(
        BONUS_REYS, balance_difference="5000", taken_away=True
    )
    transactions[WALLET_ADJ_REYS] = _owner_transaction(
        WALLET_ADJ_REYS, balance_difference="-1000", taken_away=True
    )
    db_session.add_all(transactions.values())

    # A fixed rate keeps the USD rate lookups away from the currency API.
    db_session.add(
        StaticData(id=1, use_custom_rate=True, custom_usd_rate=12650.0, extra_charge=0)
    )
    await db_session.commit()
    return Seed(owner=owner, transactions=transactions)


@pytest.fixture(autouse=True)
def offline_integrations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer Google Sheets from fixed rows and swallow Telegram sends."""

    async def find_client_group(
        self: GoogleSheetsChecker, client_code: str | list[str], reverse: bool = False
    ) -> dict[str, object]:
        return {"found": True, "matches": [{"flight_name": SHEETS_FLIGHT}]}

    async def get_track_codes(
        self: GoogleSheetsChecker, flight_name: str, client_code: str | list[str]
    ) -> list[str]:
        return [TRACK_CODE]

    async def send_message(chat_id: int, text: str, **kwargs: object) -> None:
        """Pretend Telegram accepted the admin notification."""

    monkeypatch.setattr(GoogleSheetsChecker, "find_client_group", find_client_group)
    monkeypatch.setattr(
        GoogleSheetsChecker, "get_track_codes_by_flight_and_client", get_track_codes
    )
    monkeypatch.setattr(bot, "send_message", send_message)


@pytest.fixture
def redis_client() -> FakeRedis:
    return FakeRedis(decode_responses=True)


@pytest_asyncio.fixture
async def app(
    db_engine: AsyncEngine, redis_client: FakeRedis
) -> AsyncIterator[FastAPI]:
    application = FastAPI()
    # Same routers, prefixes and order as src/bot/bot.py.
    application.include_router(reports_router, prefix="/api/v1")
    application.include_router(user_delivery_router, prefix="/api")
    application.include_router(payment_history_router, prefix="/api/v1")
    application.include_router(make_payment_router, prefix="/api/v1")

    db_client = DatabaseClient(db_engine.url.render_as_string(hide_password=False))
    application.state.db_client = db_client
    application.state.redis = redis_client
    try:
        yield application
    finally:
        await db_client.shutdown()


@pytest_asyncio.fixture
async def api(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def owner_headers(redis_client: FakeRedis, seed: Seed) -> dict[str, str]:
    """A session token stored the way the login endpoint stores it."""
    token = secrets.token_urlsafe(32)
    await redis_client.setex(
        f"{SESSION_PREFIX}{token}", SESSION_TTL_SECONDS, str(seed.owner.id)
    )
    return {"Authorization": f"Bearer {token}"}


async def _aliases(engine: AsyncEngine, partner_code: str) -> dict[str, str]:
    """Committed ``real -> mask`` pairs of one partner."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(
                PartnerFlightAlias.real_flight_name, PartnerFlightAlias.mask_flight_name
            )
            .join(Partner, Partner.id == PartnerFlightAlias.partner_id)
            .where(Partner.code == partner_code)
        )
        return {real: mask for real, mask in rows}


async def _alias_count(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        return await conn.scalar(select(func.count()).select_from(PartnerFlightAlias))


def _marker_rows() -> Select[tuple[int]]:
    return (
        select(func.count())
        .select_from(FlightCargo)
        .where(FlightCargo.flight_name == MARKER_FLIGHT)
    )


def _assert_no_real_flight_names(response: Response) -> None:
    leaked = sorted(name for name in REAL_FLIGHTS if name in response.text)
    assert not leaked, f"real flight names reached the client: {leaked}"


def _assert_only_masks(response: Response) -> None:
    """Neither a real flight name nor a placeholder of either kind."""
    _assert_no_real_flight_names(response)
    assert f"{FLIGHT_ORDINAL_PREFIX} #" not in response.text
    assert FLIGHT_PLACEHOLDER not in response.text


# ---------------------------------------------------------------------------
# Lists read from the client's own records mint, and the masks round-trip
# ---------------------------------------------------------------------------


async def test_report_flights_are_masks_that_filter_the_history(
    api: AsyncClient, db_engine: AsyncEngine, owner_headers: dict[str, str]
) -> None:
    listed = await api.get(
        f"/api/v1/reports/flights/{OWNER_CODE}", headers=owner_headers
    )

    assert listed.status_code == 200, listed.text
    _assert_only_masks(listed)
    aliases = await _aliases(db_engine, "SYT")
    # Exactly the client's web-sent flights have aliases; the existing one is kept.
    assert set(aliases) == set(WEB_REPORT_WEIGHTS)
    assert aliases[SYT_ALIASED_FLIGHT] == SYT_ALIASED_MASK
    assert listed.json() == [
        aliases[name] for name in sorted(WEB_REPORT_WEIGHTS, reverse=True)
    ]
    assert await _aliases(db_engine, "AKB") == AKB_ALIASES

    for real_name, mask in aliases.items():
        history = await api.get(
            f"/api/v1/reports/history/{OWNER_CODE}",
            params={"flight_name": mask},
            headers=owner_headers,
        )
        assert history.status_code == 200, history.text
        _assert_only_masks(history)
        assert [
            (item["flight_name"], item["total_weight"]) for item in history.json()
        ] == [(mask, WEB_REPORT_WEIGHTS[real_name])]


async def test_report_flight_masks_open_the_payment_details(
    api: AsyncClient, db_engine: AsyncEngine, owner_headers: dict[str, str]
) -> None:
    listed = await api.get(
        f"/api/v1/reports/flights/{OWNER_CODE}", headers=owner_headers
    )
    assert listed.status_code == 200, listed.text
    _assert_only_masks(listed)
    real_by_mask = {
        mask: real for real, mask in (await _aliases(db_engine, "SYT")).items()
    }

    for mask in listed.json():
        details = await api.get(
            f"/api/v1/payments/flight-details/{mask}", headers=owner_headers
        )
        assert details.status_code == 200, details.text
        _assert_only_masks(details)
        body = details.json()
        assert (body["flight_name"], body["total_weight"]) == (
            mask,
            WEB_REPORT_WEIGHTS[real_by_mask[mask]],
        )


async def test_payment_flights_are_masks_that_open_the_details(
    api: AsyncClient, db_engine: AsyncEngine, owner_headers: dict[str, str]
) -> None:
    listed = await api.get("/api/v1/payments/available-flights", headers=owner_headers)

    assert listed.status_code == 200, listed.text
    _assert_only_masks(listed)
    aliases = await _aliases(db_engine, "SYT")
    # Sheets first, then expected cargo by name; none of these is paid yet.
    unpaid = (SHEETS_FLIGHT, *EXPECTED_FLIGHTS)
    assert set(aliases) == {SYT_ALIASED_FLIGHT, *unpaid}
    assert [item["flight_name"] for item in listed.json()["flights"]] == [
        aliases[name] for name in unpaid
    ]

    # A flight whose report was not sent yet has nothing to pay: its details are
    # a 404 by design, so only the reported flights are opened.
    for name in (name for name in unpaid if name in WEB_REPORT_WEIGHTS):
        details = await api.get(
            f"/api/v1/payments/flight-details/{aliases[name]}", headers=owner_headers
        )
        assert details.status_code == 200, details.text
        assert details.json()["flight_name"] == aliases[name]


@pytest.mark.parametrize("request_kind", ["standard", "uzpost"])
async def test_paid_flights_list_an_unaliased_flight_the_delivery_request_accepts(
    api: AsyncClient,
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    owner_headers: dict[str, str],
    request_kind: str,
) -> None:
    listed = await api.get("/api/user/delivery/flights", headers=owner_headers)

    assert listed.status_code == 200, listed.text
    _assert_only_masks(listed)
    aliases = await _aliases(db_engine, "SYT")
    # Only confirmed paid flights mint, not the unpaid Sheets / expected candidates.
    assert set(aliases) == set(PAID_FLIGHTS)
    assert UNALIASED_PAID_FLIGHT in aliases
    paid_newest_first = sorted(PAID_FLIGHTS, reverse=True)
    masks = [aliases[name] for name in paid_newest_first]
    assert listed.json() == {
        "flights": [{"flight_name": mask, "display_name": mask} for mask in masks]
    }

    if request_kind == "standard":
        submitted = await api.post(
            "/api/user/delivery/request/standard",
            json={"delivery_type": "akb", "flight_names": masks},
            headers=owner_headers,
        )
    else:
        submitted = await api.post(
            "/api/user/delivery/request/uzpost",
            data={"flight_names": json.dumps(masks)},
            headers=owner_headers,
        )

    assert submitted.status_code == 200, submitted.text
    stored = await db_session.scalar(
        select(DeliveryRequest.flight_names).where(
            DeliveryRequest.id == submitted.json()["delivery_request_id"]
        )
    )
    assert json.loads(stored) == paid_newest_first

    history = await api.get("/api/user/delivery/history", headers=owner_headers)
    assert history.status_code == 200, history.text
    assert [item["flight_names"] for item in history.json()["requests"]] == [masks]


async def test_payment_history_masks_flights_and_leaves_bookkeeping_rows_unaliased(
    api: AsyncClient,
    db_engine: AsyncEngine,
    owner_headers: dict[str, str],
    seed: Seed,
) -> None:
    response = await api.get("/api/v1/payments/history", headers=owner_headers)

    assert response.status_code == 200, response.text
    _assert_no_real_flight_names(response)
    aliases = await _aliases(db_engine, "SYT")
    assert set(aliases) == set(PAID_FLIGHTS)
    shown = {item["id"]: item["flight_name"] for item in response.json()["items"]}
    assert shown == {
        **{seed.transactions[name].id: aliases[name] for name in PAID_FLIGHTS},
        seed.transactions[BONUS_REYS].id: FLIGHT_PLACEHOLDER,
        seed.transactions[WALLET_ADJ_REYS].id: FLIGHT_PLACEHOLDER,
    }


# ---------------------------------------------------------------------------
# A flight name from the request only translates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UserInput:
    """A request carrying a flight name the client typed or crafted."""

    method: str
    url: str
    status: int
    params: dict[str, str] = field(default_factory=dict)
    body: dict[str, object] | None = None
    shown_flight: str | None = None
    """The ``flight_name`` the response must render, when it renders one."""


USER_INPUTS = [
    pytest.param(
        UserInput(
            "GET",
            f"/api/v1/reports/history/{OWNER_CODE}",
            200,
            params={"flight_name": UNKNOWN_FLIGHT},
        ),
        id="history-filter-unknown",
    ),
    pytest.param(
        UserInput(
            "GET",
            f"/api/v1/reports/history/{OWNER_CODE}",
            200,
            params={"flight_name": NEIGHBOURS_FLIGHT},
        ),
        id="history-filter-neighbours-flight",
    ),
    pytest.param(
        UserInput("GET", f"/api/v1/payments/flight-details/{UNKNOWN_FLIGHT}", 404),
        id="flight-details-unknown",
    ),
    pytest.param(
        UserInput(
            "GET",
            f"/api/v1/payments/flight-details/{UNALIASED_REPORT}",
            200,
            shown_flight=FLIGHT_PLACEHOLDER,
        ),
        id="flight-details-typed-real-name",
    ),
    pytest.param(
        UserInput(
            "POST",
            "/api/v1/payments/submit/cash",
            404,
            body={"flight_name": UNKNOWN_FLIGHT},
        ),
        id="cash-unknown",
    ),
    pytest.param(
        UserInput(
            "POST",
            "/api/v1/payments/submit/wallet-only",
            404,
            body={"flight_name": UNKNOWN_FLIGHT, "amount": 1000},
        ),
        id="wallet-only-unknown",
    ),
    pytest.param(
        UserInput(
            "POST",
            "/api/user/delivery/calculate-uzpost",
            200,
            body={"flight_names": [UNKNOWN_FLIGHT]},
        ),
        id="calculate-uzpost-unknown",
    ),
]


@pytest.mark.parametrize("user_input", USER_INPUTS)
async def test_a_flight_name_from_the_request_never_mints(
    api: AsyncClient,
    db_engine: AsyncEngine,
    owner_headers: dict[str, str],
    user_input: UserInput,
) -> None:
    before = await _alias_count(db_engine)

    response = await api.request(
        user_input.method,
        user_input.url,
        params=user_input.params,
        json=user_input.body,
        headers=owner_headers,
    )

    assert response.status_code == user_input.status, response.text
    _assert_no_real_flight_names(response)
    if user_input.shown_flight is not None:
        assert response.json()["flight_name"] == user_input.shown_flight
    assert await _alias_count(db_engine) == before


async def test_delivery_history_never_mints_the_flights_a_request_named(
    api: AsyncClient, db_engine: AsyncEngine, owner_headers: dict[str, str]
) -> None:
    before = await _alias_count(db_engine)
    typed = [UNKNOWN_FLIGHT, UNALIASED_PAID_FLIGHT]

    submitted = await api.post(
        "/api/user/delivery/request/standard",
        json={"delivery_type": "akb", "flight_names": typed},
        headers=owner_headers,
    )
    assert submitted.status_code == 200, submitted.text
    history = await api.get("/api/user/delivery/history", headers=owner_headers)

    assert history.status_code == 200, history.text
    _assert_no_real_flight_names(history)
    assert [item["flight_names"] for item in history.json()["requests"]] == [
        [FLIGHT_PLACEHOLDER] * len(typed)
    ]
    assert await _alias_count(db_engine) == before


# ---------------------------------------------------------------------------
# Minting runs beside the request's transaction
# ---------------------------------------------------------------------------


@dataclass
class SessionProbe:
    """The request session's state, read once the endpoint has returned."""

    in_transaction: bool | None = None
    pending_marker_rows: int | None = None


MINTING_READS = [
    pytest.param(f"/api/v1/reports/flights/{OWNER_CODE}", id="report-flights"),
    pytest.param(f"/api/v1/reports/history/{OWNER_CODE}", id="report-history"),
    pytest.param("/api/v1/payments/available-flights", id="payment-flights"),
    pytest.param("/api/user/delivery/flights", id="paid-flights"),
    pytest.param("/api/v1/payments/history", id="payment-history"),
]


@pytest.mark.parametrize("url", MINTING_READS)
async def test_minting_neither_commits_nor_rolls_back_the_request_session(
    app: FastAPI,
    api: AsyncClient,
    db_engine: AsyncEngine,
    owner_headers: dict[str, str],
    url: str,
) -> None:
    probe = SessionProbe()
    session_factory = app.state.db_client.session_factory

    async def get_db_with_pending_row() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            session.add(
                FlightCargo(
                    flight_name=MARKER_FLIGHT,
                    client_id=NEIGHBOUR_CODE,
                    photo_file_ids="[]",
                )
            )
            await session.flush()
            yield session
            probe.in_transaction = session.in_transaction()
            probe.pending_marker_rows = await session.scalar(_marker_rows())

    app.dependency_overrides[get_db] = get_db_with_pending_row
    before = await _alias_count(db_engine)

    response = await api.get(url, headers=owner_headers)

    assert response.status_code == 200, response.text
    # The request minted aliases, and they are committed ...
    assert await _alias_count(db_engine) > before
    # ... while the row the request flushed first is still pending in its session
    # and was never committed.
    assert probe == SessionProbe(in_transaction=True, pending_marker_rows=1)
    async with db_engine.connect() as conn:
        assert await conn.scalar(_marker_rows()) == 0
