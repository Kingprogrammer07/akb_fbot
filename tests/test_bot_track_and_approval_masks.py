"""Bot handlers mint partner masks for flights read from the client's records.

A track-code result and the messages ``payment_approval`` sends to a client
name a flight taken from that client's own rows: a track-code lookup scoped to
its codes, or the payment it submitted for its cargo.  When the partner has no
alias for that flight yet the client must see a newly minted mask - never the
real name and never a placeholder - while staff messages keep the real name.
Minting runs in a transaction of its own, so the handler's session is neither
committed nor rolled back, and a flight the client has no cargo in mints
nothing, because a payment submission can name one.

Handlers are called directly with aiogram objects bound to an ``AsyncMock``
bot, on a fresh PostgreSQL schema, with an in-memory Redis.
"""

import re
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import fakeredis
import fakeredis.aioredis
import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageCaption, SendMessage
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.bot.handlers.admin import payment_approval
from src.bot.handlers.user import track_code
from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.bot.utils.i18n import i18n
from src.config import config
from src.infrastructure.database.models.analytics_event import AnalyticsEvent
from src.infrastructure.database.models.cargo_item import CargoItem
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_flight_alias import PartnerFlightAlias
from src.infrastructure.database.models.static_data import StaticData
from src.infrastructure.services import ClientService
from src.infrastructure.services.cargo_item import CargoItemService

ADMIN_TG = 1
BOT_TG = 123456
STAFF_GROUP_ID = config.telegram.TOLOVLARNI_TASDIQLASH_GROUP_ID
CONFIRMED_CHANNEL_ID = config.telegram.TOLOV_TASDIQLANGAN_CHANNEL_ID

CLIENT_TG = 7101
CLIENT_CODE = "T101"
NEIGHBOUR_TG = 7102
NEIGHBOUR_CODE = "T102"

EARLIER_FLIGHT = "M9700-REAL"
EARLIER_MASK = "TRT4"
# The client's cargo flights that have no alias yet: one arrived, one on the road.
OWN_FLIGHT = "M9731-REAL"
ROAD_FLIGHT = "M9740-REAL"
# Minting continues the partner's counter after EARLIER_MASK.
OWN_MASK = "TRT5"
ROAD_MASK = "TRT6"
# Only the neighbour, a client of the same partner, has cargo in this flight.
NEIGHBOUR_FLIGHT = "M9799-REAL"

REAL_FLIGHTS = (EARLIER_FLIGHT, OWN_FLIGHT, ROAD_FLIGHT, NEIGHBOUR_FLIGHT)
LEAKY_FRAGMENTS = tuple(
    sorted({part for name in REAL_FLIGHTS for part in (name, name.split("-")[0])})
)

UZBEKISTAN_TRACK_CODE = "YT7000000001"
ROAD_TRACK_CODE = "YT7000000002"
NEIGHBOUR_TRACK_CODE = "YT7000000003"

# 2.50 kg x 8.00 USD/kg x 12500 UZS/USD, no extra charge.
FLIGHT_TOTAL = 250000.0
RECEIPT_PHOTO = [
    {"file_id": "receipt", "file_unique_id": "receipt-u", "width": 1, "height": 1}
]
REJECTION_COMMENT = "Chek o'qilmaydi"
HTML_TAG = re.compile(r"</?[a-z]+>")
COUNT_ANALYTICS_EVENTS = select(func.count()).select_from(AnalyticsEvent)


def translate(key: str, **kwargs: object) -> str:
    return i18n.get("uz", key, **kwargs)


def headline(key: str) -> str:
    return translate(key).split("\n", 1)[0]


def flight_line(flight: str) -> str:
    """The flight line of a track-code result, as both templates render it."""
    return f"<b>Reys:</b> {flight}\n"


def full_payment_success(worksheet: str) -> str:
    return translate(
        "payment-approved-full-success",
        worksheet=worksheet,
        paid="250,000.00",
        overpaid=0.0,
        overpaid_fmt="0.00",
    )


# ---------------------------------------------------------------------------
# Fixtures and builders
# ---------------------------------------------------------------------------


@pytest.fixture
def redis_client() -> Redis:
    return fakeredis.aioredis.FakeRedis(
        server=fakeredis.FakeServer(), decode_responses=True
    )


@pytest.fixture
def client_service() -> ClientService:
    return ClientService()


