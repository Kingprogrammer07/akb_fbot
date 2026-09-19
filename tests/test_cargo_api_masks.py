"""
Flight names in the cargo API responses an end user sees.

Real flight names (``M200``) must never reach a client: every flight is shown by
the mask of the client's partner (``AKB8``).  A flight read from the caller's own
rows gets an alias minted when it has none.  A flight the caller sends in the
path or the query is only translated back to its real name for the lookup: no
alias is ever minted from it, and the answer never names a flight the caller
did not send.

The tests mount the real routers and authenticate with a Redis session token,
the path the Mini App takes.
"""

from collections.abc import Iterable
from decimal import Decimal
from urllib.parse import quote

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.infrastructure.database.models.cargo_item import CargoItem
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_flight_alias import PartnerFlightAlias
from src.infrastructure.database.models.static_data import StaticData
from src.infrastructure.services.flight_display import FLIGHT_ORDINAL_PREFIX
from src.infrastructure.tools.datetime_utils import get_current_business_date

# ``api`` and ``redis_client`` are fixtures, re-exported so pytest finds them here.
from tests._api_fakes import api as api
from tests._api_fakes import bearer
from tests._api_fakes import redis_client as redis_client

OWNER_CODE = "A01-1/1"
TRITON_CODE = "SYT700"
NO_PARTNER_CODE = "Z5"

# The owner's parcels per real flight: M100 already has an AKB alias, M200 none.
OWNER_TRACKS = {"M100": ["YT1000000001"], "M200": ["YT2000000001"]}
# No track code may contain a flight name: responses are searched for them.
TRITON_TRACK = "YT7700000001"
NO_PARTNER_TRACK = "YT5000000001"

# M300 is an AKB flight the owner has no cargo in; T900 is Triton's.
SEEDED_ALIASES = [
    ("AKB", "M100", "AKB7"),
    ("AKB", "M300", "AKB-300"),
    ("SYT", "T900", "SYT1"),
]
# The next canonical AKB mask: custom masks such as AKB-300 do not advance it.
MINTED_M200 = "AKB8"

REAL_FLIGHTS = ("M100", "M200", "M300", "T900")
EVERY_FLIGHT_NAME = (
    *REAL_FLIGHTS,
    *(mask for _, _, mask in SEEDED_ALIASES),
    MINTED_M200,
)


@pytest_asyncio.fixture
async def seed(db_session: AsyncSession) -> dict[str, Client]:
    partners = {
        "AKB": Partner(
            code="AKB", display_name="AKB Cargo", prefix="A", is_dm_partner=True
        ),
        "SYT": Partner(
            code="SYT", display_name="Triton", prefix="SYT", group_chat_id=-1001
        ),
    }
    clients = {
        "owner": Client(full_name="Owner", telegram_id=5001, extra_code=OWNER_CODE),
        "triton": Client(full_name="Triton", telegram_id=5002, client_code=TRITON_CODE),
        "no_partner": Client(
            full_name="No partner", telegram_id=5003, client_code=NO_PARTNER_CODE
        ),
    }
    db_session.add_all([*partners.values(), *clients.values()])
    await db_session.flush()

    db_session.add_all(
        PartnerFlightAlias(
            partner_id=partners[code].id, real_flight_name=real, mask_flight_name=mask
        )
        for code, real, mask in SEEDED_ALIASES
    )
    parcels = [
        (OWNER_CODE, flight, track)
        for flight, tracks in OWNER_TRACKS.items()
        for track in tracks
    ]
    parcels += [
        (TRITON_CODE, "T900", TRITON_TRACK),
        (NO_PARTNER_CODE, "M200", NO_PARTNER_TRACK),
    ]
    db_session.add_all(
        CargoItem(
            track_code=track,
            client_id=code,
            flight_name=flight,
            checkin_status="pre",
            weight_kg="1.5",
        )
        for code, flight, track in parcels
    )
    # M200 has two billing rows for one parcel, so its items gain an EXTRA_ row.
    db_session.add_all(
        FlightCargo(
            flight_name=flight,
            client_id=OWNER_CODE,
            photo_file_ids="[]",
            weight_kg=Decimal("2.00"),
            price_per_kg=Decimal("9.00"),
            is_sent=True,
            is_sent_web=True,
        )
        for flight in ("M100", "M200", "M200")
    )
    # A fixed rate keeps get_usd_rate from falling back to the currency API.
    db_session.add(StaticData(id=1, use_custom_rate=True, custom_usd_rate=12650.0))
    await db_session.commit()
    return clients


