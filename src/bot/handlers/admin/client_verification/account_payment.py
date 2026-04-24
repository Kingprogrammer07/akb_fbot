"""Account payment handlers (Click/Payme) for client verification."""
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_admin import IsAdmin
from src.infrastructure.services.client import ClientService
from src.infrastructure.services.client_transaction import ClientTransactionService
from src.infrastructure.services.payment_allocation import PaymentAllocationService
from src.infrastructure.tools.money_utils import parse_money
from src.bot.utils.decorators import handle_errors
from src.config import config

from .utils import safe_answer_callback, VERIFICATION_CONTEXT
from .paid import show_payments_list

router = Router()


class VerificationAccountPaymentState(StatesGroup):
    """State for account payment approval in verification with amount input."""
    waiting_for_amount = State()


@router.callback_query(F.data.startswith("v:ap:"), IsAdmin())
@handle_errors
async def account_payment_select_provider(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    transaction_service: ClientTransactionService
):
    """
    Show provider selection for account payment (Click/Payme).
    Callback format: v:ap:{transaction_id}
    """
    parts = callback.data.split(":")
    if len(parts) < 3:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    transaction_id = int(parts[2])

    from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
    transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)

    if not transaction:
        await safe_answer_callback(callback, _("admin-account-payment-transaction-not-found"), show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("btn-account-payment-click"),
        callback_data=f"v:apc:{transaction_id}:click"
    )
    builder.button(
        text=_("btn-account-payment-payme"),
        callback_data=f"v:apc:{transaction_id}:payme"
    )
    builder.button(
        text=_("btn-account-payment-cancel"),
        callback_data=f"v:apcnl:{transaction_id}"
    )
    builder.adjust(2, 1)

    await callback.message.answer(
        _("admin-account-payment-select-provider"),
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await safe_answer_callback(callback)


@router.callback_query(F.data.startswith("v:apc:"), IsAdmin())
@handle_errors
async def account_payment_confirm(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    transaction_service: ClientTransactionService
):
    """
    Show confirmation dialog for account payment.
    Callback format: v:apc:{transaction_id}:{provider}
    """
    parts = callback.data.split(":")
    if len(parts) < 4:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    transaction_id = int(parts[2])
    provider = parts[3]

    if provider not in ['click', 'payme']:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
    transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)

    if not transaction:
        await safe_answer_callback(callback, _("admin-account-payment-transaction-not-found"), show_alert=True)
        return

    if transaction.payment_status == "partial" and transaction.remaining_amount:
        amount = float(transaction.remaining_amount)
    else:
        amount = float(transaction.summa or 0)

    provider_display = "Click" if provider == "click" else "Payme"

    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Ha",
        callback_data=f"v:apyes:{transaction_id}:{provider}"
    )
    builder.button(
        text="❌ Yo'q",
        callback_data=f"v:apno:{transaction_id}"
    )
    builder.adjust(2)

    confirmation_text = _("admin-account-payment-confirm",
        amount=f"{amount:.0f}",
        provider=provider_display,
        transaction_id=transaction_id
    )

    await callback.message.edit_text(
        confirmation_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await safe_answer_callback(callback)


@router.callback_query(F.data.startswith("v:apno:"), IsAdmin())
@handle_errors
async def account_payment_cancel(
    callback: CallbackQuery,
    _: callable
):
    """
    Cancel account payment confirmation.
    Callback format: v:apno:{transaction_id}
    """
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(_("admin-account-payment-cancelled"))
    await safe_answer_callback(callback)


@router.callback_query(F.data.startswith("v:apcnl:"), IsAdmin())
@handle_errors
async def account_payment_cancel_provider_selection(
    callback: CallbackQuery,
    _: callable
):
    """
    Cancel provider selection.
    Callback format: v:apcnl:{transaction_id}
    """
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(_("admin-account-payment-cancelled"))
    await safe_answer_callback(callback)


@router.callback_query(F.data.startswith("v:apyes:"), IsAdmin())
@handle_errors
async def account_payment_start(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext
):
    """
    Start account payment confirmation - ask for amount input.
    Callback format: v:apyes:{transaction_id}:{provider}
    """
    await safe_answer_callback(callback)

    parts = callback.data.split(":")
    if len(parts) < 4:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    transaction_id = int(parts[2])
    provider = parts[3]

    if provider not in ['click', 'payme']:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
    from src.infrastructure.database.dao.client_payment_event import ClientPaymentEventDAO

    transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)

    if not transaction:
        await safe_answer_callback(callback, _("admin-account-payment-transaction-not-found"), show_alert=True)
        return

    client = await client_service.get_client_by_code(transaction.client_code, session)
    if not client:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    # Calculate expected amount
    if transaction.payment_status == "partial" and transaction.remaining_amount:
        expected_amount = float(transaction.remaining_amount)
    elif transaction.total_amount:
        expected_amount = float(transaction.total_amount)
    else:
        expected_amount = float(transaction.summa or 0)

    # Check for duplicate provider events
    existing_events = await ClientPaymentEventDAO.get_by_transaction_id(session, transaction_id)
    for event in existing_events:
        if event.payment_provider == provider:
            await safe_answer_callback(callback, _("admin-account-payment-already-confirmed"), show_alert=True)
            return

    # Store context in FSM state
    await state.update_data(
        vapyes_transaction_id=transaction_id,
        vapyes_provider=provider,
        vapyes_client_code=transaction.client_code,
        vapyes_expected_amount=expected_amount,
        vapyes_flight=transaction.reys,
        vapyes_message_id=callback.message.message_id,
        vapyes_chat_id=callback.message.chat.id
    )

    provider_display = "Click" if provider == "click" else "Payme"

    # Ask for amount input
    await callback.message.answer(
        _("admin-account-payment-enter-amount", expected=f"{expected_amount:,.0f}", provider=provider_display)
    )
    await callback.message.answer(
        f"ℹ️ Istalgan summani kiriting:\n"
        f"• Ko'proq → ortiqcha balansga o'tadi\n"
        f"• Kamroq → qisman to'lov sifatida saqlanadi\n"
        f"• Kutilgan summa: {expected_amount:,.2f} so'm"
    )
    await state.set_state(VerificationAccountPaymentState.waiting_for_amount)


