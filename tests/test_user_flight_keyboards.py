"""User flight keyboards must never expose a real flight name to the client.

``callback_data`` reaches the Telegram client together with the message, so
both the rendered text and every payload of the keyboards built by the user
handlers (info, make_payment, delivery_request, profile) are checked here.
Tokens are scoped to the client they are shown to, so every payload is also
checked to resolve only for that client.

Handlers are called directly with aiogram objects bound to an ``AsyncMock``
bot, on a fresh PostgreSQL schema, with an in-memory Redis whose primed
``sheets_data`` keys stand in for Google Sheets (see ``_user_flight_fakes``).
Minting of missing aliases is covered by ``test_user_flight_minting``.
"""

import json
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.methods import AnswerCallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.handlers.user import delivery_request, info, make_payment, profile
from src.bot.utils.flight_token import (
    client_token_scope,
    flight_token,
    resolve_flight_token,
)
from src.bot.utils.sheets_cache import get_client_sheets_data
from src.config import config
from src.infrastructure.database.models.delivery_request import DeliveryRequest
from src.infrastructure.services import ClientService
from tests._user_flight_fakes import (
    CARGO_TOTAL,
    FORGED_TOKEN,
    LONE_CODE,
    LONE_FLIGHT_A,
    LONE_FLIGHT_B,
    LONE_TG,
    MASK,
    MASKED_FLIGHT,
    MINTED_MASK,
    PADDED_FLIGHT,
    PARTNER_CODE,
    PARTNER_TG,
    UNKNOWN_TG,
    UNMASKED_FLIGHT,
    Output,
    assert_rejected,
    callback_answers,
    capture,
    fake_redis,
    keep_google_sheets_offline,
    make_active_card,
    make_callback,
    make_cargo,
    make_message,
    make_state,
    make_transaction,
    prime_sheets,
    seed_world,
    token_scope,
    translate,
)


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
# info.py
# ---------------------------------------------------------------------------


async def test_info_screens_render_masks_and_tokens_only(
    db_session: AsyncSession, redis_client: Redis, client_service: ClientService
) -> None:
    await seed_world(db_session, redis_client)
    expectations = {
        PARTNER_TG: ([MASKED_FLIGHT, UNMASKED_FLIGHT], [MASK, MINTED_MASK]),
        LONE_TG: ([LONE_FLIGHT_A, LONE_FLIGHT_B], ["Reys #1", "Reys #2"]),
    }

    for telegram_id, (flights, labels) in expectations.items():
        client = await client_service.get_client(telegram_id, db_session)
        scope = client_token_scope(client.id)
        sheets = await get_client_sheets_data(client.active_codes, redis_client)
        allowed = info._sheet_flight_names(sheets)

        bot = AsyncMock()
        await info.info_handler(
            make_message(bot, telegram_id),
            _=translate,
            session=db_session,
            client_service=client_service,
            redis=redis_client,
            state=make_state(telegram_id),
        )
        listing = capture(bot)
        listing.assert_no_real_flight_names()
        buttons = listing.callbacks("info_flight:")
        assert [
            resolve_flight_token(data.split(":")[1], allowed, scope) for data in buttons
        ] == flights
        for label in labels:
            assert any(label in text for text in listing.texts)

        payable = await make_payment._client_payable_flights(
            db_session, client, redis_client
        )
        for data, flight in zip(buttons, flights, strict=True):
            token = flight_token(flight, scope)

            bot = AsyncMock()
            await info.flight_details_handler(
                make_callback(bot, telegram_id, data),
                _=translate,
                session=db_session,
                client_service=client_service,
                transaction_service=None,
                redis=redis_client,
            )
            details = capture(bot)
            assert details.screens == 1
            details.assert_no_real_flight_names()
            assert details.callbacks("view_cargo_photos:") == [
                f"view_cargo_photos:{token}"
            ]
            assert details.callbacks("pay_flight:") == [f"pay_flight:{token}"]
            assert resolve_flight_token(token, payable, scope) == flight

            bot = AsyncMock()
            await info.view_cargo_photos_handler(
                make_callback(bot, telegram_id, f"view_cargo_photos:{token}"),
                _=translate,
                session=db_session,
                client_service=client_service,
                redis=redis_client,
            )
            photos = capture(bot)
            assert photos.screens == 1
            photos.assert_no_real_flight_names()


