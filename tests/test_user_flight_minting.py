"""Partner clients see a minted mask for every flight from their own records.

Product rule: every flight an end user sees shows a partner mask, never the
real name and never a placeholder.  The user handlers render flights read from
the client's own sheet rows, expected cargo and transactions, or FSM data
derived from them, so a flight without an alias gets one minted when it is
first rendered.

Every surface is driven from a state where the rendered flight has no alias,
and every rendering handler call runs with an uncommitted change staged on the
handler's own session, which must still be pending afterwards: the alias is
committed in a transaction of its own.

The single-answer contracts of the UZPOST wallet-only submit, the delivery
"done" button and the payment wallet toggle are pinned here as well.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.methods import EditMessageText, SendMessage, TelegramMethod
from redis.asyncio import Redis
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.bot.handlers.user import delivery_request, info, make_payment, profile
from src.bot.utils.flight_token import flight_token
from src.infrastructure.database.dao.delivery_request import DeliveryRequestDAO
from src.infrastructure.database.models.delivery_request import DeliveryRequest
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.partner_flight_alias import PartnerFlightAlias
from src.infrastructure.services import ClientService
from tests._user_flight_fakes import (
    ERROR_TEXT,
    LONE_TG,
    MASK,
    MASKED_FLIGHT,
    MINTED_MASK,
    PARTNER_CODE,
    PARTNER_TG,
    UNKNOWN_TG,
    UNMASKED_FLIGHT,
    UNREPORTED_FLIGHT,
    Output,
    assert_rejected,
    callback_answers,
    capture,
    fake_redis,
    keep_google_sheets_offline,
    make_active_card,
    make_callback,
    make_message,
    make_state,
    make_transaction,
    prime_sheets,
    seed_world,
    token_scope,
    translate,
)

STAGED_CODE = "S000"
STAGED_FLIGHT = "S0001-STAGED"
PREVIOUSLY_SHOWN_CARD_ID = -1

Render = Callable[[AsyncMock], Awaitable[object]]


@pytest.fixture
def redis_client() -> Redis:
    return fake_redis()


@pytest.fixture
def client_service() -> ClientService:
    return ClientService()


@pytest.fixture(autouse=True)
def offline_google_sheets(monkeypatch: pytest.MonkeyPatch) -> None:
    keep_google_sheets_offline(monkeypatch)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def own_session_untouched(
    engine: AsyncEngine, session: AsyncSession
) -> AsyncIterator[None]:
    """Stage an uncommitted row on ``session``; it must still be pending after.

    A commit would make the row visible to another connection, and a rollback
    would expunge it from the session.
    """
    staged = FlightCargo(
        flight_name=STAGED_FLIGHT, client_id=STAGED_CODE, photo_file_ids="[]"
    )
    session.add(staged)
    await session.flush()

    yield

    assert session.in_transaction()
    assert inspect(staged).persistent, "the handler's session was rolled back"
    async with engine.connect() as conn:
        committed = await conn.scalar(
            select(func.count())
            .select_from(FlightCargo)
            .where(FlightCargo.client_id == STAGED_CODE)
        )
    assert committed == 0, "the handler's session was committed"
    await session.delete(staged)
    await session.flush()


async def committed_aliases(engine: AsyncEngine) -> dict[str, str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(
                PartnerFlightAlias.real_flight_name,
                PartnerFlightAlias.mask_flight_name,
            )
        )
        return {real: mask for real, mask in rows}


async def forget_minted_aliases(engine: AsyncEngine) -> None:
    """Delete every alias but the seeded one, so the next render has to mint."""
    async with engine.begin() as conn:
        await conn.execute(
            delete(PartnerFlightAlias).where(
                PartnerFlightAlias.real_flight_name != MASKED_FLIGHT
            )
        )


async def render_minting(
    engine: AsyncEngine, session: AsyncSession, flight: str, render: Render
) -> Output:
    """Run ``render`` with ``flight`` unaliased; it must show the minted mask."""
    await forget_minted_aliases(engine)
    assert flight not in await committed_aliases(engine)

    bot = AsyncMock()
    async with own_session_untouched(engine, session):
        await render(bot)

    output = capture(bot)
    output.assert_no_real_flight_names()
    shown = (*output.texts, *output.alerts)
    assert any(MINTED_MASK in value for value in shown), shown
    assert not any("Reys #" in value for value in shown), shown
    assert (await committed_aliases(engine))[flight] == MINTED_MASK
    return output


def flight_buttons(output: Output) -> list[str]:
    """Flight button labels without their amount / status suffix."""
    return [label.split(" - ")[0] for label in output.buttons if label.startswith("✈️")]


def answered(bot: AsyncMock) -> list[tuple[str | None, bool | None]]:
    return [(answer.text, answer.show_alert) for answer in callback_answers(bot)]


# ---------------------------------------------------------------------------
# info.py
# ---------------------------------------------------------------------------


async def test_info_list_mints_the_missing_alias(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
) -> None:
    await seed_world(db_session, redis_client)

    listing = await render_minting(
        db_engine,
        db_session,
        UNMASKED_FLIGHT,
        lambda bot: info.info_handler(
            make_message(bot, PARTNER_TG),
            _=translate,
            session=db_session,
            client_service=client_service,
            redis=redis_client,
            state=make_state(PARTNER_TG),
        ),
    )
    assert flight_buttons(listing) == [f"✈️ {MASK}", f"✈️ {MINTED_MASK}"]

    # A client without a partner has no alias slice: ordinals, nothing minted.
    bot = AsyncMock()
    await info.info_handler(
        make_message(bot, LONE_TG),
        _=translate,
        session=db_session,
        client_service=client_service,
        redis=redis_client,
        state=make_state(LONE_TG),
    )
    lone = capture(bot)
    lone.assert_no_real_flight_names()
    assert flight_buttons(lone) == ["✈️ Reys #1", "✈️ Reys #2"]
    assert await committed_aliases(db_engine) == {
        MASKED_FLIGHT: MASK,
        UNMASKED_FLIGHT: MINTED_MASK,
    }


async def test_info_details_and_photos_mint_the_missing_alias(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
) -> None:
    await seed_world(db_session, redis_client)
    await prime_sheets(
        redis_client, PARTNER_CODE, [MASKED_FLIGHT, UNMASKED_FLIGHT, UNREPORTED_FLIGHT]
    )
    scope = await token_scope(db_session, client_service, PARTNER_TG)

    # Sheet rows start at 2: a flight with sent cargo, then one without.
    for flight, row in ((UNMASKED_FLIGHT, 3), (UNREPORTED_FLIGHT, 4)):
        data = f"info_flight:{flight_token(flight, scope)}:{row}"
        details = await render_minting(
            db_engine,
            db_session,
            flight,
            lambda bot, data=data: info.flight_details_handler(
                make_callback(bot, PARTNER_TG, data),
                _=translate,
                session=db_session,
                client_service=client_service,
                transaction_service=None,
                redis=redis_client,
            ),
        )
        assert details.screens == 1

    photos = await render_minting(
        db_engine,
        db_session,
        UNMASKED_FLIGHT,
        lambda bot: info.view_cargo_photos_handler(
            make_callback(
                bot,
                PARTNER_TG,
                f"view_cargo_photos:{flight_token(UNMASKED_FLIGHT, scope)}",
            ),
            _=translate,
            session=db_session,
            client_service=client_service,
            redis=redis_client,
        ),
    )
    assert photos.screens == 1


# ---------------------------------------------------------------------------
# make_payment.py
# ---------------------------------------------------------------------------


async def test_payment_list_mints_the_missing_alias(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
) -> None:
    await seed_world(db_session, redis_client)

    listing = await render_minting(
        db_engine,
        db_session,
        UNMASKED_FLIGHT,
        lambda bot: make_payment.make_payment_handler(
            make_message(bot, PARTNER_TG),
            _=translate,
            session=db_session,
            client_service=client_service,
            redis=redis_client,
            state=make_state(PARTNER_TG),
        ),
    )
    assert flight_buttons(listing) == [f"✈️ {MASK}", f"✈️ {MINTED_MASK}"]


async def test_every_payment_step_mints_the_missing_alias(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
) -> None:
    await seed_world(db_session, redis_client)
    await prime_sheets(
        redis_client, PARTNER_CODE, [MASKED_FLIGHT, UNMASKED_FLIGHT, UNREPORTED_FLIGHT]
    )
    db_session.add(make_active_card())
    await db_session.commit()
    scope = await token_scope(db_session, client_service, PARTNER_TG)
    token = flight_token(UNMASKED_FLIGHT, scope)
    state = make_state(PARTNER_TG)
    services = {"session": db_session, "client_service": client_service}

    def press(
        handler: Callable[..., Awaitable[object]], data: str, **extra: object
    ) -> Render:
        return lambda bot: handler(
            make_callback(bot, PARTNER_TG, data),
            _=translate,
            state=state,
            **services,
            **extra,
        )

    # A flight with no photo report names only its mask and starts no flow.
    unreported = await render_minting(
        db_engine,
        db_session,
        UNREPORTED_FLIGHT,
        press(
            make_payment.payment_flight_selected,
            f"pay_flight:{flight_token(UNREPORTED_FLIGHT, scope)}",
            redis=redis_client,
        ),
    )
    assert f"Reys: <b>{MINTED_MASK}</b>" in unreported.texts[0]
    assert await state.get_data() == {}

    await press(
        make_payment.payment_flight_selected, f"pay_flight:{token}", redis=redis_client
    )(AsyncMock())
    assert (await state.get_data())["worksheet"] == UNMASKED_FLIGHT

    toggle = press(
        make_payment.payment_wallet_toggle_handler,
        f"payment_wallet_toggle:{token}",
        redis=redis_client,
    )
    screens = (
        press(make_payment.payment_type_cash_selected, f"payment_type:cash:{token}"),
        toggle,  # cash confirmation
        press(make_payment.pay_full_handler, f"pay_full:{token}"),
        toggle,  # card details
        press(
            make_payment.pay_partial_handler,
            f"pay_partial:{token}",
            transaction_service=None,
        ),
    )
    for screen in screens:
        output = await render_minting(db_engine, db_session, UNMASKED_FLIGHT, screen)
        assert output.screens == 1

    await press(
        make_payment.enter_partial_amount_handler, f"enter_partial_amount:{token}"
    )(AsyncMock())
    partial = await render_minting(
        db_engine,
        db_session,
        UNMASKED_FLIGHT,
        lambda bot: make_payment.partial_amount_received(
            make_message(bot, PARTNER_TG, "100000"),
            _=translate,
            state=state,
            transaction_service=None,
            **services,
        ),
    )
    assert partial.screens == 1

    db_session.add(
        make_transaction(
            PARTNER_TG,
            PARTNER_CODE,
            UNMASKED_FLIGHT,
            status="partial",
            remaining=Decimal("150000.00"),
        )
    )
    await db_session.commit()
    remaining = await render_minting(
        db_engine,
        db_session,
        UNMASKED_FLIGHT,
        press(
            make_payment.pay_full_remaining_handler,
            f"pay_full_remaining:{token}",
            transaction_service=None,
        ),
    )
    assert remaining.screens == 1

    await state.update_data(payment_mode="full", wallet_balance=1_000_000.0)
    wallet_only = await render_minting(
        db_engine,
        db_session,
        UNMASKED_FLIGHT,
        lambda bot: make_payment.payment_wallet_only_handler(
            make_callback(bot, PARTNER_TG, f"payment_wallet_only:{token}"),
            _=translate,
            state=state,
            bot=bot,
            redis=redis_client,
            **services,
        ),
    )
    assert wallet_only.screens == 1


# ---------------------------------------------------------------------------
# profile.py
# ---------------------------------------------------------------------------


async def test_payment_reminder_mints_the_missing_alias(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
) -> None:
    await seed_world(db_session, redis_client)
    db_session.add(
        make_transaction(
            PARTNER_TG,
            PARTNER_CODE,
            UNMASKED_FLIGHT,
            status="partial",
            remaining=Decimal("150000.00"),
        )
    )
    await db_session.commit()

    reminder = await render_minting(
        db_engine,
        db_session,
        UNMASKED_FLIGHT,
        lambda bot: profile.payment_reminder_handler(
            make_message(bot, PARTNER_TG),
            _=translate,
            session=db_session,
            client_service=client_service,
            state=make_state(PARTNER_TG),
        ),
    )
    assert any(text.endswith(f" - {MINTED_MASK}") for text in reminder.texts)


# ---------------------------------------------------------------------------
# delivery_request.py
# ---------------------------------------------------------------------------


async def test_delivery_flow_mints_the_missing_alias(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_world(db_session, redis_client)
    db_session.add_all(
        [
            make_transaction(
                PARTNER_TG, PARTNER_CODE, flight, status="paid", remaining=Decimal("0")
            )
            for flight in (MASKED_FLIGHT, UNMASKED_FLIGHT)
        ]
    )
    db_session.add(make_active_card())
    await db_session.commit()
    client = await client_service.get_client(PARTNER_TG, db_session)
    scope = await token_scope(db_session, client_service, PARTNER_TG)
    state = make_state(PARTNER_TG)
    await state.update_data(delivery_type="uzpost")
    services = {"session": db_session, "client_service": client_service}

    offer = await render_minting(
        db_engine,
        db_session,
        UNMASKED_FLIGHT,
        lambda bot: delivery_request.profile_confirmation_yes(
            make_callback(bot, PARTNER_TG, "confirm_profile_yes"),
            _=translate,
            redis=redis_client,
            state=state,
            **services,
        ),
    )
    assert flight_buttons(offer) == [f"✈️ {MASK}", f"✈️ {MINTED_MASK}"]

    bot = AsyncMock()
    await delivery_request.process_flight_selection(
        make_callback(
            bot, PARTNER_TG, f"select_flight:{flight_token(UNMASKED_FLIGHT, scope)}"
        ),
        _=translate,
        state=state,
        **services,
    )
    assert (await state.get_data())["selected_flights"] == [UNMASKED_FLIGHT]

    def done(bot: AsyncMock) -> Awaitable[object]:
        return delivery_request.process_flight_selection_done(
            make_callback(bot, PARTNER_TG, "flight_selection_done"),
            _=translate,
            state=state,
            bot=bot,
            redis=redis_client,
            **services,
        )

    uzpost = await render_minting(db_engine, db_session, UNMASKED_FLIGHT, done)
    assert uzpost.screens == 2  # payment details, then the receipt prompt

    toggled = await render_minting(
        db_engine,
        db_session,
        UNMASKED_FLIGHT,
        lambda bot: delivery_request.uzpost_toggle_wallet(
            make_callback(bot, PARTNER_TG, "uzpost_toggle_wallet"),
            _=translate,
            state=state,
            **services,
        ),
    )
    assert toggled.screens == 1

    # A repeated request inside the rate-limit window names the flight too.
    await DeliveryRequestDAO.create(
        session=db_session,
        client_id=client.id,
        client_code=client.client_code,
        telegram_id=client.telegram_id,
        delivery_type="uzpost",
        flight_names=json.dumps([UNMASKED_FLIGHT]),
        full_name=client.full_name,
        phone=client.phone,
        region=client.region,
        address=client.address,
    )
    await db_session.commit()

    async def every_request_is_recent(
        session: AsyncSession, client_id: int, hours: int = 1
    ) -> list[DeliveryRequest]:
        """The one-hour window is the DAO's concern, not the rendering's."""
        result = await session.execute(
            select(DeliveryRequest).where(DeliveryRequest.client_id == client_id)
        )
        return list(result.scalars())

    monkeypatch.setattr(
        DeliveryRequestDAO,
        "get_recent_requests_by_client",
        staticmethod(every_request_is_recent),
    )
    limited = await render_minting(db_engine, db_session, UNMASKED_FLIGHT, done)
    assert limited.screens == 0
    assert len(limited.alerts) == 1


# ---------------------------------------------------------------------------
# Answering each callback exactly once
# ---------------------------------------------------------------------------


async def test_uzpost_wallet_only_submit_answers_exactly_once(
    db_session: AsyncSession, redis_client: Redis, client_service: ClientService
) -> None:
    await seed_world(db_session, redis_client)

    async def submit(telegram_id: int, bot: AsyncMock, wallet_used: int) -> FSMContext:
        state = make_state(telegram_id)
        await state.update_data(
            selected_flights=[UNMASKED_FLIGHT],
            delivery_type="uzpost",
            wallet_used=wallet_used,
            total_amount=21000,
        )
        await delivery_request.uzpost_wallet_only_submit(
            make_callback(bot, telegram_id, "uzpost_wallet_only_submit"),
            _=translate,
            session=db_session,
            client_service=client_service,
            state=state,
            bot=bot,
            redis=redis_client,
        )
        return state

    # Unknown client: the error alert is the only answer.
    bot = AsyncMock()
    await submit(UNKNOWN_TG, bot, wallet_used=21000)
    assert answered(bot) == [(ERROR_TEXT, True)]
    assert_rejected(capture(bot))

    # The wallet does not cover the amount.
    bot = AsyncMock()
    await submit(PARTNER_TG, bot, wallet_used=1000)
    assert [text for text, _alert in answered(bot)] == [None]
    assert capture(bot).texts == [ERROR_TEXT]
    bot.send_message.assert_not_awaited()

    # The admin group is unreachable: only handle_errors answers the press.
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("admin group unreachable")
    await submit(PARTNER_TG, bot, wallet_used=21000)
    assert [text for text, _alert in answered(bot)] == [None]

    # Telegram refuses the admin send.  handle_errors only logs a Telegram
    # error, so the handler answers the press itself before it propagates.
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramBadRequest(
        method=SendMessage(chat_id=1, text="request"),
        message="Bad Request: chat not found",
    )
    await submit(PARTNER_TG, bot, wallet_used=21000)
    assert [text for text, _alert in answered(bot)] == [None]

    bot = AsyncMock()
    state = await submit(PARTNER_TG, bot, wallet_used=21000)
    assert [text for text, _alert in answered(bot)] == [None]
    bot.send_message.assert_awaited_once()
    assert capture(bot).texts == [
        translate("delivery-wallet-only-submitted", amount="21,000")
    ]
    assert await state.get_data() == {}


async def test_flight_selection_done_rejects_a_missing_client(
    db_session: AsyncSession, redis_client: Redis, client_service: ClientService
) -> None:
    await seed_world(db_session, redis_client)
    state = make_state(UNKNOWN_TG)
    await state.update_data(selected_flights=[UNMASKED_FLIGHT], delivery_type="uzpost")

    bot = AsyncMock()
    await delivery_request.process_flight_selection_done(
        make_callback(bot, UNKNOWN_TG, "flight_selection_done"),
        _=translate,
        session=db_session,
        client_service=client_service,
        state=state,
        bot=bot,
        redis=redis_client,
    )

    assert answered(bot) == [(ERROR_TEXT, True)]
    assert_rejected(capture(bot))
    bot.send_message.assert_not_awaited()
    assert await state.get_data() == {
        "selected_flights": [UNMASKED_FLIGHT],
        "delivery_type": "uzpost",
    }


async def open_payment(
    session: AsyncSession,
    redis: Redis,
    client_service: ClientService,
    state: FSMContext,
) -> str:
    """Start paying ``MASKED_FLIGHT`` online; return its wallet-toggle payload."""
    token = flight_token(
        MASKED_FLIGHT, await token_scope(session, client_service, PARTNER_TG)
    )
    await make_payment.payment_flight_selected(
        make_callback(AsyncMock(), PARTNER_TG, f"pay_flight:{token}"),
        _=translate,
        session=session,
        client_service=client_service,
        state=state,
        redis=redis,
    )
    await state.update_data(payment_mode="full")
    assert (await state.get_data())["use_wallet"] is False
    return f"payment_wallet_toggle:{token}"


async def test_wallet_toggle_saves_the_choice_only_once_it_is_shown(
    db_session: AsyncSession, redis_client: Redis, client_service: ClientService
) -> None:
    await seed_world(db_session, redis_client)
    state = make_state(PARTNER_TG)
    data = await open_payment(db_session, redis_client, client_service, state)

    async def press(bot: AsyncMock) -> None:
        await make_payment.payment_wallet_toggle_handler(
            make_callback(bot, PARTNER_TG, data),
            _=translate,
            session=db_session,
            client_service=client_service,
            state=state,
            redis=redis_client,
        )

    # No active card: the press is refused and the saved choice stays off.
    bot = AsyncMock()
    await press(bot)
    assert answered(bot) == [(translate("payment-no-cards"), True)]
    assert capture(bot).screens == 0
    assert (await state.get_data())["use_wallet"] is False

    db_session.add(make_active_card())
    await db_session.commit()
    for expected in (True, False):
        bot = AsyncMock()
        await press(bot)
        assert answered(bot) == [(None, False)]
        assert capture(bot).screens == 1
        assert (await state.get_data())["use_wallet"] is expected


async def test_wallet_toggle_answers_once_when_it_raises(
    db_session: AsyncSession,
    redis_client: Redis,
    client_service: ClientService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_world(db_session, redis_client)
    db_session.add(make_active_card())
    await db_session.commit()
    state = make_state(PARTNER_TG)
    data = await open_payment(db_session, redis_client, client_service, state)

    async def press(bot: AsyncMock) -> None:
        await make_payment.payment_wallet_toggle_handler(
            make_callback(bot, PARTNER_TG, data),
            _=translate,
            session=db_session,
            client_service=client_service,
            state=state,
            redis=redis_client,
        )

    async def refuse_edits(method: TelegramMethod[object]) -> bool:
        if isinstance(method, EditMessageText):
            raise TelegramBadRequest(
                method=method, message="Bad Request: message to edit not found"
            )
        return True

    # Telegram refuses the edit: the press is answered, and nothing the screen
    # would have shown is saved, the card drawn for it included.
    await state.update_data(shown_card_id=PREVIOUSLY_SHOWN_CARD_ID)
    bot = AsyncMock(side_effect=refuse_edits)
    with pytest.raises(TelegramBadRequest):
        await press(bot)
    assert answered(bot) == [(ERROR_TEXT, True)]
    assert (await state.get_data())["use_wallet"] is False
    assert (await state.get_data())["shown_card_id"] == PREVIOUSLY_SHOWN_CARD_ID

    async def database_down(session: AsyncSession, active_codes: list[str]) -> float:
        raise ConnectionError("database unavailable")

    # The database fails before anything is shown.
    monkeypatch.setattr(make_payment, "_get_wallet_balance", database_down)
    bot = AsyncMock()
    with pytest.raises(ConnectionError):
        await press(bot)
    assert answered(bot) == [(ERROR_TEXT, True)]
    assert capture(bot).screens == 0
    assert (await state.get_data())["use_wallet"] is False