@pytest.fixture(autouse=True)
def offline_google_sheets(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach Google: every flight's sheet lists one track code."""

    async def one_track_code(
        self: GoogleSheetsChecker, flight_name: str, client_code: str | list[str]
    ) -> list[str]:
        return ["TRK-1"]

    monkeypatch.setattr(
        GoogleSheetsChecker, "get_track_codes_by_flight_and_client", one_track_code
    )


def _client(telegram_id: int, code: str) -> Client:
    return Client(
        telegram_id=telegram_id,
        full_name=f"Client {code}",
        phone="+998900000000",
        language_code="uz",
        client_code=code,
        is_logged_in=True,
    )


def _cargo(code: str, flight: str) -> FlightCargo:
    return FlightCargo(
        flight_name=flight,
        client_id=code,
        photo_file_ids="[]",
        weight_kg=Decimal("2.50"),
        price_per_kg=Decimal("8.00"),
        is_sent=True,
        is_sent_web=True,
    )


async def seed_world(session: AsyncSession, redis: Redis) -> None:
    """One partner with an earlier alias, and two of its clients with cargo."""
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
    session.add_all(
        [
            PartnerFlightAlias(
                partner_id=partner.id,
                real_flight_name=EARLIER_FLIGHT,
                mask_flight_name=EARLIER_MASK,
            ),
            _client(CLIENT_TG, CLIENT_CODE),
            _client(NEIGHBOUR_TG, NEIGHBOUR_CODE),
            _cargo(CLIENT_CODE, EARLIER_FLIGHT),
            _cargo(CLIENT_CODE, OWN_FLIGHT),
            _cargo(NEIGHBOUR_CODE, NEIGHBOUR_FLIGHT),
        ]
    )
    await session.commit()
    await redis.set("currency:usd_uzs", "12500")


async def committed_aliases(engine: AsyncEngine) -> list[tuple[str, str]]:
    """Committed ``(real, mask)`` pairs, read outside the handler's session."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(
                PartnerFlightAlias.real_flight_name,
                PartnerFlightAlias.mask_flight_name,
            ).order_by(PartnerFlightAlias.id)
        )
        return [(real, mask) for real, mask in rows]


def _user(telegram_id: int, *, is_bot: bool = False) -> dict[str, object]:
    return {"id": telegram_id, "is_bot": is_bot, "first_name": "Test"}


def _message_payload(
    chat_id: int, sender: dict[str, object], **content: object
) -> dict[str, object]:
    return {
        "message_id": 10,
        "date": datetime.now(timezone.utc),
        "chat": {"id": chat_id, "type": "private" if chat_id > 0 else "supergroup"},
        "from": sender,
        **content,
    }


def make_message(bot: AsyncMock, chat_id: int, sender_id: int, text: str) -> Message:
    return Message.model_validate(
        _message_payload(chat_id, _user(sender_id), text=text), context={"bot": bot}
    )


def make_staff_callback(bot: AsyncMock, data: str, **content: object) -> CallbackQuery:
    """An admin pressing a button under the bot's message in the staff group."""
    return CallbackQuery.model_validate(
        {
            "id": "cb-1",
            "from": _user(ADMIN_TG),
            "chat_instance": "ci-1",
            "data": data,
            "message": _message_payload(
                STAFF_GROUP_ID, _user(BOT_TG, is_bot=True), **content
            ),
        },
        context={"bot": bot},
    )


def make_state(chat_id: int, user_id: int) -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=BOT_TG, chat_id=chat_id, user_id=user_id),
    )


def staff_submission(flight: str, provider: str) -> str:
    """The submission the staff group got, as Telegram hands it back: no HTML."""
    rendered = payment_approval.build_admin_payment_message(
        _=translate,
        client_code=CLIENT_CODE,
        worksheet=flight,
        payment_provider=provider,
        payment_status="paid",
        summa=FLIGHT_TOTAL,
        full_name=f"Client {CLIENT_CODE}",
        phone="+998900000000",
        telegram_id=str(CLIENT_TG),
        vazn="2.50",
        track_codes=["TRK-1"],
    )
    return HTML_TAG.sub("", rendered)


def replies(bot: AsyncMock) -> list[str]:
    """Texts sent as answers to the incoming update (``message.answer``)."""
    return [
        call.args[0].text
        for call in bot.await_args_list
        if isinstance(call.args[0], SendMessage)
    ]


def sent_to(bot: AsyncMock, chat_id: int) -> list[str]:
    """Texts the handler sent to ``chat_id`` through ``bot.send_message``."""
    return [
        call.kwargs["text"]
        for call in bot.send_message.await_args_list
        if call.kwargs["chat_id"] == chat_id
    ]