async def test_info_callbacks_reject_forged_foreign_raw_and_malformed_payloads(
    db_session: AsyncSession, redis_client: Redis, client_service: ClientService
) -> None:
    await seed_world(db_session, redis_client)
    partner_scope = await token_scope(db_session, client_service, PARTNER_TG)
    lone_scope = await token_scope(db_session, client_service, LONE_TG)
    own_token = flight_token(MASKED_FLIGHT, partner_scope)
    rejected_details = (
        f"info_flight:{FORGED_TOKEN}:2",
        # Copied from the other client's button.
        f"info_flight:{flight_token(LONE_FLIGHT_A, lone_scope)}:2",
        # An owned flight, but minted for the other client.
        f"info_flight:{flight_token(MASKED_FLIGHT, lone_scope)}:2",
        # The raw real name of an owned flight: accepting it confirms guesses.
        f"info_flight:{MASKED_FLIGHT}:2",
        f"info_flight:{own_token}:abc",
        f"info_flight:{own_token}:99999999999",
        f"info_flight:{own_token}",
    )
    for data in rejected_details:
        bot = AsyncMock()
        await info.flight_details_handler(
            make_callback(bot, PARTNER_TG, data),
            _=translate,
            session=db_session,
            client_service=client_service,
            transaction_service=None,
            redis=redis_client,
        )
        assert_rejected(capture(bot))

    for data in (
        f"view_cargo_photos:{FORGED_TOKEN}",
        f"view_cargo_photos:{flight_token(LONE_FLIGHT_B, lone_scope)}",
        f"view_cargo_photos:{flight_token(MASKED_FLIGHT, lone_scope)}",
        f"view_cargo_photos:{MASKED_FLIGHT}",
    ):
        bot = AsyncMock()
        await info.view_cargo_photos_handler(
            make_callback(bot, PARTNER_TG, data),
            _=translate,
            session=db_session,
            client_service=client_service,
            redis=redis_client,
        )
        assert_rejected(capture(bot))


# ---------------------------------------------------------------------------
# info.py + make_payment.py: names with surrounding whitespace
# ---------------------------------------------------------------------------


async def test_padded_flight_name_still_shows_its_amounts(
    db_session: AsyncSession, redis_client: Redis, client_service: ClientService
) -> None:
    await seed_world(db_session, redis_client)
    db_session.add(make_cargo(LONE_CODE, PADDED_FLIGHT))
    await db_session.commit()
    await prime_sheets(
        redis_client, LONE_CODE, [LONE_FLIGHT_A, LONE_FLIGHT_B, PADDED_FLIGHT]
    )
    token = flight_token(
        PADDED_FLIGHT, await token_scope(db_session, client_service, LONE_TG)
    )

    bot = AsyncMock()
    await info.flight_details_handler(
        make_callback(bot, LONE_TG, f"info_flight:{token}:4"),
        _=translate,
        session=db_session,
        client_service=client_service,
        transaction_service=None,
        redis=redis_client,
    )
    details = capture(bot)
    assert details.screens == 1
    details.assert_no_real_flight_names()
    assert any(CARGO_TOTAL in text for text in details.texts)
    assert details.callbacks("pay_flight:") == [f"pay_flight:{token}"]

    state = make_state(LONE_TG)
    bot = AsyncMock()
    await make_payment.payment_flight_selected(
        make_callback(bot, LONE_TG, f"pay_flight:{token}"),
        _=translate,
        session=db_session,
        client_service=client_service,
        state=state,
        redis=redis_client,
    )
    selection = capture(bot)
    selection.assert_no_real_flight_names()
    assert selection.callbacks("payment_type:cash:") == [f"payment_type:cash:{token}"]
    data = await state.get_data()
    assert data["worksheet"] == PADDED_FLIGHT
    assert data["summa"] == CARGO_TOTAL

    bot = AsyncMock()
    await make_payment.payment_type_cash_selected(
        make_callback(bot, LONE_TG, f"payment_type:cash:{token}"),
        _=translate,
        session=db_session,
        client_service=client_service,
        state=state,
    )
    cash = capture(bot)
    assert cash.screens == 1
    cash.assert_no_real_flight_names()
    assert any(CARGO_TOTAL in text for text in cash.texts)