@pytest.fixture
def sheet_lookups(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stand in for Google Sheets: record each flight looked up, find no rows."""
    flights: list[str] = []

    async def lookup(
        self: GoogleSheetsChecker, flight_name: str, client_code: str | list[str]
    ) -> list[str]:
        flights.append(flight_name)
        return []

    monkeypatch.setattr(
        GoogleSheetsChecker, "get_track_codes_by_flight_and_client", lookup
    )
    return flights


async def aliases(engine: AsyncEngine) -> list[tuple[str, str, str]]:
    """Committed ``(partner code, real, mask)`` rows in creation order."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(
                Partner.code,
                PartnerFlightAlias.real_flight_name,
                PartnerFlightAlias.mask_flight_name,
            )
            .join(Partner, Partner.id == PartnerFlightAlias.partner_id)
            .order_by(PartnerFlightAlias.id)
        )
        return [(code, real, mask) for code, real, mask in rows]


def assert_ok_and_hides(response: Response, hidden: Iterable[str]) -> None:
    assert response.status_code == 200, response.text
    leaked = sorted(name for name in hidden if name in response.text)
    assert leaked == [], response.text


def history_url(code: str = OWNER_CODE, flight: str | None = None) -> str:
    url = f"/api/v1/cargo/history/{code}/flights"
    return f"{url}/{flight}" if flight else url


async def flight_status(
    api: AsyncClient, headers: dict[str, str], flight: str
) -> Response:
    return await api.get(
        "/api/v1/cargo/flight-status",
        params={"flight_name": flight, "client_code": OWNER_CODE},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Flights read from the caller's own rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("client", "track_code", "mask"),
    [
        ("owner", OWNER_TRACKS["M100"][0], "AKB7"),
        ("owner", OWNER_TRACKS["M200"][0], MINTED_M200),
        ("triton", TRITON_TRACK, "SYT1"),
    ],
    ids=["existing-alias", "minted-alias", "other-partner"],
)
async def test_track_shows_the_callers_partner_mask(
    api: AsyncClient,
    redis_client: FakeRedis,
    seed: dict[str, Client],
    client: str,
    track_code: str,
    mask: str,
) -> None:
    response = await api.get(
        f"/api/v1/cargo/track/{track_code}",
        headers=await bearer(redis_client, seed[client]),
    )

    assert_ok_and_hides(response, REAL_FLIGHTS)
    items = response.json()["items"]
    assert items
    assert {item["flight_name"] for item in items} == {mask}


async def test_history_lists_masks_and_mints_only_the_callers_flights(
    api: AsyncClient,
    db_engine: AsyncEngine,
    redis_client: FakeRedis,
    seed: dict[str, Client],
) -> None:
    response = await api.get(
        history_url(), headers=await bearer(redis_client, seed["owner"])
    )

    assert_ok_and_hides(response, REAL_FLIGHTS)
    assert sorted(summary["flight_name"] for summary in response.json()) == [
        "AKB7",
        MINTED_M200,
    ]
    assert await aliases(db_engine) == [
        *SEEDED_ALIASES,
        ("AKB", "M200", MINTED_M200),
    ]


