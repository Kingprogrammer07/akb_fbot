"""
Routing of the staff client-verification endpoints for client codes with ``/``.

Client codes look like ``A01-1/1`` (Tashkent) or ``A80/1`` (other regions), and
the admin panel (``akb_web/src/api/verification.ts``) interpolates them into the
path without encoding.  A plain ``{client_code}`` segment cannot match ``/``, so
every such request used to 404.  Captured as a ``path`` segment, the code also
matches ``/``, so each route has to be declared before any route whose pattern
would swallow its URL.

The tests mount the real router and authenticate with an admin JWT through the
real ``get_admin_from_jwt`` and ``require_permission`` chain, against a seeded
account whose role holds ``clients:read``.  Requests are sent raw, as the admin
panel does today, and percent-encoded.  These are staff endpoints: real flight
names are expected in their responses.
"""

from decimal import Decimal
from urllib.parse import quote

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.verification import FlightPaymentSummary
from src.api.services.verification import CargoService, VerificationService
from src.api.utils.admin_jwt import create_admin_token
from src.config import config
from src.infrastructure.database.models.admin_account import AdminAccount
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.role import Permission, Role
from src.infrastructure.database.models.static_data import StaticData

# ``api`` and ``redis_client`` are fixtures, re-exported so pytest finds them here.
from tests._api_fakes import api as api
from tests._api_fakes import redis_client as redis_client

EXTRA_CODE = "A01-1/1"
CLIENT_CODE = "AKB01-1/1"
UNPAID_FLIGHT = "M200"
PAID_FLIGHT = "M300"

VERIFIER = "verifier"
COURIER = "courier"

UNPAID_CARGO_QUERY = {
    "filter_type": "all",
    "sort_order": "asc",
    "limit": "10",
    "offset": "0",
}
ROUTE_SUFFIXES = {
    "client-info": "",
    "unpaid-cargo": "/cargo/unpaid",
    "client-flights": "/flights",
    "unpaid-cargo-flights": "/cargo/unpaid/flights",
    "payment-summary": f"/flights/{UNPAID_FLIGHT}/payment-summary",
}
PAYMENT_SUMMARY = FlightPaymentSummary(
    total_weight=2.5,
    price_per_kg_usd=8.0,
    price_per_kg_uzs=101200.0,
    extra_charge=0.0,
    total_payment=253000.0,
    track_codes=["YT1000000001"],
)

ENCODINGS = pytest.mark.parametrize("encoded", [False, True], ids=["raw", "encoded"])


@pytest_asyncio.fixture
async def admins(db_session: AsyncSession) -> dict[str, AdminAccount]:
    """A client with cargo in two flights, and a staff account per role."""
    owner = Client(
        full_name="Owner",
        telegram_id=6001,
        extra_code=EXTRA_CODE,
        client_code=CLIENT_CODE,
    )
    roles = {
        VERIFIER: Role(
            name=VERIFIER, permissions=[Permission(resource="clients", action="read")]
        ),
        COURIER: Role(name=COURIER),
    }
    accounts = {
        name: AdminAccount(
            client=Client(full_name=f"{name} staff", telegram_id=6100 + number),
            role=role,
            system_username=name,
            pin_hash="unused-by-jwt-auth",
        )
        for number, (name, role) in enumerate(roles.items(), start=1)
    }
    db_session.add(owner)
    db_session.add_all(accounts.values())
    # Stored under the second alias: a handler given a truncated code finds nothing.
    db_session.add_all(
        FlightCargo(
            flight_name=flight,
            client_id=CLIENT_CODE,
            photo_file_ids="[]",
            weight_kg=Decimal("2.50"),
            price_per_kg=Decimal("8.00"),
            is_sent=True,
        )
        for flight in (UNPAID_FLIGHT, PAID_FLIGHT)
    )
    db_session.add(
        ClientTransaction(
            telegram_id=owner.telegram_id,
            client_code=EXTRA_CODE,
            qator_raqami=0,
            reys=PAID_FLIGHT,
            summa=253000.0,
            vazn="2.50",
            payment_type="cash",
            payment_status="paid",
            paid_amount=253000.0,
            remaining_amount=0.0,
            payment_balance_difference=0.0,
        )
    )
    # A fixed rate keeps get_usd_rate from falling back to the currency API.
    db_session.add(StaticData(id=1, use_custom_rate=True, custom_usd_rate=12650.0))
    await db_session.commit()
    return accounts