# ---------------------------------------------------------------------------
# make_payment.py
# ---------------------------------------------------------------------------


async def test_payment_list_offers_tokens_for_both_kinds_of_client(
    db_session: AsyncSession, redis_client: Redis, client_service: ClientService
) -> None:
    await seed_world(db_session, redis_client)
    expectations = {
        PARTNER_TG: [MASKED_FLIGHT, UNMASKED_FLIGHT],
        LONE_TG: [LONE_FLIGHT_A, LONE_FLIGHT_B],
    }
    for telegram_id, flights in expectations.items():
        client = await client_service.get_client(telegram_id, db_session)
        scope = client_token_scope(client.id)
        bot = AsyncMock()
        await make_payment.make_payment_handler(
            make_message(bot, telegram_id),
            _=translate,
            session=db_session,
            client_service=client_service,
            redis=redis_client,
            state=make_state(telegram_id),
        )
        listing = capture(bot)
        listing.assert_no_real_flight_names()
        payable = await make_payment._client_payable_flights(
            db_session, client, redis_client
        )
        tokens = [data.split(":", 1)[1] for data in listing.callbacks("pay_flight:")]
        assert [
            resolve_flight_token(token, payable, scope) for token in tokens
        ] == flights


async def test_pay_flight_rejects_forged_foreign_and_raw_payloads(
    db_session: AsyncSession, redis_client: Redis, client_service: ClientService
) -> None:
    await seed_world(db_session, redis_client)
    lone_scope = await token_scope(db_session, client_service, LONE_TG)
    for data in (
        f"pay_flight:{FORGED_TOKEN}",
        f"pay_flight:{flight_token(LONE_FLIGHT_A, lone_scope)}",
        f"pay_flight:{flight_token(MASKED_FLIGHT, lone_scope)}",
        f"pay_flight:{LONE_FLIGHT_A}",
        f"pay_flight:{MASKED_FLIGHT}",
    ):
        state = make_state(PARTNER_TG)
        bot = AsyncMock()
        await make_payment.payment_flight_selected(
            make_callback(bot, PARTNER_TG, data),
            _=translate,
            session=db_session,
            client_service=client_service,
            state=state,
            redis=redis_client,
        )
        assert_rejected(capture(bot))
        assert await state.get_data() == {}


