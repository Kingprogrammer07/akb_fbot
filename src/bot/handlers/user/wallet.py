"""Wallet (Hamyon) handler for user wallet operations."""

import hashlib
import logging
import time
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_private_chat import IsPrivate
from src.bot.filters.is_logged_in import ClientExists, IsRegistered, IsLoggedIn
from src.bot.utils.decorators import handle_errors
from src.bot.states.wallet_states import WalletStates
from src.infrastructure.services import ClientService, UserPaymentCardService
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.user_payment_card import UserPaymentCardDAO
from src.infrastructure.database.dao.payment_card import PaymentCardDAO
from src.infrastructure.tools.money_utils import parse_money
from src.config import config

logger = logging.getLogger(__name__)

wallet_router = Router(name="wallet")

MIN_REFUND_AMOUNT = 5000
MAX_CARDS_PER_USER = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def mask_card_number(card_number: str) -> str:
    """Mask card number showing only last 4 digits."""
    if len(card_number) >= 4:
        return f"**** **** **** {card_number[-4:]}"
    return card_number


async def get_wallet_balance(session: AsyncSession, client_code: str) -> float:
    return await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
        session, client_code
    )


def _balance_text(_, balance: float) -> str:
    if balance > 0:
        return _("wallet-balance-positive", balance=f"{balance:,.2f}")
    if balance < 0:
        return _("wallet-balance-negative", balance=f"{abs(balance):,.2f}")
    return _("wallet-balance-zero")


def build_wallet_main_keyboard(_, balance: float) -> InlineKeyboardBuilder:
    """Build main wallet screen inline keyboard based on balance."""
    builder = InlineKeyboardBuilder()
    if balance > 0:
        builder.button(text=_("btn-wallet-use-balance"),    callback_data="wallet:use_balance")
        builder.button(text=_("btn-wallet-request-refund"), callback_data="wallet:request_refund")
    elif balance < 0:
        builder.button(text=_("btn-wallet-pay-debt"), callback_data="wallet:pay_debt")
    builder.button(text=_("btn-wallet-my-cards"), callback_data="wallet:my_cards")
    builder.adjust(1)
    return builder


# ---------------------------------------------------------------------------
# Handlers: Main screen
# ---------------------------------------------------------------------------

@wallet_router.message(
    IsPrivate(), ClientExists(), IsRegistered(), IsLoggedIn(),
    F.text.in_(["💰 Hamyon", "💰 Кошелек"]),
)
@handle_errors
async def wallet_main_handler(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
):
    """Show wallet main screen with balance and options."""
    await state.clear()

    client = await client_service.get_client(message.from_user.id, session)
    if not client:
        await message.answer(_("error-occurred"))
        return

    balance  = await get_wallet_balance(session, client.client_code)
    keyboard = build_wallet_main_keyboard(_, balance)
    await message.answer(_balance_text(_, balance), reply_markup=keyboard.as_markup())


@wallet_router.callback_query(F.data == "wallet:back_main")
async def wallet_back_main_handler(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
):
    """Go back to wallet main screen."""
    await callback.answer()
    await state.clear()

    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await callback.message.answer(_("error-occurred"))
        return

    balance  = await get_wallet_balance(session, client.client_code)
    keyboard = build_wallet_main_keyboard(_, balance)
    await callback.message.answer(_balance_text(_, balance), reply_markup=keyboard.as_markup())


# ---------------------------------------------------------------------------
# Handlers: Use balance info
# ---------------------------------------------------------------------------

@wallet_router.callback_query(F.data == "wallet:use_balance")
async def wallet_use_balance_handler(callback: CallbackQuery, _: callable):
    await callback.answer()
    await callback.message.answer(_("wallet-use-balance-info"))


# ---------------------------------------------------------------------------
# Handlers: Refund flow
# ---------------------------------------------------------------------------

@wallet_router.callback_query(F.data == "wallet:request_refund")
async def wallet_refund_start_handler(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
):
    """Start refund request flow."""
    await callback.answer()

    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await callback.message.answer(_("error-occurred"))
        return

    balance = await get_wallet_balance(session, client.client_code)
    if balance < MIN_REFUND_AMOUNT:
        await callback.message.answer(
            _("wallet-refund-min-error", min_amount=f"{MIN_REFUND_AMOUNT:,.2f}")
        )
        return

    await state.update_data(refund_balance=balance)

    cards   = await UserPaymentCardService.get_user_cards(callback.from_user.id, session)
    builder = InlineKeyboardBuilder()

    for card in cards:
        masked = mask_card_number(card.card_number)
        holder = card.holder_name or _("wallet-card-no-holder")
        builder.button(
            text=f"💳 {masked} ({holder})",
            callback_data=f"wallet:refund_card:{card.id}",
        )

    builder.button(text=_("btn-wallet-new-card"), callback_data="wallet:refund_new_card")
    builder.button(text=_("btn-cancel"),          callback_data="wallet:back_main")
    builder.adjust(1)

    await callback.message.answer(
        _("wallet-refund-select-card"), reply_markup=builder.as_markup()
    )