def assert_no_real_flight_names(texts: list[str]) -> None:
    for text in texts:
        for fragment in LEAKY_FRAGMENTS:
            assert fragment not in text, f"{fragment!r} leaked in {text!r}"


async def send_track_code(session: AsyncSession, text: str) -> list[str]:
    bot = AsyncMock()
    await track_code.process_track_code(
        make_message(bot, CLIENT_TG, CLIENT_TG, text),
        _=translate,
        session=session,
        cargo_service=CargoItemService(),
        state=make_state(CLIENT_TG, CLIENT_TG),
    )
    return replies(bot)


async def reject(
    session: AsyncSession,
    client_service: ClientService,
    flight: str,
    *,
    comment: str | None,
) -> AsyncMock:
    """Reject the client's receipt for ``flight``, with or without a comment."""
    submission = {
        "caption": staff_submission(flight, "click"),
        "photo": RECEIPT_PHOTO,
    }
    bot = AsyncMock()
    if comment is None:
        await payment_approval.reject_payment_callback(
            make_staff_callback(bot, f"reject_payment:{CLIENT_CODE}", **submission),
            _=translate,
            bot=bot,
            session=session,
            client_service=client_service,
        )
        return bot

    state = make_state(STAFF_GROUP_ID, ADMIN_TG)
    await payment_approval.reject_payment_with_comment_callback(
        make_staff_callback(bot, f"reject_payment_comment:{CLIENT_CODE}", **submission),
        _=translate,
        state=state,
    )
    assert (await state.get_data())["reject_flight_name"] == flight
    await payment_approval.rejection_comment_received(
        make_message(bot, STAFF_GROUP_ID, ADMIN_TG, comment),
        _=translate,
        state=state,
        bot=bot,
        session=session,
        client_service=client_service,
    )
    return bot


# ---------------------------------------------------------------------------
# track_code.py
# ---------------------------------------------------------------------------


async def test_track_code_results_show_masks_minted_for_the_clients_own_flights(
    db_engine: AsyncEngine, db_session: AsyncSession, redis_client: Redis
) -> None:
    await seed_world(db_session, redis_client)
    db_session.add_all(
        [
            # A fixed rate keeps get_usd_rate away from the currency API.
            StaticData(id=1, use_custom_rate=True, custom_usd_rate=12500.0),
            CargoItem(
                track_code=UZBEKISTAN_TRACK_CODE,
                client_id=CLIENT_CODE,
                flight_name=OWN_FLIGHT,
                checkin_status="post",
                weight_kg="2.50",
                quantity="1",
                post_checkin_date="2026-09-05",
            ),
            CargoItem(
                track_code=ROAD_TRACK_CODE,
                client_id=CLIENT_CODE,
                flight_name=ROAD_FLIGHT,
                checkin_status="pre",
                weight_kg="1.20",
                quantity="2",
                item_name_ru="Kurtka",
                box_number="B-7",
                pre_checkin_date="2026-09-08",
            ),
        ]
    )
    await db_session.commit()

    arrived = await send_track_code(db_session, UZBEKISTAN_TRACK_CODE)
    on_the_road = await send_track_code(db_session, ROAD_TRACK_CODE)
    arrived_again = await send_track_code(db_session, UZBEKISTAN_TRACK_CODE)

    search_again = translate("user-track-check-search-again")
    assert len(arrived) == 2 and arrived[1] == search_again
    assert arrived[0].startswith(headline("user-track-check-uzbekistan-info"))
    assert flight_line(OWN_MASK) in arrived[0]
    assert len(on_the_road) == 2 and on_the_road[1] == search_again
    assert on_the_road[0].startswith(headline("user-track-check-china-info"))
    assert flight_line(ROAD_MASK) in on_the_road[0]
    # The next lookup reuses the alias instead of minting another one.
    assert arrived_again == arrived
    assert_no_real_flight_names([*arrived, *on_the_road])
    assert await committed_aliases(db_engine) == [
        (EARLIER_FLIGHT, EARLIER_MASK),
        (OWN_FLIGHT, OWN_MASK),
        (ROAD_FLIGHT, ROAD_MASK),
    ]