async def test_payment_steps_are_bound_to_the_worksheet_flight(
    db_session: AsyncSession, redis_client: Redis, client_service: ClientService
) -> None:
    await seed_world(db_session, redis_client)
    scope = await token_scope(db_session, client_service, PARTNER_TG)
    lone_scope = await token_scope(db_session, client_service, LONE_TG)
    state = make_state(PARTNER_TG)
    token = flight_token(MASKED_FLIGHT, scope)

    bot = AsyncMock()
    await make_payment.payment_flight_selected(
        make_callback(bot, PARTNER_TG, f"pay_flight:{token}"),
        _=translate,
        session=db_session,
        client_service=client_service,
        state=state,
        redis=redis_client,
    )
    selection = capture(bot)
    selection.assert_no_real_flight_names()
    assert (await state.get_data())["worksheet"] == MASKED_FLIGHT
    assert selection.callbacks("payment_type:") == [
        f"payment_type:online:{token}",
        f"payment_type:cash:{token}",
    ]

    bot = AsyncMock()
    await make_payment.payment_type_online_selected(
        make_callback(bot, PARTNER_TG, f"payment_type:online:{token}"),
        _=translate,
        session=db_session,
        client_service=client_service,
        transaction_service=None,
        state=state,
    )
    online = capture(bot)
    online.assert_no_real_flight_names()
    assert online.callbacks("pay_full:") == [f"pay_full:{token}"]
    assert online.callbacks("pay_partial:") == [f"pay_partial:{token}"]

    bot = AsyncMock()
    await make_payment.payment_type_cash_selected(
        make_callback(bot, PARTNER_TG, f"payment_type:cash:{token}"),
        _=translate,
        session=db_session,
        client_service=client_service,
        state=state,
    )
    cash = capture(bot)
    cash.assert_no_real_flight_names()
    assert cash.callbacks("cash_confirm:") == [f"cash_confirm:{token}"]
    assert any(MASK in text for text in cash.texts)

    builder = InlineKeyboardBuilder()
    make_payment._add_wallet_toggle_button(
        builder, 5000.0, False, MASKED_FLIGHT, scope, translate
    )
    assert [
        button.callback_data
        for row in builder.as_markup().inline_keyboard
        for button in row
    ] == [f"payment_wallet_toggle:{token}"]

    bot = AsyncMock()
    await make_payment.payment_wallet_toggle_handler(
        make_callback(bot, PARTNER_TG, f"payment_wallet_toggle:{token}"),
        _=translate,
        session=db_session,
        client_service=client_service,
        state=state,
        redis=redis_client,
    )
    toggled = capture(bot)
    assert toggled.screens == 1
    toggled.assert_no_real_flight_names()
    assert toggled.callbacks("cash_confirm:") == [f"cash_confirm:{token}"]

    # Every flight a payload below names has a partial transaction and there is
    # an active card, so pay_full_remaining would proceed for any of them: only
    # the worksheet binding and the token scope can reject.
    db_session.add_all(
        [
            make_transaction(
                PARTNER_TG,
                PARTNER_CODE,
                flight,
                status="partial",
                remaining=Decimal("150000.00"),
            )
            for flight in (MASKED_FLIGHT, UNMASKED_FLIGHT, LONE_FLIGHT_A)
        ]
    )
    db_session.add(make_active_card())
    await db_session.commit()

    other_owned = flight_token(UNMASKED_FLIGHT, scope)
    foreign = flight_token(LONE_FLIGHT_A, lone_scope)
    replayed = flight_token(MASKED_FLIGHT, lone_scope)
    base = {
        "session": db_session,
        "client_service": client_service,
        "transaction_service": None,
        "redis": redis_client,
    }
    rejected_steps = (
        (
            make_payment.payment_type_online_selected,
            f"payment_type:online:{other_owned}",
            ("session", "client_service", "transaction_service"),
        ),
        (
            make_payment.payment_type_online_selected,
            f"payment_type:online:{MASKED_FLIGHT}",
            ("session", "client_service", "transaction_service"),
        ),
        (
            make_payment.payment_type_cash_selected,
            f"payment_type:cash:{replayed}",
            ("session", "client_service"),
        ),
        (
            make_payment.pay_full_handler,
            f"pay_full:{other_owned}",
            ("session", "client_service"),
        ),
        (
            make_payment.pay_full_remaining_handler,
            f"pay_full_remaining:{other_owned}",
            ("session", "client_service", "transaction_service"),
        ),
        (
            make_payment.pay_full_remaining_handler,
            f"pay_full_remaining:{foreign}",
            ("session", "client_service", "transaction_service"),
        ),
        (
            make_payment.pay_full_remaining_handler,
            f"pay_full_remaining:{replayed}",
            ("session", "client_service", "transaction_service"),
        ),
        (
            make_payment.pay_full_remaining_handler,
            f"pay_full_remaining:{MASKED_FLIGHT}",
            ("session", "client_service", "transaction_service"),
        ),
        (
            make_payment.pay_partial_handler,
            f"pay_partial:{FORGED_TOKEN}",
            ("session", "client_service", "transaction_service"),
        ),
        (
            make_payment.enter_partial_amount_handler,
            f"enter_partial_amount:{other_owned}",
            ("session", "client_service"),
        ),
        (
            make_payment.enter_partial_amount_handler,
            f"enter_partial_amount:{MASKED_FLIGHT}",
            ("session", "client_service"),
        ),
        (
            make_payment.payment_wallet_toggle_handler,
            f"payment_wallet_toggle:{FORGED_TOKEN}",
            ("session", "client_service", "redis"),
        ),
        (
            make_payment.payment_wallet_toggle_handler,
            f"payment_wallet_toggle:{replayed}",
            ("session", "client_service", "redis"),
        ),
        (
            make_payment.payment_wallet_only_handler,
            f"payment_wallet_only:{other_owned}",
            ("session", "client_service", "bot", "redis"),
        ),
        (
            make_payment.cash_payment_confirmed,
            f"cash_confirm:{foreign}",
            ("session", "client_service", "bot", "redis"),
        ),
        (
            make_payment.cash_payment_confirmed,
            f"cash_confirm:{MASKED_FLIGHT}",
            ("session", "client_service", "bot", "redis"),
        ),
    )
    for handler, data, needs in rejected_steps:
        bot = AsyncMock()
        available = {**base, "bot": bot}
        kwargs = {name: available[name] for name in needs}
        await handler(
            make_callback(bot, PARTNER_TG, data), _=translate, state=state, **kwargs
        )
        assert_rejected(capture(bot))
        assert bot.send_message.await_count == 0
        data_after = await state.get_data()
        assert data_after["worksheet"] == MASKED_FLIGHT
        assert data_after["payment_mode"] == "cash"
        assert "partial_flight" not in data_after

    # The same setup accepts the worksheet's own token.
    bot = AsyncMock()
    await make_payment.pay_full_remaining_handler(
        make_callback(bot, PARTNER_TG, f"pay_full_remaining:{token}"),
        _=translate,
        session=db_session,
        client_service=client_service,
        transaction_service=None,
        state=state,
    )
    remaining = capture(bot)
    assert remaining.screens == 1
    remaining.assert_no_real_flight_names()
    assert any("150,000.00" in text for text in remaining.texts)
    assert (await state.get_data())["payment_mode"] == "full_remaining"

    bot = AsyncMock()
    await make_payment.enter_partial_amount_handler(
        make_callback(bot, PARTNER_TG, f"enter_partial_amount:{token}"),
        _=translate,
        session=db_session,
        client_service=client_service,
        state=state,
    )
    capture(bot).assert_no_real_flight_names()
    assert (await state.get_data())["partial_flight"] == MASKED_FLIGHT