@wallet_router.callback_query(F.data.startswith("wallet:refund_card:"))
async def wallet_refund_select_card_handler(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    state: FSMContext,
):
    """Handle saved card selection for refund."""
    await callback.answer()

    card_id = int(callback.data.split(":")[2])
    card    = await UserPaymentCardDAO.get_by_id(session, card_id)
    if not card or card.telegram_id != callback.from_user.id:
        await callback.message.answer(_("error-occurred"))
        return

    await state.update_data(
        refund_card_id=card.id,
        refund_card_number=card.card_number,
        refund_card_holder=card.holder_name,
    )

    data    = await state.get_data()
    balance = data.get("refund_balance", 0)
    await callback.message.answer(
        _("wallet-refund-enter-amount", balance=f"{balance:,.2f}")
    )
    await state.set_state(WalletStates.waiting_for_refund_amount)


@wallet_router.callback_query(F.data == "wallet:refund_new_card")
async def wallet_refund_new_card_handler(
    callback: CallbackQuery, _: callable, state: FSMContext
):
    """Start new card entry for refund."""
    await callback.answer()
    await callback.message.answer(_("wallet-refund-enter-card-number"))
    await state.set_state(WalletStates.waiting_for_refund_card_number)


@wallet_router.message(WalletStates.waiting_for_refund_card_number, F.text)
async def wallet_refund_card_number_handler(
    message: Message, _: callable, state: FSMContext
):
    """Handle card number input for refund."""
    card_number = message.text.strip().replace(" ", "").replace("-", "")
    if not card_number.isdigit() or len(card_number) != 16:
        await message.answer(_("wallet-card-invalid-number"))
        return

    await state.update_data(refund_card_number=card_number)
    await message.answer(_("wallet-refund-enter-holder-name"))
    await state.set_state(WalletStates.waiting_for_refund_holder_name)


@wallet_router.message(WalletStates.waiting_for_refund_holder_name, F.text)
async def wallet_refund_holder_name_handler(
    message: Message, _: callable, state: FSMContext
):
    """Handle holder name input for refund."""
    holder_name = message.text.strip()
    if not (2 <= len(holder_name) <= 255):
        await message.answer(_("wallet-card-invalid-holder"))
        return

    await state.update_data(refund_card_holder=holder_name)

    data    = await state.get_data()
    balance = data.get("refund_balance", 0)
    await message.answer(_("wallet-refund-enter-amount", balance=f"{balance:,.2f}"))
    await state.set_state(WalletStates.waiting_for_refund_amount)


@wallet_router.message(WalletStates.waiting_for_refund_amount, F.text)
async def wallet_refund_amount_handler(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
):
    """Handle refund amount input."""
    try:
        amount = parse_money(message.text)
    except (ValueError, TypeError):
        await session.rollback()
        await message.answer(_("wallet-refund-invalid-amount"))
        return

    client = await client_service.get_client(message.from_user.id, session)
    if not client:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    balance = await get_wallet_balance(session, client.client_code)

    if amount < MIN_REFUND_AMOUNT:
        await message.answer(
            _("wallet-refund-min-error", min_amount=f"{MIN_REFUND_AMOUNT:,.2f}")
        )
        return

    if amount > balance:
        await message.answer(
            _("wallet-refund-exceeds-balance", balance=f"{balance:,.2f}")
        )
        return

    await state.update_data(refund_amount=amount)

    data        = await state.get_data()
    card_number = data.get("refund_card_number", "")
    holder_name = data.get("refund_card_holder", "")

    builder = InlineKeyboardBuilder()
    builder.button(text=_("btn-confirm"), callback_data="wallet:refund_confirm")
    builder.button(text=_("btn-cancel"),  callback_data="wallet:back_main")
    builder.adjust(1)

    await message.answer(
        _("wallet-refund-confirm",
          amount=f"{amount:,.2f}",
          card=mask_card_number(card_number),
          holder=holder_name),
        reply_markup=builder.as_markup(),
    )