async def test_another_clients_track_code_mints_nothing(
    db_engine: AsyncEngine, db_session: AsyncSession, redis_client: Redis
) -> None:
    await seed_world(db_session, redis_client)
    db_session.add(
        CargoItem(
            track_code=NEIGHBOUR_TRACK_CODE,
            client_id=NEIGHBOUR_CODE,
            flight_name=NEIGHBOUR_FLIGHT,
            checkin_status="post",
        )
    )
    await db_session.commit()

    texts = await send_track_code(db_session, NEIGHBOUR_TRACK_CODE)

    assert texts == [
        translate("user-track-check-not-found", track_code=NEIGHBOUR_TRACK_CODE)
        + "\n\n"
        + translate("user-track-check-search-again")
    ]
    assert await committed_aliases(db_engine) == [(EARLIER_FLIGHT, EARLIER_MASK)]


# ---------------------------------------------------------------------------
# payment_approval.py: approvals
# ---------------------------------------------------------------------------


async def test_online_approval_shows_the_client_a_minted_mask_and_staff_the_real_name(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
) -> None:
    await seed_world(db_session, redis_client)
    state = make_state(STAFF_GROUP_ID, ADMIN_TG)

    await payment_approval.approve_payment_callback(
        make_staff_callback(
            AsyncMock(),
            f"approve_payment:{CLIENT_CODE}:{OWN_FLIGHT}",
            caption=staff_submission(OWN_FLIGHT, "click"),
            photo=RECEIPT_PHOTO,
        ),
        _=translate,
        session=db_session,
        client_service=client_service,
        state=state,
        redis=redis_client,
    )
    assert (await state.get_data())["approval_expected_amount"] == FLIGHT_TOTAL

    bot = AsyncMock()
    await payment_approval.full_pay_confirmed_callback(
        make_staff_callback(
            bot, f"full_pay_approve:{CLIENT_CODE}:{OWN_FLIGHT}", text="hint"
        ),
        _=translate,
        session=db_session,
        client_service=client_service,
        transaction_service=None,
        state=state,
        bot=bot,
        redis=redis_client,
    )

    to_client = sent_to(bot, CLIENT_TG)
    assert to_client == [
        translate("payment-approved-user", worksheet=OWN_MASK, summa="250000.00"),
        full_payment_success(OWN_MASK),
    ]
    assert_no_real_flight_names(to_client)
    [channel_post] = sent_to(bot, CONFIRMED_CHANNEL_ID)
    assert f"<b>Reys:</b> {OWN_FLIGHT}\n" in channel_post
    assert await committed_aliases(db_engine) == [
        (EARLIER_FLIGHT, EARLIER_MASK),
        (OWN_FLIGHT, OWN_MASK),
    ]


async def test_cash_approval_shows_the_client_a_minted_mask_and_staff_the_real_name(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
) -> None:
    await seed_world(db_session, redis_client)
    state = make_state(STAFF_GROUP_ID, ADMIN_TG)

    await payment_approval.cash_payment_confirmed_callback(
        make_staff_callback(
            AsyncMock(),
            f"cash_payment_confirmed:{CLIENT_CODE}:{OWN_FLIGHT}",
            text=staff_submission(OWN_FLIGHT, "cash"),
        ),
        _=translate,
        session=db_session,
        client_service=client_service,
        state=state,
        redis=redis_client,
    )
    assert (await state.get_data())["cash_expected_amount"] == FLIGHT_TOTAL

    bot = AsyncMock()
    await payment_approval.cash_payment_amount_received(
        make_message(bot, STAFF_GROUP_ID, ADMIN_TG, "250000"),
        _=translate,
        session=db_session,
        client_service=client_service,
        transaction_service=None,
        state=state,
        bot=bot,
        redis=redis_client,
    )

    to_client = sent_to(bot, CLIENT_TG)
    assert to_client == [
        translate("payment-cash-confirmed-user"),
        full_payment_success(OWN_MASK),
    ]
    assert_no_real_flight_names(to_client)
    [channel_post] = sent_to(bot, CONFIRMED_CHANNEL_ID)
    assert f"<b>Reys:</b> {OWN_FLIGHT}\n" in channel_post
    [staff_stamp] = sent_to(bot, STAFF_GROUP_ID)
    assert OWN_FLIGHT in staff_stamp
    assert await committed_aliases(db_engine) == [
        (EARLIER_FLIGHT, EARLIER_MASK),
        (OWN_FLIGHT, OWN_MASK),
    ]


# ---------------------------------------------------------------------------
# payment_approval.py: rejections
# ---------------------------------------------------------------------------