async def test_every_listed_mask_opens_its_flight_details(
    api: AsyncClient,
    db_engine: AsyncEngine,
    redis_client: FakeRedis,
    seed: dict[str, Client],
) -> None:
    headers = await bearer(redis_client, seed["owner"])
    summaries = (await api.get(history_url(), headers=headers)).json()
    real_by_mask = {mask: real for _, real, mask in await aliases(db_engine)}
    assert len(summaries) == len(OWNER_TRACKS)

    for summary in summaries:
        mask = summary["flight_name"]
        response = await api.get(history_url(flight=mask), headers=headers)

        assert_ok_and_hides(response, REAL_FLIGHTS)
        items = response.json()["items"]
        assert {item["flight_name"] for item in items} == {mask}
        track_codes = [item["track_code"] for item in items]
        extra = [code for code in track_codes if code.startswith("EXTRA_")]
        parcels = sorted(code for code in track_codes if code not in extra)
        real = real_by_mask[mask]
        assert parcels == OWNER_TRACKS[real]
        assert len(extra) == (1 if real == "M200" else 0)


async def test_every_listed_mask_checks_its_flight_status(
    api: AsyncClient,
    db_engine: AsyncEngine,
    redis_client: FakeRedis,
    seed: dict[str, Client],
    sheet_lookups: list[str],
) -> None:
    headers = await bearer(redis_client, seed["owner"])
    summaries = (await api.get(history_url(), headers=headers)).json()
    real_by_mask = {mask: real for _, real, mask in await aliases(db_engine)}
    masks = [summary["flight_name"] for summary in summaries]

    for mask in masks:
        response = await flight_status(api, headers, mask)

        assert_ok_and_hides(response, REAL_FLIGHTS)
        body = response.json()
        assert (body["flight_name"], body["exists_in_db"]) == (mask, True)
    # Sheets are opened by the real flight name, never by the mask.
    assert sheet_lookups == [real_by_mask[mask] for mask in masks]


async def test_flight_status_answers_a_real_name_of_the_callers_cargo_with_its_mask(
    api: AsyncClient,
    redis_client: FakeRedis,
    seed: dict[str, Client],
    sheet_lookups: list[str],
) -> None:
    response = await flight_status(
        api, await bearer(redis_client, seed["owner"]), "M100"
    )

    assert_ok_and_hides(response, ["M100"])
    body = response.json()
    assert (body["flight_name"], body["exists_in_db"]) == ("AKB7", True)


async def test_leftover_billing_rows_are_labelled_from_their_own_flight_name(
    api: AsyncClient,
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: FakeRedis,
    seed: dict[str, Client],
) -> None:
    """``EXTRA_`` rows used to take the lookup string instead of the row's name.

    A flight typed in another case then minted a second alias for a flight name
    that exists only in the request.
    """
    akb = await db_session.scalar(select(Partner).where(Partner.code == "AKB"))
    db_session.add(
        PartnerFlightAlias(
            partner_id=akb.id, real_flight_name="M200", mask_flight_name=MINTED_M200
        )
    )
    await db_session.commit()

    response = await api.get(
        history_url(flight="m200"), headers=await bearer(redis_client, seed["owner"])
    )

    assert_ok_and_hides(response, [*REAL_FLIGHTS, "m200"])
    items = response.json()["items"]
    assert sorted(item["track_code"].startswith("EXTRA_") for item in items) == [
        False,
        True,
    ]
    assert {item["flight_name"] for item in items} == {MINTED_M200}
    extra = next(item for item in items if item["track_code"].startswith("EXTRA_"))
    # A Tashkent business date, written like the imported check-in dates.
    assert extra["post_checkin_date"] == get_current_business_date().isoformat()
    assert await aliases(db_engine) == [
        *SEEDED_ALIASES,
        ("AKB", "M200", MINTED_M200),
    ]