async def test_wallet_toggle_answers_the_callback_exactly_once_on_every_branch(
    db_session: AsyncSession, redis_client: Redis, client_service: ClientService
) -> None:
    await seed_world(db_session, redis_client)
    token = flight_token(
        MASKED_FLIGHT, await token_scope(db_session, client_service, PARTNER_TG)
    )
    state = make_state(PARTNER_TG)
    bot = AsyncMock()
    await make_payment.payment_flight_selected(
        make_callback(bot, PARTNER_TG, f"pay_flight:{token}"),
        _=translate,
        session=db_session,
        client_service=client_service,
        state=state,
        redis=redis_client,
    )
    assert (await state.get_data())["worksheet"] == MASKED_FLIGHT

    async def press_toggle(
        telegram_id: int, data: str, toggle_state: FSMContext
    ) -> tuple[Output, list[AnswerCallbackQuery]]:
        bot = AsyncMock()
        await make_payment.payment_wallet_toggle_handler(
            make_callback(bot, telegram_id, data),
            _=translate,
            session=db_session,
            client_service=client_service,
            state=toggle_state,
            redis=redis_client,
        )
        return capture(bot), callback_answers(bot)

    rejected = (
        (PARTNER_TG, f"payment_wallet_toggle:{token}:extra", state),
        (UNKNOWN_TG, f"payment_wallet_toggle:{token}", make_state(UNKNOWN_TG)),
        (PARTNER_TG, f"payment_wallet_toggle:{FORGED_TOKEN}", state),
    )
    for telegram_id, data, toggle_state in rejected:
        output, answers = await press_toggle(telegram_id, data, toggle_state)
        assert len(answers) == 1, data
        assert answers[0].show_alert
        assert_rejected(output)

    # Online payment with no active card: the no-card alert is the only answer.
    await state.update_data(payment_mode="full")
    output, answers = await press_toggle(
        PARTNER_TG, f"payment_wallet_toggle:{token}", state
    )
    assert [(answer.text, answer.show_alert) for answer in answers] == [
        (translate("payment-no-cards"), True)
    ]
    assert output.screens == 0

    db_session.add(make_active_card())
    await db_session.commit()
    for payment_mode in ("full", "partial", "full_remaining", "cash"):
        await state.update_data(payment_mode=payment_mode)
        output, answers = await press_toggle(
            PARTNER_TG, f"payment_wallet_toggle:{token}", state
        )
        assert len(answers) == 1, payment_mode
        assert answers[0].text is None
        assert output.screens == 1
        output.assert_no_real_flight_names()