@router.message(IsAdmin(), VerificationAccountPaymentState.waiting_for_amount, F.text)
async def account_payment_amount_received(
    message: Message,
    _: callable,
    session: AsyncSession,
    transaction_service: ClientTransactionService,
    client_service: ClientService,
    state: FSMContext,
    bot: Bot
):
    """Process account payment amount from admin in verification."""
    # Check for cancel
    if message.text.strip().lower() in ["/cancel", "bekor", "отмена"]:
        await message.answer(_("admin-payment-cancelled"))
        await state.clear()
        return

    # Parse amount
    try:
        amount = parse_money(message.text)
    except (ValueError, TypeError):
        await session.rollback()
        await message.answer(_("admin-payment-invalid-amount"))
        return

    if amount <= 0:
        await message.answer(_("admin-payment-invalid-amount"))
        return

    # Get stored context
    data = await state.get_data()
    transaction_id = data.get("vapyes_transaction_id")
    provider = data.get("vapyes_provider")
    client_code = data.get("vapyes_client_code")
    expected_amount = data.get("vapyes_expected_amount", 0)
    flight_name = data.get("vapyes_flight")
    admin_message_id = data.get("vapyes_message_id")
    admin_chat_id = data.get("vapyes_chat_id")

    if not transaction_id or not provider:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
    from src.infrastructure.database.dao.client_payment_event import ClientPaymentEventDAO
    from src.infrastructure.tools.datetime_utils import get_current_time, to_tashkent

    transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)

    if not transaction:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    client = await client_service.get_client_by_code(transaction.client_code, session)
    if not client:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    try:
        # Create payment event with admin-entered amount
        await ClientPaymentEventDAO.create(
            session=session,
            transaction_id=transaction.id,
            payment_type="online",
            amount=amount,
            approved_by_admin_id=message.from_user.id,
            payment_provider=provider
        )

        # Recalculate payment_balance_difference using PaymentAllocationService
        await PaymentAllocationService.recalculate_transaction_balance(
            session, transaction.id
        )

        # Refresh to get updated values
        await session.refresh(transaction)

        # payment_balance_difference already updated by recalculate_transaction_balance

        await session.commit()

        # Update original admin message
        if admin_message_id and admin_chat_id:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=admin_chat_id,
                    message_id=admin_message_id,
                    reply_markup=None
                )
            except Exception as e:
                await session.rollback()
                print(f"Failed to update admin message: {e}")

        # Send channel notification
        channel_id = config.telegram.TOLOV_TASDIQLANGAN_CHANNEL_ID
        provider_display = "Click" if provider == "click" else "Payme"

        current_time = get_current_time()
        tashkent_time = to_tashkent(current_time)
        formatted_time = tashkent_time.strftime("%Y-%m-%d %H:%M:%S")

        admin_name = message.from_user.full_name
        if message.from_user.username:
            admin_name = f"@{message.from_user.username}"

        flight_display = flight_name if flight_name else "Noma'lum"

        channel_text = _("account-payment-channel-notification",
            client_code=client.client_code,
            transaction_id=transaction.id,
            flight=flight_display,
            amount=f"{amount:.0f}",
            provider=provider_display,
            admin_name=admin_name,
            time=formatted_time
        )

        try:
            await bot.send_message(
                chat_id=channel_id,
                text=channel_text,
                parse_mode="HTML"
            )
        except Exception as e:
            await session.rollback()
            print(f"Failed to send account payment notification to channel: {e}")

        await message.answer(_("admin-payment-success"))

    except Exception as e:
        await session.rollback()
        print(f"Error in account payment execution: {e}")
        await message.answer(_("error-occurred"))

    await state.clear()