async def test_client_without_a_partner_never_sees_a_real_flight_name(
    api: AsyncClient,
    db_engine: AsyncEngine,
    redis_client: FakeRedis,
    seed: dict[str, Client],
) -> None:
    headers = await bearer(redis_client, seed["no_partner"])

    track = await api.get(f"/api/v1/cargo/track/{NO_PARTNER_TRACK}", headers=headers)
    history = await api.get(history_url(NO_PARTNER_CODE), headers=headers)

    assert_ok_and_hides(track, REAL_FLIGHTS)
    assert_ok_and_hides(history, REAL_FLIGHTS)
    assert [item["flight_name"] for item in track.json()["items"]] == [None]
    assert [summary["flight_name"] for summary in history.json()] == [
        f"{FLIGHT_ORDINAL_PREFIX} #1"
    ]
    assert await aliases(db_engine) == SEEDED_ALIASES


async def test_client_without_a_partner_opens_flight_details_from_the_listed_label(
    api: AsyncClient,
    db_engine: AsyncEngine,
    redis_client: FakeRedis,
    seed: dict[str, Client],
    sheet_lookups: list[str],
) -> None:
    """With no mask the list shows ``Reys #N``, and that label opens the flight."""
    headers = await bearer(redis_client, seed["no_partner"])
    history = await api.get(history_url(NO_PARTNER_CODE), headers=headers)
    [label] = [summary["flight_name"] for summary in history.json()]

    details = await api.get(history_url(NO_PARTNER_CODE, quote(label)), headers=headers)

    assert_ok_and_hides(details, REAL_FLIGHTS)
    assert [item["track_code"] for item in details.json()["items"]] == [NO_PARTNER_TRACK]
    assert await aliases(db_engine) == SEEDED_ALIASES


# ---------------------------------------------------------------------------
# Flights sent by the caller
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flight",
    ["M999", "M300", "AKB-300", "T900", "SYT1"],
    ids=[
        "unknown",
        "partner-flight-without-cargo",
        "partner-mask-without-cargo",
        "other-partner-flight",
        "other-partner-mask",
    ],
)
async def test_flights_from_the_request_are_never_minted_or_resolved_for_display(
    api: AsyncClient,
    db_engine: AsyncEngine,
    redis_client: FakeRedis,
    seed: dict[str, Client],
    sheet_lookups: list[str],
    flight: str,
) -> None:
    """Only what the caller sent comes back: no other real name and no other mask.

    Answering ``M300`` with ``AKB-300`` would let a caller confirm the real names
    behind their partner's masks by guessing them.
    """
    headers = await bearer(redis_client, seed["owner"])
    other_names = [name for name in EVERY_FLIGHT_NAME if name != flight]

    details = await api.get(history_url(flight=flight), headers=headers)
    status_response = await flight_status(api, headers, flight)

    assert_ok_and_hides(details, other_names)
    assert (details.json()["items"], details.json()["total"]) == ([], 0)
    assert_ok_and_hides(status_response, other_names)
    body = status_response.json()
    assert (body["flight_name"], body["exists_in_db"]) == (flight, False)
    assert await aliases(db_engine) == SEEDED_ALIASES


@pytest.mark.parametrize(
    "flight", ["%25", "%25%25", "_"], ids=["percent", "percents", "underscore"]
)
async def test_a_wildcard_flight_in_the_path_matches_no_cargo_and_mints_nothing(
    api: AsyncClient,
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: FakeRedis,
    seed: dict[str, Client],
    sheet_lookups: list[str],
    flight: str,
) -> None:
    """A flight in the path is compared as a name, never as a LIKE pattern.

    An owned parcel with an empty flight name used to match ``%``; its item
    then carried the request string as its flight name, which was minted.
    """
    db_session.add(
        CargoItem(
            track_code="YT1000000099",
            client_id=OWNER_CODE,
            flight_name="",
            checkin_status="pre",
            weight_kg="1.0",
        )
    )
    await db_session.commit()

    details = await api.get(
        history_url(flight=flight), headers=await bearer(redis_client, seed["owner"])
    )

    assert details.status_code == 200, details.text
    assert (details.json()["items"], details.json()["total"]) == ([], 0)
    assert await aliases(db_engine) == SEEDED_ALIASES
