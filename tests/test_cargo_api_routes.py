"""
Routing of the cargo history endpoints for client codes that contain ``/``.

Client codes look like ``A01-1/1`` (Tashkent) or ``A80/1`` (other regions), and
the web app (``akb_web/src/api/services/cargo.ts``) interpolates them into the
path without encoding.  A plain ``{client_code}`` segment cannot match ``/``, so
every such request used to 404.  With the code captured as a ``path`` segment,
the summary route (``.../flights``) and the detail route
(``.../flights/{flight_name}``) must still reach their own handlers, and
ownership must still be enforced.

The tests mount the real router under the prefix ``src/bot/bot.py`` uses and
authenticate with a Redis session token, the path the Mini App takes.  Every
request is sent raw, as the web app does today, and percent-encoded, as it would
be with ``encodeURIComponent``: the ASGI server decodes ``%2F`` before routing,
so both forms have to resolve the same way.
"""

from urllib.parse import quote

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.cargo_item import CargoItem
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.static_data import StaticData
# ``api`` and ``redis_client`` are fixtures, re-exported so pytest finds them here.
from tests._api_fakes import api as api
from tests._api_fakes import bearer
from tests._api_fakes import redis_client as redis_client

OWNER_CODE = "A01-1/1"
OTHER_CODE = "A80/1"
FLIGHT_NAME = "M200"
OWNER_TRACK_CODES = ["YT1000000001", "YT1000000002"]
OTHER_TRACK_CODE = "YT2000000001"
PARCEL_WEIGHT_KG = "1.5"

ENCODINGS = pytest.mark.parametrize("encoded", [False, True], ids=["raw", "encoded"])


@pytest_asyncio.fixture
async def seed(db_session: AsyncSession) -> dict[str, Client]:
    """Two clients with slash codes whose parcels share one flight."""
    clients = {
        "owner": Client(full_name="Owner", telegram_id=2001, extra_code=OWNER_CODE),
        "other": Client(full_name="Other", telegram_id=2002, extra_code=OTHER_CODE),
    }
    db_session.add_all(clients.values())
    parcels = [(OWNER_CODE, code) for code in OWNER_TRACK_CODES]
    parcels.append((OTHER_CODE, OTHER_TRACK_CODE))
    db_session.add_all(
        CargoItem(
            track_code=track_code,
            client_id=client_code,
            flight_name=FLIGHT_NAME,
            weight_kg=PARCEL_WEIGHT_KG,
        )
        for client_code, track_code in parcels
    )
    # A fixed rate keeps get_usd_rate from falling back to the currency API.
    db_session.add(StaticData(id=1, use_custom_rate=True, custom_usd_rate=12650.0))
    await db_session.commit()
    return clients


def history_url(code: str, *, encoded: bool, flight_name: str | None = None) -> str:
    """Build a history URL with the client code sent raw or percent-encoded."""
    segment = quote(code, safe="") if encoded else code
    url = f"/api/v1/cargo/history/{segment}/flights"
    return f"{url}/{flight_name}" if flight_name else url


@ENCODINGS
async def test_flight_history_resolves_a_code_containing_a_slash(
    api: AsyncClient, redis_client: FakeRedis, seed: dict[str, Client], encoded: bool
) -> None:
    response = await api.get(
        history_url(OWNER_CODE, encoded=encoded),
        headers=await bearer(redis_client, seed["owner"]),
    )

    assert response.status_code == 200, response.text
    # A list of per-flight summaries is the summary handler's shape; the detail
    # handler answers with a paginated object.
    [summary] = response.json()
    assert summary["total_count"] == len(OWNER_TRACK_CODES)
    assert summary["total_weight"] == float(PARCEL_WEIGHT_KG) * len(OWNER_TRACK_CODES)


@ENCODINGS
async def test_flight_details_resolve_a_code_containing_a_slash(
    api: AsyncClient, redis_client: FakeRedis, seed: dict[str, Client], encoded: bool
) -> None:
    response = await api.get(
        history_url(OWNER_CODE, encoded=encoded, flight_name=FLIGHT_NAME),
        headers=await bearer(redis_client, seed["owner"]),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["total"], body["page"], body["size"]) == (
        len(OWNER_TRACK_CODES),
        1,
        20,
    )
    assert sorted(item["track_code"] for item in body["items"]) == OWNER_TRACK_CODES


@ENCODINGS
@pytest.mark.parametrize(
    "flight_name", [None, FLIGHT_NAME], ids=["flights", "flight-details"]
)
async def test_history_forbids_a_slash_code_the_caller_does_not_own(
    api: AsyncClient,
    redis_client: FakeRedis,
    seed: dict[str, Client],
    encoded: bool,
    flight_name: str | None,
) -> None:
    response = await api.get(
        history_url(OTHER_CODE, encoded=encoded, flight_name=flight_name),
        headers=await bearer(redis_client, seed["owner"]),
    )

    assert response.status_code == 403, response.text
