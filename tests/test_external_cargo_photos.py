"""
Photos, flight and bag in the External Cargo API (webmandarin.uz astatka).

``photo_file_ids`` holds S3 keys and Telegram file ids, which mean nothing to
the partner. Each item therefore carries ``photo_urls``: a signed link per
photo, served by ``GET /api/v1/external/photos/{cargo_id}/{index}`` without the
API key, because the partner's browser opens them in ``<img>``. The signature
must open exactly that photo until it expires and nothing else, and the route
must only ever answer with a real raster image.

``by-track-code`` also names the scanned parcel's flight and every track code
of that client in that flight (the bag), matched exactly, never as a pattern.
"""

import time
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.api.routers import external_cargo_router as external
from src.api.services.telegram_file_service import TelegramFileService
from src.api.utils.external_photo_links import (
    LINK_BUCKET_SECONDS,
    LINK_MAX_LIFETIME_SECONDS,
    LINK_TTL_SECONDS,
    link_expiry,
    photo_link_valid,
    photo_signature,
)
from src.config import config
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.models.cargo_item import CargoItem
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.tools.s3_manager import s3_manager

PUBLIC_ORIGIN = "https://bot.akbcargo.test"
CLIENT = "A07-37"
FLIGHT = "M308"
S3_KEY = "flight_cargos/M308/A07-37_1.jpg"
TELEGRAM_ID = "AgACAgIAAxkBAAIBtelegramfileid"

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64
HTML = b"<html><script>alert(1)</script></html>"


# --------------------------------------------------------------------------
# Link signing
# --------------------------------------------------------------------------


def test_a_link_opens_only_its_own_photo_until_it_expires() -> None:
    now = 1_800_000_000
    exp = link_expiry(now)
    sig = photo_signature(42, 1, exp)

    assert photo_link_valid(42, 1, exp, sig, now=now)
    assert photo_link_valid(42, 1, exp, sig, now=exp - 1)
    assert not photo_link_valid(42, 1, exp, sig, now=exp)
    assert not photo_link_valid(43, 1, exp, sig, now=now)
    assert not photo_link_valid(42, 2, exp, sig, now=now)
    assert not photo_link_valid(42, 1, exp + 1, sig, now=now)
    assert not photo_link_valid(42, 1, exp, "0" * 64, now=now)


def test_an_expiry_too_far_ahead_is_refused_even_when_signed() -> None:
    now = 1_800_000_000
    far = now + LINK_MAX_LIFETIME_SECONDS + 1
    assert not photo_link_valid(42, 0, far, photo_signature(42, 0, far), now=now)


def test_expiries_snap_to_a_grid_and_last_at_least_the_ttl() -> None:
    now = 1_800_000_123
    exp = link_expiry(now)
    assert exp % LINK_BUCKET_SECONDS == 0
    assert LINK_TTL_SECONDS <= exp - now <= LINK_MAX_LIFETIME_SECONDS
    # The same photo keeps one link for a while, so caches can reuse it.
    assert link_expiry(now + 60) == exp


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://bot.akbcargo.uz", "https://bot.akbcargo.uz"),
        ("https://bot.akbcargo.uz/webhook/", "https://bot.akbcargo.uz"),
        (" https://bot.akbcargo.uz:8443 ", "https://bot.akbcargo.uz:8443"),
        ("http://bot.akbcargo.uz", None),
        ("https://user@evil.example", None),
        ("bot.akbcargo.uz", None),
        ("", None),
        (None, None),
    ],
)
def test_only_a_plain_https_origin_is_used_for_links(
    value: str | None, expected: str | None
) -> None:
    assert external._https_origin(value) == expected


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (JPEG, "image/jpeg"),
        (PNG, "image/png"),
        (WEBP, "image/webp"),
        (GIF, "image/gif"),
        (HTML, None),
        (b"RIFF\x24\x00\x00\x00WAVEfmt ", None),
        (b"", None),
    ],
)
def test_the_served_type_comes_from_the_bytes(
    data: bytes, media_type: str | None
) -> None:
    assert external._image_type(data) == media_type


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@pytest.fixture
def redis_client() -> FakeRedis:
    return FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def public_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.api, "EXTERNAL_PUBLIC_ORIGIN", PUBLIC_ORIGIN)


