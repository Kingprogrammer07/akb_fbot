"""``POST /webhook`` only dispatches requests that carry Telegram's secret token.

The endpoint is public and the bot's admin filters trust
``update.from_user.id``, so a JSON body posted by anyone who knows an admin's
Telegram id used to run as that admin (payment approvals and the like).  The
lifespan now registers a secret derived from the bot token with
``setWebhook``; Telegram echoes it in ``X-Telegram-Bot-Api-Secret-Token`` and
the handler refuses every other request before reading the body.

A refusal is logged at WARNING, never ERROR (ERROR records are forwarded to the
ops Telegram channel), and neither the header value nor the body is logged.

The HTTP tests drive the real ``src.bot.bot.app`` through httpx without its
lifespan, with the module's ``bot`` / ``dp`` globals replaced by fakes.
"""

import hashlib
import hmac
import logging
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from aiogram.types import Update
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.bot import bot as bot_module
from src.bot.utils.webhook_secret import webhook_secret_token
from src.infrastructure.database import seeders

# Spelled out rather than imported: the name is Telegram's contract, not ours.
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
UPDATE_ID = 424242
WEBHOOK_URL = "https://bot.example.test"

HeaderFactory = Callable[[str], dict[str, str | bytes]]


class FakeBot:
    """Stands in for aiogram's ``Bot``; records ``set_webhook`` keyword arguments."""

    def __init__(self) -> None:
        self.set_webhook_calls: list[dict[str, object]] = []

    async def set_webhook(self, **kwargs: object) -> bool:
        self.set_webhook_calls.append(kwargs)
        return True


class FakeDispatcher:
    """Stands in for aiogram's ``Dispatcher``; records every update it is fed."""

    def __init__(self) -> None:
        self.fed: list[tuple[object, Update]] = []

    async def feed_update(self, bot: object, update: Update) -> None:
        self.fed.append((bot, update))


class FakeRedisClient:
    async def get_redis(self) -> object:
        return object()


class FakeDatabaseClient:
    @asynccontextmanager
    async def session_factory(self) -> AsyncIterator[object]:
        yield object()


def _update_body(text: str) -> dict[str, object]:
    """A private message from Telegram user 1, an admin in the test config."""
    return {
        "update_id": UPDATE_ID,
        "message": {
            "message_id": 7,
            "date": 1_700_000_000,
            "chat": {"id": 1, "type": "private"},
            "from": {"id": 1, "is_bot": False, "first_name": "Admin"},
            "text": text,
        },
    }


def _one_char_off(secret: str) -> str:
    return secret[:-1] + ("1" if secret.endswith("0") else "0")


@pytest.fixture
def expected_secret() -> str:
    return webhook_secret_token(bot_module.config.telegram.TOKEN.get_secret_value())


@pytest.fixture
def fake_bot(monkeypatch: pytest.MonkeyPatch) -> FakeBot:
    fake = FakeBot()
    monkeypatch.setattr(bot_module, "bot", fake)
    return fake


@pytest.fixture
def fake_dp(monkeypatch: pytest.MonkeyPatch) -> FakeDispatcher:
    fake = FakeDispatcher()
    monkeypatch.setattr(bot_module, "dp", fake)
    return fake


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """The production app; httpx's ASGITransport sends no lifespan events."""
    async with AsyncClient(
        transport=ASGITransport(app=bot_module.app), base_url="http://test"
    ) as http:
        yield http


def test_secret_is_a_deterministic_64_char_lowercase_hex_digest() -> None:
    token = "123456:ABC-def_GHI"
    secret = webhook_secret_token(token)

    assert secret == webhook_secret_token(token)
    assert re.fullmatch(r"[0-9a-f]{64}", secret)
    assert (
        secret
        == hmac.new(
            token.encode(), b"akb:telegram-webhook-secret:v1", hashlib.sha256
        ).hexdigest()
    )


def test_secret_differs_for_different_bot_tokens() -> None:
    assert webhook_secret_token("123456:first-token") != webhook_secret_token(
        "123456:second-token"
    )