@wallet_router.callback_query(F.data == "wallet:refund_confirm")
async def wallet_refund_confirm_handler(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    bot: Bot,
):
    """Confirm refund request and send to admin channel."""
    await callback.answer()

    data        = await state.get_data()
    amount      = data.get("refund_amount", 0)
    card_number = data.get("refund_card_number", "")
    holder_name = data.get("refund_card_holder", "")
    card_id     = data.get("refund_card_id")

    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await callback.message.answer(_("error-occurred"))
        await state.clear()
        return

    request_key = hashlib.md5(f"{callback.from_user.id}:{time.time()}".encode()).hexdigest()[:8]

    admin_text = _(
        "wallet-admin-refund-request",
        client_code=client.client_code,
        full_name=client.full_name or "N/A",
        phone=client.phone or "N/A",
        telegram_id=str(callback.from_user.id),
        amount=f"{amount:,.2f}",
        card=card_number,
        holder=holder_name,
    )

    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("btn-admin-approve-refund"),
        callback_data=f"refund_approve:{callback.from_user.id}:{request_key}",
    )
    builder.button(
        text=_("btn-admin-reject-refund"),
        callback_data=f"refund_reject:{callback.from_user.id}",
    )
    builder.adjust(1)

    try:
        await bot.send_message(
            chat_id=config.telegram.REFUND_CHANNEL_ID,
            text=admin_text,
            reply_markup=builder.as_markup(),
        )
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to send refund request to admin: {e}")
        await callback.message.answer(_("error-occurred"))
        await state.clear()
        return

    # Save new card if not already saved and under limit
    if not card_id and card_number:
        exists = await UserPaymentCardDAO.check_duplicate(
            session, callback.from_user.id, card_number
        )
        if not exists:
            count = await UserPaymentCardDAO.count_active_by_telegram_id(
                session, callback.from_user.id
            )
            if count < MAX_CARDS_PER_USER:
                await UserPaymentCardService.create_card(
                    callback.from_user.id, card_number, holder_name, session
                )
                await session.commit()

    await callback.message.answer(_("wallet-refund-submitted"))
    await state.clear()


# ---------------------------------------------------------------------------
# Handlers: Debt payment flow
# ---------------------------------------------------------------------------

@wallet_router.callback_query(F.data == "wallet:pay_debt")
async def wallet_pay_debt_handler(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
):
    """Start debt payment flow."""
    await callback.answer()

    client = await client_service.get_client(callback.from_user.id, session)
    if not client:
        await callback.message.answer(_("error-occurred"))
        return

    balance = await get_wallet_balance(session, client.client_code)
    if balance >= 0:
        await callback.message.answer(_("wallet-no-debt"))
        return

    debt = abs(balance)
    card = await PaymentCardDAO.get_random_active(session)
    if not card:
        await callback.message.answer(_("wallet-debt-no-card"))
        return

    await state.update_data(
        debt_amount=debt,
        debt_card_number=card.card_number,
        debt_card_holder=card.full_name,
    )

    await callback.message.answer(
        _("wallet-debt-info",
          debt=f"{debt:,.2f}",
          card_number=card.card_number,
          card_holder=card.full_name)
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=_("btn-wallet-send-receipt"), callback_data="wallet:debt_send_receipt")
    builder.button(text=_("btn-cancel"),              callback_data="wallet:back_main")
    builder.adjust(1)

    await callback.message.answer(
        _("wallet-debt-send-receipt-prompt"), reply_markup=builder.as_markup()
    )


@wallet_router.callback_query(F.data == "wallet:debt_send_receipt")
async def wallet_debt_send_receipt_handler(
    callback: CallbackQuery, _: callable, state: FSMContext
):
    """Prompt user to send debt payment receipt."""
    await callback.answer()
    await callback.message.answer(_("wallet-debt-upload-receipt"))
    await state.set_state(WalletStates.waiting_for_debt_receipt)


@wallet_router.message(
    WalletStates.waiting_for_debt_receipt,
    F.content_type.in_(["photo", "document"]),
)
async def wallet_debt_receipt_handler(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    bot: Bot,
):
    """Handle debt payment receipt upload."""
    client = await client_service.get_client(message.from_user.id, session)
    if not client:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    data = await state.get_data()
    debt = data.get("debt_amount", 0)

    admin_text = _(
        "wallet-admin-debt-receipt",
        client_code=client.client_code,
        full_name=client.full_name or "N/A",
        phone=client.phone or "N/A",
        telegram_id=str(message.from_user.id),
        debt=f"{debt:,.2f}",
    )

    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("btn-admin-approve-debt"),
        callback_data=f"debt_approve:{message.from_user.id}:{client.client_code}",
    )
    builder.button(
        text=_("btn-admin-reject-debt"),
        callback_data=f"debt_reject:{message.from_user.id}",
    )
    builder.adjust(1)

    try:
        if message.photo:
            await bot.send_photo(
                chat_id=config.telegram.DEBT_GROUP_ID,
                photo=message.photo[-1].file_id,
                caption=admin_text,
                reply_markup=builder.as_markup(),
            )
        elif message.document:
            await bot.send_document(
                chat_id=config.telegram.DEBT_GROUP_ID,
                document=message.document.file_id,
                caption=admin_text,
                reply_markup=builder.as_markup(),
            )
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to send debt receipt to admin: {e}")
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    await message.answer(_("wallet-debt-submitted"))
    await state.clear()