# ---------------------------------------------------------------------------
# profile.py -> make_payment.py
# ---------------------------------------------------------------------------


async def test_payment_reminder_buttons_resolve_through_the_payment_flow(
    db_session: AsyncSession, redis_client: Redis, client_service: ClientService
) -> None:
    await seed_world(db_session, redis_client)
    # The reminder's flight is known only from the client's own transaction.
    await prime_sheets(redis_client, PARTNER_CODE, [MASKED_FLIGHT])
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
    client = await client_service.get_client(PARTNER_TG, db_session)
    scope = client_token_scope(client.id)
    token = flight_token(UNMASKED_FLIGHT, scope)

    bot = AsyncMock()
    await profile.payment_reminder_handler(
        make_message(bot, PARTNER_TG),
        _=translate,
        session=db_session,
        client_service=client_service,
        state=make_state(PARTNER_TG),
    )
    reminder = capture(bot)
    reminder.assert_no_real_flight_names()
    assert reminder.callbacks("pay_flight:") == [f"pay_flight:{token}"]

    payable = await make_payment._client_payable_flights(
        db_session, client, redis_client
    )
    assert resolve_flight_token(token, payable, scope) == UNMASKED_FLIGHT
    assert resolve_flight_token(flight_token(LONE_FLIGHT_A, scope), payable, scope) is None

    state = make_state(PARTNER_TG)
    bot = AsyncMock()
    await make_payment.payment_flight_selected(
        make_callback(bot, PARTNER_TG, f"pay_flight:{token}"),
        _=translate,
        session=db_session,
        client_service=client_service,
        state=state,
        redis=redis_client,
    )
    selection = capture(bot)
    selection.assert_no_real_flight_names()
    assert (await state.get_data())["worksheet"] == UNMASKED_FLIGHT
    assert selection.callbacks("payment_type:cash:") == [f"payment_type:cash:{token}"]


# ---------------------------------------------------------------------------
# delivery_request.py
# ---------------------------------------------------------------------------


async def offer_paid_flights(
    session: AsyncSession,
    redis: Redis,
    client_service: ClientService,
    state: FSMContext,
    paid: tuple[str, ...],
) -> Output:
    """Seed paid transactions for the partner client and open flight selection."""
    for flight in paid:
        session.add(
            make_transaction(
                PARTNER_TG, PARTNER_CODE, flight, status="paid", remaining=Decimal("0")
            )
        )
    await session.commit()
    await state.update_data(delivery_type="yandex")

    bot = AsyncMock()
    await delivery_request.profile_confirmation_yes(
        make_callback(bot, PARTNER_TG, "confirm_profile_yes"),
        _=translate,
        session=session,
        client_service=client_service,
        redis=redis,
        state=state,
    )
    return capture(bot)