@pytest.mark.usefixtures("fake_bot")
@pytest.mark.parametrize(
    "forged_headers",
    [
        pytest.param(lambda secret: {}, id="missing"),
        pytest.param(lambda secret: {SECRET_HEADER: ""}, id="empty"),
        pytest.param(lambda secret: {SECRET_HEADER: "wrong-secret"}, id="wrong"),
        pytest.param(
            lambda secret: {SECRET_HEADER: _one_char_off(secret)}, id="one-char-off"
        ),
        # compare_digest raises TypeError on a non-ASCII str: must be 403, not 500.
        pytest.param(lambda secret: {SECRET_HEADER: b"\xe9" * 64}, id="non-ascii"),
    ],
)
async def test_request_without_the_secret_is_refused_and_never_dispatched(
    client: AsyncClient,
    fake_dp: FakeDispatcher,
    expected_secret: str,
    forged_headers: HeaderFactory,
) -> None:
    response = await client.post(
        "/webhook",
        json=_update_body("/start"),
        headers=forged_headers(expected_secret),
    )

    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden"}
    assert fake_dp.fed == []


async def test_secret_is_checked_before_the_bot_ready_check(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bot_module, "bot", None)
    monkeypatch.setattr(bot_module, "dp", None)

    response = await client.post("/webhook", json=_update_body("/start"))

    assert response.status_code == 403


@pytest.mark.usefixtures("fake_bot")
async def test_forged_body_is_never_parsed(
    client: AsyncClient,
    fake_dp: FakeDispatcher,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            "/webhook",
            content=b'{"update_id": not-json',
            headers={"Content-Type": "application/json", SECRET_HEADER: "wrong"},
        )

    assert response.status_code == 403
    assert fake_dp.fed == []
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


@pytest.mark.usefixtures("fake_bot", "fake_dp")
async def test_refusal_is_one_warning_that_logs_neither_header_nor_body(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    forged_secret = "f0rged-secret-" * 4
    body_marker = "approve-payment-forged-marker"

    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            "/webhook",
            json=_update_body(body_marker),
            headers={SECRET_HEADER: forged_secret},
        )

    assert response.status_code == 403
    refusals = [r for r in caplog.records if r.name == bot_module.__name__]
    assert [r.levelno for r in refusals] == [logging.WARNING]
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
    for record in caplog.records:
        logged = f"{record.getMessage()} {record.exc_text or ''}"
        assert forged_secret not in logged
        assert body_marker not in logged