async def test_rejection_shows_the_client_a_minted_mask_and_staff_the_real_name(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
) -> None:
    await seed_world(db_session, redis_client)

    bot = await reject(db_session, client_service, OWN_FLIGHT, comment=None)

    [to_client] = sent_to(bot, CLIENT_TG)
    assert f"(Reys: {OWN_MASK}) rad etildi." in to_client
    assert_no_real_flight_names([to_client])
    [staff_edit] = [
        call.args[0]
        for call in bot.await_args_list
        if isinstance(call.args[0], EditMessageCaption)
    ]
    assert f"Reys: {OWN_FLIGHT}\n" in staff_edit.caption
    assert await committed_aliases(db_engine) == [
        (EARLIER_FLIGHT, EARLIER_MASK),
        (OWN_FLIGHT, OWN_MASK),
    ]


async def test_rejection_with_a_comment_shows_the_client_a_minted_mask(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
) -> None:
    await seed_world(db_session, redis_client)

    bot = await reject(
        db_session, client_service, OWN_FLIGHT, comment=REJECTION_COMMENT
    )

    [to_client] = sent_to(bot, CLIENT_TG)
    assert f"(Reys: {OWN_MASK}) rad etildi." in to_client
    assert to_client.endswith(REJECTION_COMMENT)
    assert_no_real_flight_names([to_client])
    assert await committed_aliases(db_engine) == [
        (EARLIER_FLIGHT, EARLIER_MASK),
        (OWN_FLIGHT, OWN_MASK),
    ]


async def test_minting_during_a_rejection_leaves_the_handlers_session_alone(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
) -> None:
    await seed_world(db_session, redis_client)
    # Rejection handlers never commit: this write must stay pending in their session.
    db_session.add(AnalyticsEvent(event_type="uncommitted-handler-write", user_id=1))
    await db_session.flush()

    bot = await reject(db_session, client_service, OWN_FLIGHT, comment=None)

    assert f"(Reys: {OWN_MASK}) rad etildi." in sent_to(bot, CLIENT_TG)[0]
    # The alias is committed on its own ...
    assert await committed_aliases(db_engine) == [
        (EARLIER_FLIGHT, EARLIER_MASK),
        (OWN_FLIGHT, OWN_MASK),
    ]
    # ... while the handler's write is neither committed nor rolled back.
    assert db_session.in_transaction()
    assert await db_session.scalar(COUNT_ANALYTICS_EVENTS) == 1
    async with db_engine.connect() as conn:
        assert await conn.scalar(COUNT_ANALYTICS_EVENTS) == 0

    await db_session.rollback()
    assert await db_session.scalar(COUNT_ANALYTICS_EVENTS) == 0
    assert await committed_aliases(db_engine) == [
        (EARLIER_FLIGHT, EARLIER_MASK),
        (OWN_FLIGHT, OWN_MASK),
    ]


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        (None, translate("payment-rejected-user")),
        (
            REJECTION_COMMENT,
            translate("payment-rejected-with-comment", comment=REJECTION_COMMENT),
        ),
    ],
)
async def test_rejecting_a_flight_without_the_clients_cargo_mints_nothing(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
    comment: str | None,
    expected: str,
) -> None:
    """A submission can name a flight the client has no cargo in; nothing is minted."""
    await seed_world(db_session, redis_client)

    bot = await reject(db_session, client_service, NEIGHBOUR_FLIGHT, comment=comment)

    assert sent_to(bot, CLIENT_TG) == [expected]
    assert await committed_aliases(db_engine) == [(EARLIER_FLIGHT, EARLIER_MASK)]


@pytest.mark.parametrize(
    ("owned_flight", "mask", "aliases"),
    [
        pytest.param(
            OWN_FLIGHT,
            OWN_MASK,
            [(EARLIER_FLIGHT, EARLIER_MASK), (OWN_FLIGHT, OWN_MASK)],
            id="unaliased-flight",
        ),
        pytest.param(
            EARLIER_FLIGHT,
            EARLIER_MASK,
            [(EARLIER_FLIGHT, EARLIER_MASK)],
            id="aliased-flight",
        ),
    ],
)
async def test_a_case_variant_of_an_owned_flight_never_becomes_an_alias(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
    owned_flight: str,
    mask: str,
    aliases: list[tuple[str, str]],
) -> None:
    """A submission may spell the client's flight in another case.

    Cargo lookups ignore case, so the client still owns the flight, but aliases
    are keyed by the exact real name: the client sees the flight's own mask,
    minted under the name ``flight_cargos`` stores, and the submitted spelling
    never becomes an alias.
    """
    await seed_world(db_session, redis_client)

    bot = await reject(db_session, client_service, owned_flight.lower(), comment=None)

    assert f"(Reys: {mask}) rad etildi." in sent_to(bot, CLIENT_TG)[0]
    assert await committed_aliases(db_engine) == aliases