@pytest.fixture(autouse=True)
def no_google_sheets(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Sheets lookup would call the Google API; these tests read the database."""

    async def no_flights(client_code: str) -> list[str]:
        return []

    monkeypatch.setattr(
        VerificationService, "_get_sheets_flights", staticmethod(no_flights)
    )


@pytest.fixture
def payment_calculations(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str | list[str], str]]:
    """Record what the payment-summary handler asks ``CargoService`` for.

    Routing is what these tests are about; the calculation itself is covered
    by ``tests/test_verification_payment_summary.py``.
    """
    calls: list[tuple[str | list[str], str]] = []

    async def calculate(
        client_code: str | list[str], flight_name: str, session: AsyncSession
    ) -> FlightPaymentSummary:
        calls.append((client_code, flight_name))
        return PAYMENT_SUMMARY

    monkeypatch.setattr(
        CargoService, "calculate_flight_payment", staticmethod(calculate)
    )
    return calls


def admin_headers(account: AdminAccount) -> dict[str, str]:
    """Mint an admin JWT the way the admin login endpoint does."""
    token, _ = create_admin_token(
        admin_id=account.id,
        role_name=account.role.name,
        secret=config.api.JWT_SECRET.get_secret_value(),
        algorithm=config.api.JWT_ALGORITHM,
        expire_minutes=5,
    )
    return {"X-Admin-Authorization": f"Bearer {token}"}


def verification_url(suffix: str = "", *, encoded: bool) -> str:
    code = quote(EXTRA_CODE, safe="") if encoded else EXTRA_CODE
    return f"/api/v1/verification/{code}{suffix}"


@ENCODINGS
async def test_client_info_resolves_a_code_containing_a_slash(
    api: AsyncClient, admins: dict[str, AdminAccount], encoded: bool
) -> None:
    response = await api.get(
        verification_url(encoded=encoded), headers=admin_headers(admins[VERIFIER])
    )

    assert response.status_code == 200, response.text
    client = response.json()["client"]
    assert (client["client_code"], client["full_name"]) == (EXTRA_CODE, "Owner")


@ENCODINGS
async def test_unpaid_cargo_resolves_a_code_containing_a_slash(
    api: AsyncClient, admins: dict[str, AdminAccount], encoded: bool
) -> None:
    response = await api.get(
        verification_url(ROUTE_SUFFIXES["unpaid-cargo"], encoded=encoded),
        params=UNPAID_CARGO_QUERY,
        headers=admin_headers(admins[VERIFIER]),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["flight_name"] for item in body["items"]] == [UNPAID_FLIGHT]
    assert body["total_count"] == 1


@ENCODINGS
async def test_client_flights_resolve_a_code_containing_a_slash(
    api: AsyncClient, admins: dict[str, AdminAccount], encoded: bool
) -> None:
    response = await api.get(
        verification_url(ROUTE_SUFFIXES["client-flights"], encoded=encoded),
        params={"include_sheets": "false", "include_database": "true"},
        headers=admin_headers(admins[VERIFIER]),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "flights": [PAID_FLIGHT, UNPAID_FLIGHT],
        "source": "database",
    }


@ENCODINGS
async def test_unpaid_cargo_flights_resolve_a_code_containing_a_slash(
    api: AsyncClient, admins: dict[str, AdminAccount], encoded: bool
) -> None:
    """``.../flights`` would also match this URL if it were declared first."""
    response = await api.get(
        verification_url(ROUTE_SUFFIXES["unpaid-cargo-flights"], encoded=encoded),
        headers=admin_headers(admins[VERIFIER]),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"flights": [UNPAID_FLIGHT], "source": "database"}


@ENCODINGS
async def test_flight_payment_summary_resolves_a_code_containing_a_slash(
    api: AsyncClient,
    admins: dict[str, AdminAccount],
    payment_calculations: list[tuple[str | list[str], str]],
    encoded: bool,
) -> None:
    response = await api.get(
        verification_url(ROUTE_SUFFIXES["payment-summary"], encoded=encoded),
        headers=admin_headers(admins[VERIFIER]),
    )

    assert response.status_code == 200, response.text
    assert response.json() == PAYMENT_SUMMARY.model_dump()
    assert payment_calculations == [([EXTRA_CODE, CLIENT_CODE], UNPAID_FLIGHT)]


async def test_search_still_reaches_its_own_handler(
    api: AsyncClient, admins: dict[str, AdminAccount]
) -> None:
    response = await api.get(
        "/api/v1/verification/search",
        params={"q": EXTRA_CODE},
        headers=admin_headers(admins[VERIFIER]),
    )

    assert response.status_code == 200, response.text
    assert response.json()["client"]["client_code"] == EXTRA_CODE


@pytest.mark.parametrize(
    "suffix", ROUTE_SUFFIXES.values(), ids=list(ROUTE_SUFFIXES.keys())
)
async def test_every_route_still_requires_clients_read(
    api: AsyncClient, admins: dict[str, AdminAccount], suffix: str
) -> None:
    response = await api.get(
        verification_url(suffix, encoded=False),
        params=UNPAID_CARGO_QUERY,
        headers=admin_headers(admins[COURIER]),
    )

    assert response.status_code == 403, response.text


@pytest.mark.parametrize(
    "url",
    ["/api/v1/verification/", "/api/v1/verification//cargo/unpaid/flights"],
    ids=["client-info", "unpaid-cargo-flights"],
)
async def test_a_request_without_a_client_code_is_rejected(
    api: AsyncClient, admins: dict[str, AdminAccount], url: str
) -> None:
    """A ``path`` segment also matches an empty string; no client has that code."""
    response = await api.get(url, headers=admin_headers(admins[VERIFIER]))

    assert response.status_code == 422, response.text