async def test_delivery_selection_accepts_only_offered_paid_flights(
    db_session: AsyncSession, redis_client: Redis, client_service: ClientService
) -> None:
    await seed_world(db_session, redis_client)
    scope = await token_scope(db_session, client_service, PARTNER_TG)
    lone_scope = await token_scope(db_session, client_service, LONE_TG)
    state = make_state(PARTNER_TG)
    offered_buttons = [
        f"select_flight:{flight_token(MASKED_FLIGHT, scope)}",
        f"select_flight:{flight_token(UNMASKED_FLIGHT, scope)}",
    ]

    offer = await offer_paid_flights(
        db_session, redis_client, client_service, state, (MASKED_FLIGHT, UNMASKED_FLIGHT)
    )
    offer.assert_no_real_flight_names()
    assert offer.callbacks("select_flight:") == offered_buttons
    assert any(MASK in text for text in offer.texts)
    paid_flights = (await state.get_data())["paid_flights"]
    assert [flight["flight_name"] for flight in paid_flights] == [
        MASKED_FLIGHT,
        UNMASKED_FLIGHT,
    ]

    async def press(data: str) -> Output:
        bot = AsyncMock()
        await delivery_request.process_flight_selection(
            make_callback(bot, PARTNER_TG, data),
            _=translate,
            session=db_session,
            client_service=client_service,
            state=state,
        )
        return capture(bot)

    toggled = await press(offered_buttons[1])
    toggled.assert_no_real_flight_names()
    assert toggled.callbacks("select_flight:") == offered_buttons
    assert (await state.get_data())["selected_flights"] == [UNMASKED_FLIGHT]

    for data in (
        f"select_flight:{FORGED_TOKEN}",
        f"select_flight:{flight_token(LONE_FLIGHT_A, lone_scope)}",
        f"select_flight:{flight_token(MASKED_FLIGHT, lone_scope)}",
        f"select_flight:{LONE_FLIGHT_A}",
        f"select_flight:{MASKED_FLIGHT}",
    ):
        assert_rejected(await press(data))
        assert (await state.get_data())["selected_flights"] == [UNMASKED_FLIGHT]

    (await press(offered_buttons[0])).assert_no_real_flight_names()
    assert (await state.get_data())["selected_flights"] == [
        UNMASKED_FLIGHT,
        MASKED_FLIGHT,
    ]


async def test_done_button_reaches_the_submission_step(
    db_session: AsyncSession, redis_client: Redis, client_service: ClientService
) -> None:
    await seed_world(db_session, redis_client)
    scope = await token_scope(db_session, client_service, PARTNER_TG)
    state = make_state(PARTNER_TG)
    await offer_paid_flights(
        db_session, redis_client, client_service, state, (UNMASKED_FLIGHT,)
    )

    bot = AsyncMock()
    await delivery_request.process_flight_selection(
        make_callback(bot, PARTNER_TG, f"select_flight:{flight_token(UNMASKED_FLIGHT, scope)}"),
        _=translate,
        session=db_session,
        client_service=client_service,
        state=state,
    )
    (done_data,) = [
        data for data in capture(bot).callback_data if not data.startswith("select_flight:")
    ]

    # Route the pressed button the way the dispatcher would: through the
    # Done handler's own state and data filters.
    (done_handler,) = [
        handler
        for handler in delivery_request.delivery_request_router.callback_query.handlers
        if handler.callback is delivery_request.process_flight_selection_done
    ]
    bot = AsyncMock()
    done = make_callback(bot, PARTNER_TG, done_data)
    matched, _filter_data = await done_handler.check(done, raw_state=await state.get_state())
    assert matched, f"the Done button sends {done_data!r}, which no Done filter accepts"

    await done_handler.call(
        done,
        _=translate,
        session=db_session,
        client_service=client_service,
        state=state,
        bot=bot,
        redis=redis_client,
    )
    submitted = capture(bot)
    submitted.assert_no_real_flight_names()
    assert submitted.texts == [translate("delivery-request-submitted")]
    assert await state.get_state() is None
    bot.send_message.assert_awaited_once()
    assert (
        bot.send_message.await_args.kwargs["chat_id"]
        == config.telegram.YANDEX_DELIVERY_REQUEST_CHANNEL_ID
    )
    requests = (await db_session.execute(select(DeliveryRequest))).scalars().all()
    assert [json.loads(request.flight_names) for request in requests] == [
        [UNMASKED_FLIGHT]
    ]