async def test_update_with_the_secret_is_fed_exactly_once(
    client: AsyncClient,
    fake_bot: FakeBot,
    fake_dp: FakeDispatcher,
    expected_secret: str,
) -> None:
    response = await client.post(
        "/webhook",
        json=_update_body("/start"),
        headers={SECRET_HEADER: expected_secret},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(fake_dp.fed) == 1
    fed_bot, fed_update = fake_dp.fed[0]
    assert fed_bot is fake_bot
    assert isinstance(fed_update, Update)
    assert fed_update.update_id == UPDATE_ID
    assert fed_update.message is not None
    assert fed_update.message.text == "/start"


async def test_correct_secret_still_gets_503_until_the_bot_is_ready(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, expected_secret: str
) -> None:
    monkeypatch.setattr(bot_module, "bot", None)
    monkeypatch.setattr(bot_module, "dp", None)

    response = await client.post(
        "/webhook",
        json=_update_body("/start"),
        headers={SECRET_HEADER: expected_secret},
    )

    assert response.status_code == 503
    assert response.json() == {"error": "Bot not initialized"}


async def test_lifespan_registers_the_secret_that_the_handler_accepts(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, expected_secret: str
) -> None:
    registered_bot = FakeBot()
    dispatcher = FakeDispatcher()

    async def fake_setup_bot() -> tuple[
        FakeBot, FakeDispatcher, FakeRedisClient, FakeDatabaseClient
    ]:
        return registered_bot, dispatcher, FakeRedisClient(), FakeDatabaseClient()

    async def skip_seeding(session: object) -> None:
        return None

    async def skip_shutdown() -> None:
        return None

    # lifespan rebinds these module globals; monkeypatch restores them after.
    for name in ("bot", "dp", "redis_client", "db_client"):
        monkeypatch.setattr(bot_module, name, None)
    monkeypatch.setattr(bot_module, "setup_bot", fake_setup_bot)
    monkeypatch.setattr(bot_module, "shutdown_bot", skip_shutdown)
    monkeypatch.setattr(seeders, "seed_permissions", skip_seeding)
    monkeypatch.setattr(seeders, "seed_roles", skip_seeding)
    monkeypatch.setattr(bot_module.config.telegram, "WEBHOOK_URL", WEBHOOK_URL)

    # A throwaway app absorbs the lifespan's app.state writes.
    async with bot_module.lifespan(FastAPI()):
        assert registered_bot.set_webhook_calls == [
            {
                "url": f"{WEBHOOK_URL}/webhook",
                "drop_pending_updates": True,
                "secret_token": expected_secret,
            }
        ]
        registered_secret = registered_bot.set_webhook_calls[0]["secret_token"]
        assert isinstance(registered_secret, str)

        # What Telegram is told to send is exactly what the handler accepts.
        response = await client.post(
            "/webhook",
            json=_update_body("/start"),
            headers={SECRET_HEADER: registered_secret},
        )

    assert response.status_code == 200
    assert len(dispatcher.fed) == 1


class UnreachableTelegramBot(FakeBot):
    """A ``Bot`` whose ``setWebhook`` call fails, as when Telegram is unreachable."""

    async def set_webhook(self, **kwargs: object) -> bool:
        self.set_webhook_calls.append(kwargs)
        raise RuntimeError("Cannot connect to host api.telegram.org:443")


async def test_failed_webhook_registration_is_logged_as_an_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A failed registration leaves Telegram posting without the secret.

    Every update is then refused and the bot goes silent, so the failure is an
    ERROR (forwarded to the ops channel), while the API keeps starting.
    """
    unreachable = UnreachableTelegramBot()

    async def fake_setup_bot() -> tuple[
        FakeBot, FakeDispatcher, FakeRedisClient, FakeDatabaseClient
    ]:
        return unreachable, FakeDispatcher(), FakeRedisClient(), FakeDatabaseClient()

    async def skip_seeding(session: object) -> None:
        return None

    async def skip_shutdown() -> None:
        return None

    for name in ("bot", "dp", "redis_client", "db_client"):
        monkeypatch.setattr(bot_module, name, None)
    monkeypatch.setattr(bot_module, "setup_bot", fake_setup_bot)
    monkeypatch.setattr(bot_module, "shutdown_bot", skip_shutdown)
    monkeypatch.setattr(seeders, "seed_permissions", skip_seeding)
    monkeypatch.setattr(seeders, "seed_roles", skip_seeding)
    monkeypatch.setattr(bot_module.config.telegram, "WEBHOOK_URL", WEBHOOK_URL)

    with caplog.at_level(logging.DEBUG):
        async with bot_module.lifespan(FastAPI()):
            pass

    assert len(unreachable.set_webhook_calls) == bot_module.WEBHOOK_SETUP_ATTEMPTS
    failures = [r for r in caplog.records if "Failed to set webhook" in r.getMessage()]
    assert [r.levelno for r in failures] == [logging.ERROR]


class FlakyTelegramBot(FakeBot):
    """A ``Bot`` whose ``setWebhook`` fails once, as on a blip at boot."""

    async def set_webhook(self, **kwargs: object) -> bool:
        self.set_webhook_calls.append(kwargs)
        if len(self.set_webhook_calls) == 1:
            raise RuntimeError("Cannot connect to host api.telegram.org:443")
        return True


async def test_webhook_registration_is_retried_before_giving_up(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One failed call must not leave the bot silent until someone restarts it."""
    flaky = FlakyTelegramBot()

    async def fake_setup_bot() -> tuple[
        FakeBot, FakeDispatcher, FakeRedisClient, FakeDatabaseClient
    ]:
        return flaky, FakeDispatcher(), FakeRedisClient(), FakeDatabaseClient()

    async def skip_seeding(session: object) -> None:
        return None

    async def skip_shutdown() -> None:
        return None

    for name in ("bot", "dp", "redis_client", "db_client"):
        monkeypatch.setattr(bot_module, name, None)
    monkeypatch.setattr(bot_module, "setup_bot", fake_setup_bot)
    monkeypatch.setattr(bot_module, "shutdown_bot", skip_shutdown)
    monkeypatch.setattr(seeders, "seed_permissions", skip_seeding)
    monkeypatch.setattr(seeders, "seed_roles", skip_seeding)
    monkeypatch.setattr(bot_module.config.telegram, "WEBHOOK_URL", WEBHOOK_URL)
    monkeypatch.setattr(bot_module, "WEBHOOK_SETUP_RETRY_SECONDS", 0)

    with caplog.at_level(logging.DEBUG):
        async with bot_module.lifespan(FastAPI()):
            pass

    assert len(flaky.set_webhook_calls) == 2
    assert flaky.set_webhook_calls[1]["secret_token"] == webhook_secret_token(
        bot_module.config.telegram.TOKEN.get_secret_value()
    )
    assert any("Webhook set to" in r.getMessage() for r in caplog.records)
    assert not [
        r for r in caplog.records if "Failed to set webhook" in r.getMessage()
    ]