# ---------------------------------------------------------------------------
# Handlers: Card management
# ---------------------------------------------------------------------------

@wallet_router.callback_query(F.data == "wallet:my_cards")
async def wallet_my_cards_handler(
    callback: CallbackQuery, _: callable, session: AsyncSession
):
    """Show user's saved cards."""
    await callback.answer()

    cards   = await UserPaymentCardService.get_user_cards(callback.from_user.id, session)
    builder = InlineKeyboardBuilder()

    if not cards:
        builder.button(text=_("btn-wallet-add-card"), callback_data="wallet:add_card")
        builder.button(text=_("btn-back"),             callback_data="wallet:back_main")
        builder.adjust(1)
        await callback.message.answer(_("wallet-no-cards"), reply_markup=builder.as_markup())
        return

    lines = [_("wallet-my-cards-header"), ""]
    for i, card in enumerate(cards, 1):
        masked = mask_card_number(card.card_number)
        holder = card.holder_name or _("wallet-card-no-holder")
        lines.append(f"{i}. {masked}\n   {holder}")

    for card in cards:
        builder.button(
            text=f"🗑 {mask_card_number(card.card_number)}",
            callback_data=f"wallet:delete_card:{card.id}",
        )

    if len(cards) < MAX_CARDS_PER_USER:
        builder.button(text=_("btn-wallet-add-card"), callback_data="wallet:add_card")

    builder.button(text=_("btn-back"), callback_data="wallet:back_main")
    builder.adjust(1)

    await callback.message.answer("\n".join(lines), reply_markup=builder.as_markup())


@wallet_router.callback_query(F.data == "wallet:add_card")
async def wallet_add_card_handler(
    callback: CallbackQuery, _: callable, session: AsyncSession, state: FSMContext
):
    """Start add card flow."""
    await callback.answer()

    count = await UserPaymentCardDAO.count_active_by_telegram_id(
        session, callback.from_user.id
    )
    if count >= MAX_CARDS_PER_USER:
        await callback.message.answer(
            _("wallet-card-limit-reached", limit=MAX_CARDS_PER_USER)
        )
        return

    await callback.message.answer(_("wallet-add-card-number"))
    await state.set_state(WalletStates.waiting_for_new_card_number)


@wallet_router.message(WalletStates.waiting_for_new_card_number, F.text)
async def wallet_add_card_number_handler(
    message: Message, _: callable, session: AsyncSession, state: FSMContext
):
    """Handle new card number input."""
    card_number = message.text.strip().replace(" ", "").replace("-", "")
    if not card_number.isdigit() or len(card_number) != 16:
        await message.answer(_("wallet-card-invalid-number"))
        return

    exists = await UserPaymentCardDAO.check_duplicate(
        session, message.from_user.id, card_number
    )
    if exists:
        await message.answer(_("wallet-card-duplicate"))
        return

    await state.update_data(new_card_number=card_number)
    await message.answer(_("wallet-add-card-holder"))
    await state.set_state(WalletStates.waiting_for_new_card_holder)


@wallet_router.message(WalletStates.waiting_for_new_card_holder, F.text)
async def wallet_add_card_holder_handler(
    message: Message, _: callable, session: AsyncSession, state: FSMContext
):
    """Handle new card holder name input."""
    holder_name = message.text.strip()
    if not (2 <= len(holder_name) <= 255):
        await message.answer(_("wallet-card-invalid-holder"))
        return

    data        = await state.get_data()
    card_number = data.get("new_card_number", "")

    await UserPaymentCardService.create_card(
        message.from_user.id, card_number, holder_name, session
    )
    await session.commit()
    await message.answer(_("wallet-card-added"))
    await state.clear()


@wallet_router.callback_query(F.data.startswith("wallet:delete_card:"))
async def wallet_delete_card_handler(
    callback: CallbackQuery, _: callable, session: AsyncSession
):
    """Delete a user's card."""
    await callback.answer()

    card_id = int(callback.data.split(":")[2])
    deleted = await UserPaymentCardService.delete_card(
        card_id, callback.from_user.id, session
    )
    await session.commit()

    await callback.message.answer(
        _("wallet-card-deleted") if deleted else _("error-occurred")
    )