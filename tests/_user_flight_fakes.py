"""Seed builders and Telegram fakes for the user flight handler tests.

Shared by ``test_user_flight_keyboards`` and ``test_user_flight_minting``; not
collected by pytest because the module name does not start with ``test_``.

Handlers are called directly with aiogram objects bound to an ``AsyncMock``
bot, on a fresh PostgreSQL schema, with an in-memory Redis whose primed
``sheets_data`` keys stand in for Google Sheets.  Pytest fixtures stay in the
test modules (an imported fixture reads as an unused, redefined import), which
build them from the factories here.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import fakeredis
import fakeredis.aioredis
import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.utils.flight_token import client_token_scope
from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.bot.utils.i18n import i18n
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_flight_alias import PartnerFlightAlias
from src.infrastructure.database.models.payment_card import PaymentCard
from src.infrastructure.services import ClientService

PARTNER_TG = 7001
PARTNER_CODE = "T101"
LONE_TG = 7002
LONE_CODE = "Z900"
UNKNOWN_TG = 7999

MASKED_FLIGHT = "M9731-REAL"
MASK = "TRT5"
UNMASKED_FLIGHT = "M9732-REAL"
# The alias a render mints for the first flight of partner TRT without one.
MINTED_MASK = "TRT6"
# A sheet flight of the partner client with no sent cargo (no photo report).
UNREPORTED_FLIGHT = "M9733-REAL"
LONE_FLIGHT_A = "Q4402-REAL"
LONE_FLIGHT_B = "Q4403-REAL"
# Sheet titles and flight_cargos rows can carry surrounding whitespace.
PADDED_FLIGHT = "W7700-REAL "

REAL_FLIGHTS = (
    MASKED_FLIGHT,
    UNMASKED_FLIGHT,
    UNREPORTED_FLIGHT,
    LONE_FLIGHT_A,
    LONE_FLIGHT_B,
    PADDED_FLIGHT,
)
LEAKY_FRAGMENTS = tuple(
    sorted(
        {part for name in REAL_FLIGHTS for part in (name.strip(), name.split("-")[0])}
    )
)
FORGED_TOKEN = "0" * 16
# 2.50 kg x 8.00 USD/kg x 12500 UZS/USD, no extra charge.
CARGO_TOTAL = "250,000.00"
TELEGRAM_CALLBACK_DATA_LIMIT = 64


def translate(key: str, **kwargs: object) -> str:
    return i18n.get("uz", key, **kwargs)


ERROR_TEXT = translate("error-occurred")


# ---------------------------------------------------------------------------
# Fixture factories
# ---------------------------------------------------------------------------


def fake_redis() -> Redis:
    return fakeredis.aioredis.FakeRedis(
        server=fakeredis.FakeServer(), decode_responses=True
    )


def keep_google_sheets_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach Google: sheet rows come from the primed Redis cache."""

    async def no_track_codes(
        self: GoogleSheetsChecker, flight_name: str, client_code: str | list[str]
    ) -> list[str]:
        return []

    async def not_found(
        self: GoogleSheetsChecker, client_code: str | list[str], reverse: bool = False
    ) -> dict[str, object]:
        return {"found": False, "matches": []}

    monkeypatch.setattr(
        GoogleSheetsChecker, "get_track_codes_by_flight_and_client", no_track_codes
    )
    monkeypatch.setattr(GoogleSheetsChecker, "find_client_group", not_found)


# ---------------------------------------------------------------------------
# Seed builders
# ---------------------------------------------------------------------------


def make_client(telegram_id: int, code: str) -> Client:
    return Client(
        telegram_id=telegram_id,
        full_name=f"Client {code}",
        phone="+998900000000",
        language_code="uz",
        region="toshkent_city",
        district="chilonzor",
        address="Test street 1",
        client_code=code,
        is_logged_in=True,
    )


def make_cargo(code: str, flight: str) -> FlightCargo:
    return FlightCargo(
        flight_name=flight,
        client_id=code,
        photo_file_ids="[]",
        weight_kg=Decimal("2.50"),
        price_per_kg=Decimal("8.00"),
        is_sent=True,
        is_sent_web=False,
    )


def make_transaction(
    telegram_id: int, code: str, flight: str, *, status: str, remaining: Decimal
) -> ClientTransaction:
    total = Decimal("250000.00")
    return ClientTransaction(
        telegram_id=telegram_id,
        client_code=code,
        qator_raqami=0,
        reys=flight,
        summa=total,
        vazn="2.50",
        payment_type="online",
        payment_status=status,
        paid_amount=total - remaining,
        total_amount=total,
        remaining_amount=remaining,
        payment_balance_difference=Decimal("0"),
        is_taken_away=False,
    )


def make_active_card() -> PaymentCard:
    return PaymentCard(
        full_name="Card Owner", card_number="8600123412341234", is_active=True
    )


async def prime_sheets(redis: Redis, code: str, flights: list[str]) -> None:
    matches = [
        {"flight_name": flight, "row_number": row, "track_codes": ["TRK-1"]}
        for row, flight in enumerate(flights, start=2)
    ]
    await redis.set(
        f"sheets_data:{code}", json.dumps({"found": True, "matches": matches})
    )