@pytest_asyncio.fixture
async def api(
    db_engine: AsyncEngine, redis_client: FakeRedis
) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    # Same prefix as src/bot/bot.py.
    app.include_router(external.router, prefix="/api/v1")
    db_client = DatabaseClient(db_engine.url.render_as_string(hide_password=False))
    app.state.db_client = db_client
    app.state.redis = redis_client
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://internal:8000"
        ) as client:
            yield client
    finally:
        await db_client.shutdown()


@pytest.fixture
def key() -> dict[str, str]:
    return {"X-API-Key": config.api.EXTERNAL_CARGO_KEY.get_secret_value()}


@pytest_asyncio.fixture
async def cargo(db_session: AsyncSession) -> FlightCargo:
    """One photo report row with an S3 photo, a Telegram photo and a blank."""
    row = FlightCargo(
        flight_name=FLIGHT,
        client_id=CLIENT,
        photo_file_ids=f'["{S3_KEY}", "{TELEGRAM_ID}", " "]',
        weight_kg="2.62",
    )
    db_session.add(row)
    db_session.add_all(
        [
            CargoItem(track_code="TC100", client_id=CLIENT, flight_name=FLIGHT),
            CargoItem(track_code=" tc101 ", client_id=CLIENT, flight_name=FLIGHT),
            CargoItem(track_code="TC100", client_id=CLIENT, flight_name=FLIGHT),
            CargoItem(track_code=None, client_id=CLIENT, flight_name=FLIGHT),
            # Same client, another flight: another bag.
            CargoItem(track_code="TC200", client_id=CLIENT, flight_name="M309"),
            # Another client whose code a pattern match on "A07_37" would hit.
            CargoItem(track_code="TC300", client_id="A07X37", flight_name=FLIGHT),
        ]
    )
    await db_session.commit()
    return row


def _path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}"


