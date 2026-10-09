"""
Ownership scoping for client-code and track-code lookups.

Client codes and track codes are short and guessable, so every user-facing
lookup is limited to the caller's ``Client.active_codes``.  The comparison has
to hold up against the data as it is stored: ``cargo_items.client_id`` arrives
from spreadsheet imports and the partner API with stray padding and mixed case,
and a client's own stored code can be padded too (``ClientDAO.get_by_extra_code``
trims for exactly that reason).  Padding must neither hide a parcel from its
owner nor let a blank value match anything.

The HTTP tests mount the real routers under the prefixes ``src/bot/bot.py``
uses and authenticate with a Redis session token, the path the Mini App takes.
"""

from decimal import Decimal
from urllib.parse import quote

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.utils.authz import assert_owns_client_code
from src.infrastructure.database.models.cargo_item import CargoItem
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.static_data import StaticData
from src.infrastructure.services.cargo_item import CargoItemService
from src.infrastructure.tools.datetime_utils import get_current_time
# ``api`` and ``redis_client`` are fixtures, re-exported so pytest finds them here.
from tests._api_fakes import api as api
from tests._api_fakes import bearer
from tests._api_fakes import redis_client as redis_client

OWNER_CODES = {
    "extra_code": "A01-1/1",
    "client_code": "AKB01-1/1",
    "legacy_code": "AKB570",
}
OTHER_CODES = {"extra_code": "A80/1", "client_code": "AKB80/1", "legacy_code": "AKB571"}

TRACK_CODE = "YT7788990011"
BLANK_TRACK_CODE = "YT0000000000"
FLIGHT_NAME = "M200"

REPORT_ENDPOINTS = ("flights", "history")


# ---------------------------------------------------------------------------
# assert_owns_client_code — no database needed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("requested", ["A01-1/1", "AKB01-1/1", "AKB570", "  akb570 "])
def test_every_alias_belongs_to_its_owner(requested: str) -> None:
    assert_owns_client_code(Client(full_name="Owner", **OWNER_CODES), requested)


def test_padded_stored_code_still_belongs_to_its_owner() -> None:
    """The profile endpoint hands the raw stored code to the web app, padding included."""
    client = Client(full_name="Padded", extra_code=" A02-14 ")

    assert_owns_client_code(client, client.primary_code)
    assert_owns_client_code(client, "A02-14")


@pytest.mark.parametrize("requested", ["A80/1", "AKB571", "", "   "])
def test_foreign_or_blank_code_is_forbidden(requested: str) -> None:
    """A whitespace-only alias normalises to "" and must not make a blank request pass."""
    client = Client(
        full_name="Owner",
        extra_code="A01-1/1",
        client_code="AKB01-1/1",
        legacy_code="   ",
    )

    with pytest.raises(HTTPException) as exc_info:
        assert_owns_client_code(client, requested)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Database-backed fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seed(db_session: AsyncSession) -> dict[str, Client]:
    clients = {
        "owner": Client(full_name="Owner", telegram_id=1001, **OWNER_CODES),
        "other": Client(full_name="Other", telegram_id=1002, **OTHER_CODES),
        "padded": Client(full_name="Padded", telegram_id=1003, extra_code=" A02-14 "),
        "blank": Client(
            full_name="Blank", telegram_id=1004, extra_code="A03-7", legacy_code="   "
        ),
    }
    db_session.add_all(clients.values())
    db_session.add_all(
        [
            # The owner's parcel, imported under the legacy alias with padding and case noise.
            CargoItem(
                track_code=TRACK_CODE,
                client_id="  akb570 ",
                flight_name=FLIGHT_NAME,
                checkin_status="pre",
                weight_kg="2.5",
            ),
            CargoItem(
                track_code=BLANK_TRACK_CODE, client_id="   ", flight_name=FLIGHT_NAME
            ),
        ]
    )
    # A fixed rate keeps get_usd_rate from falling back to the currency API.
    db_session.add(StaticData(id=1, use_custom_rate=True, custom_usd_rate=12650.0))
    await db_session.commit()
    return clients


def report_url(endpoint: str, code: str) -> str:
    """Build the URL like the browser does: ``/`` kept, spaces percent-encoded."""
    return f"/api/v1/reports/{endpoint}/{quote(code, safe='/')}"


# ---------------------------------------------------------------------------
# Track-code lookup
# ---------------------------------------------------------------------------