async def seed_world(session: AsyncSession, redis: Redis) -> None:
    """A partner client (one aliased flight, one not) and a no-partner client."""
    partner = Partner(
        code="TRT",
        display_name="Triton",
        prefix="T",
        group_chat_id=-100500,
        is_dm_partner=False,
        is_active=True,
    )
    session.add(partner)
    await session.flush()
    session.add(
        PartnerFlightAlias(
            partner_id=partner.id,
            real_flight_name=MASKED_FLIGHT,
            mask_flight_name=MASK,
        )
    )
    session.add_all(
        [make_client(PARTNER_TG, PARTNER_CODE), make_client(LONE_TG, LONE_CODE)]
    )
    owned = (
        (PARTNER_CODE, (MASKED_FLIGHT, UNMASKED_FLIGHT)),
        (LONE_CODE, (LONE_FLIGHT_A, LONE_FLIGHT_B)),
    )
    for code, flights in owned:
        session.add_all([make_cargo(code, flight) for flight in flights])
    await session.commit()

    await redis.set("currency:usd_uzs", "12500")
    await prime_sheets(redis, PARTNER_CODE, [MASKED_FLIGHT, UNMASKED_FLIGHT])
    await prime_sheets(redis, LONE_CODE, [LONE_FLIGHT_A, LONE_FLIGHT_B])


async def token_scope(
    session: AsyncSession, client_service: ClientService, telegram_id: int
) -> str:
    client = await client_service.get_client(telegram_id, session)
    return client_token_scope(client.id)


# ---------------------------------------------------------------------------
# Telegram objects and captured output
# ---------------------------------------------------------------------------


def _user(telegram_id: int) -> dict[str, object]:
    return {"id": telegram_id, "is_bot": False, "first_name": "Test"}


def _message_payload(telegram_id: int, text: str) -> dict[str, object]:
    return {
        "message_id": 10,
        "date": datetime.now(timezone.utc),
        "chat": {"id": telegram_id, "type": "private"},
        "from": _user(telegram_id),
        "text": text,
    }


def make_message(bot: AsyncMock, telegram_id: int, text: str = "menu") -> Message:
    return Message.model_validate(
        _message_payload(telegram_id, text), context={"bot": bot}
    )


def make_callback(bot: AsyncMock, telegram_id: int, data: str) -> CallbackQuery:
    return CallbackQuery.model_validate(
        {
            "id": "cb-1",
            "from": _user(telegram_id),
            "chat_instance": "ci-1",
            "data": data,
            "message": _message_payload(telegram_id, "previous screen"),
        },
        context={"bot": bot},
    )


def make_state(telegram_id: int) -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=telegram_id, user_id=telegram_id),
    )


@dataclass
class Output:
    """Everything a handler sent to the user through the mocked bot.

    Only methods awaited on the bot itself are captured; a handler's
    ``bot.send_message`` to an admin group is a separate child mock.
    """

    texts: list[str] = field(default_factory=list)
    # Inline button labels, in order; each is also one of ``texts``.
    buttons: list[str] = field(default_factory=list)
    callback_data: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    screens: int = 0

    def callbacks(self, prefix: str) -> list[str]:
        return [data for data in self.callback_data if data.startswith(prefix)]

    def assert_no_real_flight_names(self) -> None:
        for value in (*self.texts, *self.callback_data, *self.alerts):
            for fragment in LEAKY_FRAGMENTS:
                assert fragment not in value, f"{fragment!r} leaked in {value!r}"


def capture(bot: AsyncMock) -> Output:
    output = Output()
    for call in bot.await_args_list:
        method = call.args[0]
        if isinstance(method, AnswerCallbackQuery):
            if method.text:
                output.alerts.append(method.text)
            continue
        output.screens += 1
        for attribute in ("text", "caption"):
            value = getattr(method, attribute, None)
            if isinstance(value, str):
                output.texts.append(value)
        markup = getattr(method, "reply_markup", None)
        if isinstance(markup, InlineKeyboardMarkup):
            for row in markup.inline_keyboard:
                for button in row:
                    output.texts.append(button.text)
                    output.buttons.append(button.text)
                    if button.callback_data is not None:
                        size = len(button.callback_data.encode("utf-8"))
                        assert size <= TELEGRAM_CALLBACK_DATA_LIMIT, (
                            button.callback_data
                        )
                        output.callback_data.append(button.callback_data)
    for call in bot.answer_callback_query.await_args_list:
        text = call.kwargs.get("text")
        if text:
            output.alerts.append(text)
    return output


def callback_answers(bot: AsyncMock) -> list[AnswerCallbackQuery]:
    return [
        call.args[0]
        for call in bot.await_args_list
        if isinstance(call.args[0], AnswerCallbackQuery)
    ]


def assert_rejected(output: Output) -> None:
    assert output.screens == 0
    assert output.alerts == [ERROR_TEXT]