async def test_by_track_code_names_the_flight_the_bag_and_photo_links(
    api: AsyncClient, key: dict[str, str], cargo: FlightCargo
) -> None:
    response = await api.get(
        "/api/v1/external/flight-cargos/by-track-code",
        params={"track_code": "tc100"},
        headers=key,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["client_code"] == CLIENT
    assert body["flight_name"] == FLIGHT
    assert body["track_codes"] == ["TC100", "TC101"]

    (item,) = body["items"]
    links = item["photo_urls"]
    # One link per real photo; the blank entry gets none, and keeps its index.
    assert len(links) == 2
    for index, link in enumerate(links):
        parts = urlsplit(link)
        assert f"{parts.scheme}://{parts.netloc}" == PUBLIC_ORIGIN
        assert parts.path == f"/api/v1/external/photos/{cargo.id}/{index}"
        query = parse_qs(parts.query)
        assert set(query) == {"exp", "sig"}
    # Neither the bucket key nor the Telegram id leaks into a link.
    assert S3_KEY not in " ".join(links)
    assert TELEGRAM_ID not in " ".join(links)


async def test_by_client_code_carries_photo_links_too(
    api: AsyncClient, key: dict[str, str], cargo: FlightCargo
) -> None:
    response = await api.get(
        "/api/v1/external/flight-cargos",
        params={"client_code": CLIENT},
        headers=key,
    )

    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert len(item["photo_urls"]) == 2


async def test_links_fall_back_to_the_webhook_host(
    api: AsyncClient,
    key: dict[str, str],
    cargo: FlightCargo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.api, "EXTERNAL_PUBLIC_ORIGIN", "")
    monkeypatch.setattr(config.telegram, "WEBHOOK_URL", "https://hook.akbcargo.test")

    response = await api.get(
        "/api/v1/external/flight-cargos",
        params={"client_code": CLIENT},
        headers=key,
    )

    (link, _) = response.json()["items"][0]["photo_urls"]
    assert link.startswith("https://hook.akbcargo.test/api/v1/external/photos/")


async def test_the_api_key_is_still_required_for_the_lists(
    api: AsyncClient, cargo: FlightCargo
) -> None:
    response = await api.get(
        "/api/v1/external/flight-cargos/by-track-code",
        params={"track_code": "TC100"},
    )
    assert response.status_code == 401


async def _links(api: AsyncClient, key: dict[str, str]) -> list[str]:
    response = await api.get(
        "/api/v1/external/flight-cargos",
        params={"client_code": CLIENT},
        headers=key,
    )
    return response.json()["items"][0]["photo_urls"]


async def test_a_signed_link_serves_the_s3_photo_without_the_key(
    api: AsyncClient,
    key: dict[str, str],
    cargo: FlightCargo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    async def fake_download(s3_key: str, max_bytes: int) -> tuple[bytes, str | None]:
        asked.append(s3_key)
        # The stored type is ignored; the bytes decide.
        return JPEG, "text/html"

    monkeypatch.setattr(s3_manager, "download_bytes", fake_download)
    s3_link, _ = await _links(api, key)

    response = await api.get(_path(s3_link))

    assert response.status_code == 200
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "cross-origin"
    assert response.headers["cache-control"].startswith("private, max-age=")
    assert asked == [S3_KEY]


async def test_a_signed_link_serves_the_telegram_photo(
    api: AsyncClient,
    key: dict[str, str],
    cargo: FlightCargo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    async def fake_download(self: TelegramFileService, file_id: str) -> bytes:
        asked.append(file_id)
        return PNG

    monkeypatch.setattr(TelegramFileService, "download_file", fake_download)
    _, telegram_link = await _links(api, key)

    response = await api.get(_path(telegram_link))

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert asked == [TELEGRAM_ID]


async def test_something_that_is_not_a_picture_is_never_served(
    api: AsyncClient,
    key: dict[str, str],
    cargo: FlightCargo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_download(s3_key: str, max_bytes: int) -> tuple[bytes, str | None]:
        return HTML, "image/jpeg"

    monkeypatch.setattr(s3_manager, "download_bytes", fake_download)
    s3_link, _ = await _links(api, key)

    response = await api.get(_path(s3_link))

    assert response.status_code == 404
    assert b"<script>" not in response.content


async def test_an_unreadable_photo_is_a_gateway_error(
    api: AsyncClient,
    key: dict[str, str],
    cargo: FlightCargo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_download(s3_key: str, max_bytes: int) -> None:
        return None

    monkeypatch.setattr(s3_manager, "download_bytes", fake_download)
    s3_link, _ = await _links(api, key)

    response = await api.get(_path(s3_link))

    # 5xx: the partner retries once.
    assert response.status_code == 502


async def test_a_link_cannot_be_turned_to_another_photo(
    api: AsyncClient,
    key: dict[str, str],
    cargo: FlightCargo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_download(s3_key: str, max_bytes: int) -> tuple[bytes, str | None]:
        raise AssertionError("storage must not be reached")

    monkeypatch.setattr(s3_manager, "download_bytes", fake_download)
    s3_link, _ = await _links(api, key)
    query = parse_qs(urlsplit(s3_link).query)
    exp, sig = query["exp"][0], query["sig"][0]
    base = "/api/v1/external/photos"

    for path in (
        f"{base}/{cargo.id}/1?exp={exp}&sig={sig}",
        f"{base}/{cargo.id + 1}/0?exp={exp}&sig={sig}",
        f"{base}/{cargo.id}/0?exp={int(exp) + 900}&sig={sig}",
        f"{base}/{cargo.id}/0?exp={exp}&sig={'0' * 64}",
    ):
        assert (await api.get(path)).status_code == 403, path

    assert (await api.get(f"{base}/{cargo.id}/0?exp={exp}")).status_code == 422
    assert (await api.get(f"{base}/{cargo.id}/0?exp={exp}&sig=xyz")).status_code == 422


async def test_an_expired_link_is_refused(api: AsyncClient, cargo: FlightCargo) -> None:
    exp = int(time.time()) - 1
    sig = photo_signature(cargo.id, 0, exp)

    response = await api.get(
        f"/api/v1/external/photos/{cargo.id}/0", params={"exp": exp, "sig": sig}
    )

    assert response.status_code == 403


async def test_a_signed_link_past_the_photo_list_is_not_found(
    api: AsyncClient, cargo: FlightCargo
) -> None:
    exp = link_expiry()
    for index in (2, 9):
        sig = photo_signature(cargo.id, index, exp)
        response = await api.get(
            f"/api/v1/external/photos/{cargo.id}/{index}",
            params={"exp": exp, "sig": sig},
        )
        assert response.status_code == 404, index


def test_photo_links_skip_the_rate_limiter() -> None:
    from src.api.middleware.rate_limit import EXCLUDED_PATH_PREFIXES

    path = "/api/v1/external/photos/1/0"
    assert any(path.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES)
    # The keyed lists stay limited.
    lists = "/api/v1/external/flight-cargos"
    assert not any(lists.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES)