async def test_owner_finds_cargo_whose_client_id_is_padded(
    api: AsyncClient, redis_client: FakeRedis, seed: dict[str, Client]
) -> None:
    response = await api.get(
        f"/api/v1/cargo/track/{TRACK_CODE}",
        headers=await bearer(redis_client, seed["owner"]),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["found"] is True
    assert [item["track_code"] for item in body["items"]] == [TRACK_CODE]
    assert body["total_count"] == 1


async def test_padded_cargo_row_is_enriched_from_rows_under_the_trimmed_code(
    api: AsyncClient,
    db_session: AsyncSession,
    redis_client: FakeRedis,
    seed: dict[str, Client],
) -> None:
    """Billing and pickup rows are keyed by the clean code, not the imported padding.

    ``flight_cargos`` and ``client_transaction_data`` are matched with
    ``upper(column) == value.upper()``: an untrimmed ``client_id`` misses both, and
    the parcel falls back to its China-side weight, no price and ``pre`` status.
    """
    db_session.add_all(
        [
            FlightCargo(
                flight_name=FLIGHT_NAME,
                client_id="AKB570",
                photo_file_ids="[]",
                weight_kg=Decimal("3.40"),
                price_per_kg=Decimal("9.20"),
                is_sent=True,
                is_sent_web=True,
            ),
            ClientTransaction(
                telegram_id=seed["owner"].telegram_id,
                client_code="AKB570",
                qator_raqami=0,
                reys=FLIGHT_NAME,
                summa=31.28,
                vazn="3.40",
                payment_type="cash",
                payment_status="paid",
                paid_amount=31.28,
                remaining_amount=0.0,
                payment_balance_difference=0.0,
                is_taken_away=True,
                taken_away_date=get_current_time(),
            ),
        ]
    )
    await db_session.commit()

    response = await api.get(
        f"/api/v1/cargo/track/{TRACK_CODE}",
        headers=await bearer(redis_client, seed["owner"]),
    )

    assert response.status_code == 200, response.text
    [item] = response.json()["items"]
    assert item["weight_kg"] == "3.40"
    assert item["price_per_kg_usd"] == "9.2"
    assert item["checkin_status"] == "post"
    assert item["is_taken_away"] is True


async def test_other_client_gets_not_found_for_owner_track_code(
    api: AsyncClient, redis_client: FakeRedis, seed: dict[str, Client]
) -> None:
    response = await api.get(
        f"/api/v1/cargo/track/{TRACK_CODE}",
        headers=await bearer(redis_client, seed["other"]),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "found": False,
        "track_code": TRACK_CODE,
        "items": [],
        "total_count": 0,
    }


async def test_blank_client_id_is_attributed_to_nobody(
    db_session: AsyncSession, seed: dict[str, Client]
) -> None:
    """A whitespace-only alias must not claim a row whose client_id is blank."""
    result = await CargoItemService().search_by_track_code(
        BLANK_TRACK_CODE,
        db_session,
        allowed_client_codes=set(seed["blank"].active_codes),
    )

    assert result == {"found": False, "items": [], "total_count": 0}


# ---------------------------------------------------------------------------
# Report endpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("endpoint", REPORT_ENDPOINTS)
@pytest.mark.parametrize("code", ["A80/1", "AKB571", "A99-9/9"])
async def test_reports_forbid_codes_the_caller_does_not_own(
    api: AsyncClient,
    redis_client: FakeRedis,
    seed: dict[str, Client],
    endpoint: str,
    code: str,
) -> None:
    response = await api.get(
        report_url(endpoint, code), headers=await bearer(redis_client, seed["owner"])
    )

    assert response.status_code == 403, response.text


@pytest.mark.parametrize("endpoint", REPORT_ENDPOINTS)
@pytest.mark.parametrize("code", ["A01-1/1", "AKB01-1/1", "AKB570", "akb570"])
async def test_reports_allow_every_owned_alias(
    api: AsyncClient,
    redis_client: FakeRedis,
    seed: dict[str, Client],
    endpoint: str,
    code: str,
) -> None:
    response = await api.get(
        report_url(endpoint, code), headers=await bearer(redis_client, seed["owner"])
    )

    assert response.status_code == 200, response.text
    assert response.json() == []


@pytest.mark.parametrize("endpoint", REPORT_ENDPOINTS)
async def test_reports_allow_the_padded_code_the_profile_endpoint_returns(
    api: AsyncClient, redis_client: FakeRedis, seed: dict[str, Client], endpoint: str
) -> None:
    """The web app sends ``profile.client_code``, which is ``Client.primary_code`` verbatim."""
    padded = seed["padded"]

    response = await api.get(
        report_url(endpoint, padded.primary_code),
        headers=await bearer(redis_client, padded),
    )

    assert response.status_code == 200, response.text
