"""Wallet admin handlers for refund and debt approval."""
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.bot.filters.is_admin import IsAdmin
from src.bot.states.wallet_states import WalletAdminStates
from src.infrastructure.services import ClientService, PaymentAllocationService
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO

wallet_admin_router = Router(name="wallet_admin")


async def safe_answer_callback(
    callback: CallbackQuery,
    text: str = "",
    show_alert: bool = False
) -> None:
    """Safely answer callback query, handling timeouts."""
    try:
        if callback.bot:
            await callback.bot.answer_callback_query(
                callback_query_id=callback.id,
                text=text,
                show_alert=show_alert
            )
    except Exception as e:
        print(f"Failed to answer callback safely: {e}")


# ==================== Refund Approval ====================

@wallet_admin_router.callback_query(IsAdmin(), F.data.startswith("refund_approve:"))
async def refund_approve_handler(
    callback: CallbackQuery,
    _: callable,
    state: FSMContext
):
    """Start refund approval - ask for actual amount."""
    await safe_answer_callback(callback)

    # Parse: refund_approve:telegram_id:key
    parts = callback.data.split(":")
    if len(parts) != 3:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    telegram_id = int(parts[1])
    request_key = parts[2]

    await state.update_data(
        refund_telegram_id=telegram_id,
        refund_request_key=request_key,
        refund_message_id=callback.message.message_id,
        refund_chat_id=callback.message.chat.id
    )

    await callback.message.answer(_("wallet-admin-refund-enter-amount"))
    await state.set_state(WalletAdminStates.waiting_for_refund_actual_amount)


@wallet_admin_router.message(IsAdmin(), WalletAdminStates.waiting_for_refund_actual_amount, F.text)
async def refund_amount_received_handler(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    bot: Bot
):
    """Process refund amount from admin."""
    from src.infrastructure.tools.money_utils import parse_money

    # Check for cancel
    if message.text.strip().lower() in ["/cancel", "bekor", "отмена"]:
        await message.answer(_("wallet-admin-cancelled"))
        await state.clear()
        return

    try:
        amount = parse_money(message.text)
    except (ValueError, TypeError):
        await session.rollback()
        await message.answer(_("wallet-admin-invalid-amount"))
        return

    if amount <= 0:
        await message.answer(_("wallet-admin-invalid-amount"))
        return

    data = await state.get_data()
    telegram_id = data.get("refund_telegram_id")
    message_id = data.get("refund_message_id")
    chat_id = data.get("refund_chat_id")

    if not telegram_id:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    # Get client
    client = await client_service.get_client(telegram_id, session)
    if not client:
        await message.answer(_("wallet-admin-client-not-found"))
        await state.clear()
        return

    # Check balance
    balance = await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
        session, client.client_code
    )

    if amount > balance:
        await message.answer(
            _("wallet-admin-refund-exceeds-balance",
              balance=f"{balance:,.0f}",
              amount=f"{amount:,.0f}")
        )
        return

    # Process refund using existing credits (NO WALLET_ADJ)
    remaining = await PaymentAllocationService.process_refund(
        session=session,
        client_code=client.client_code,
        amount=amount
    )
    
    # If remaining > 0 (should not happen due to balance check), 
    # it means there was a race condition or balance mismatch.
    # In this case we can't fully refund.
    if remaining > 0:
        # Just log it, we deducted what we could.
        print(f"WARNING: Could not fully refund {amount}, remaining: {remaining}")
    await session.commit()

    # Notify user
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=_("wallet-refund-approved-user", amount=f"{amount:,.0f}")
        )
    except Exception as e:
        await session.rollback()
        print(f"Failed to notify user about refund: {e}")

    # Update original admin message
    if message_id and chat_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None
            )
            await bot.send_message(
                chat_id=chat_id,
                text=_("wallet-admin-refund-approved",
                       client_code=client.client_code,
                       amount=f"{amount:,.0f}",
                       admin_name=message.from_user.full_name),
                reply_to_message_id=message_id
            )
        except Exception as e:
            await session.rollback()
            print(f"Failed to update admin message: {e}")

    await message.answer(_("wallet-admin-refund-success"))
    await state.clear()


@wallet_admin_router.callback_query(IsAdmin(), F.data.startswith("refund_reject:"))
async def refund_reject_handler(
    callback: CallbackQuery,
    _: callable,
    bot: Bot
):
    """Reject refund request."""
    await safe_answer_callback(callback, _("wallet-admin-rejected"), show_alert=True)

    # Parse: refund_reject:telegram_id
    parts = callback.data.split(":")
    if len(parts) != 2:
        return

    telegram_id = int(parts[1])

    # Notify user
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=_("wallet-refund-rejected-user")
        )
    except Exception as e:
        print(f"Failed to notify user about refund rejection: {e}")

    # Update admin message
    try:
        if callback.message.text:
            await callback.message.edit_text(
                callback.message.text + f"\n\n❌ Rad etildi: {callback.from_user.full_name}",
                reply_markup=None
            )
        else:
            await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        print(f"Failed to update admin message: {e}")


# ==================== Debt Approval ====================

@wallet_admin_router.callback_query(IsAdmin(), F.data.startswith("debt_approve:"))
async def debt_approve_handler(
    callback: CallbackQuery,
    _: callable,
    state: FSMContext
):
    """Start debt payment approval - ask for actual amount."""
    await safe_answer_callback(callback)

    # Parse: debt_approve:telegram_id:client_code
    parts = callback.data.split(":")
    if len(parts) != 3:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    telegram_id = int(parts[1])
    client_code = parts[2]

    await state.update_data(
        debt_telegram_id=telegram_id,
        debt_client_code=client_code,
        debt_message_id=callback.message.message_id,
        debt_chat_id=callback.message.chat.id
    )

    await callback.message.answer(_("wallet-admin-debt-enter-amount"))
    await state.set_state(WalletAdminStates.waiting_for_debt_actual_amount)


@wallet_admin_router.message(IsAdmin(), WalletAdminStates.waiting_for_debt_actual_amount, F.text)
async def debt_amount_received_handler(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
    bot: Bot
):
    """Process debt payment amount from admin."""
    from src.infrastructure.tools.money_utils import parse_money

    # Check for cancel
    if message.text.strip().lower() in ["/cancel", "bekor", "отмена"]:
        await message.answer(_("wallet-admin-cancelled"))
        await state.clear()
        return

    try:
        amount = parse_money(message.text)
    except (ValueError, TypeError):
        await session.rollback()
        await message.answer(_("wallet-admin-invalid-amount"))
        return

    if amount <= 0:
        await message.answer(_("wallet-admin-invalid-amount"))
        return

    data = await state.get_data()
    telegram_id = data.get("debt_telegram_id")
    client_code = data.get("debt_client_code")
    message_id = data.get("debt_message_id")
    chat_id = data.get("debt_chat_id")

    if not telegram_id or not client_code:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    # Verify client
    client = await client_service.get_client(telegram_id, session)
    if not client or client.client_code != client_code:
        await message.answer(_("wallet-admin-client-not-found"))
        await state.clear()
        return

    # Use FIFO allocation to apply payment to oldest debts first
    allocation_result = await PaymentAllocationService.apply_payment(
        session=session,
        client_code=client_code,
        amount=amount,
        admin_id=message.from_user.id
    )
    await session.commit()

    # Build notification message with debt allocation details
    notification_parts = [_("wallet-debt-approved-user", amount=f"{amount:,.0f}")]

    if allocation_result.allocations:
        notification_parts.append("\n")
        for alloc in allocation_result.allocations:
            if alloc.is_fully_paid:
                notification_parts.append(
                    f"\n✅ {alloc.flight_name} - qarz to'liq yopildi"
                )
            else:
                notification_parts.append(
                    f"\n💰 {alloc.flight_name} - {alloc.allocated_amount:,.0f} so'm ayirildi"
                )

    if allocation_result.remaining_credit > 0:
        notification_parts.append(
            f"\n\n💰 Ortiqcha: {allocation_result.remaining_credit:,.0f} so'm balansingizga qo'shildi"
        )

    notification_parts.append(f"\n\n📊 Yangi balans: {allocation_result.new_balance:,.0f} so'm")

    # Notify user
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text="".join(notification_parts)
        )
    except Exception as e:
        await session.rollback()
        print(f"Failed to notify user about debt payment: {e}")

    # Update original admin message
    if message_id and chat_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None
            )
            await bot.send_message(
                chat_id=chat_id,
                text=_("wallet-admin-debt-approved",
                       client_code=client_code,
                       amount=f"{amount:,.0f}",
                       admin_name=message.from_user.full_name),
                reply_to_message_id=message_id
            )
        except Exception as e:
            await session.rollback()
            print(f"Failed to update admin message: {e}")

    await message.answer(_("wallet-admin-debt-success"))
    await state.clear()


@wallet_admin_router.callback_query(IsAdmin(), F.data.startswith("debt_reject:"))
async def debt_reject_handler(
    callback: CallbackQuery,
    _: callable,
    bot: Bot
):
    """Reject debt payment."""
    await safe_answer_callback(callback, _("wallet-admin-rejected"), show_alert=True)

    # Parse: debt_reject:telegram_id
    parts = callback.data.split(":")
    if len(parts) != 2:
        return

    telegram_id = int(parts[1])

    # Notify user
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=_("wallet-debt-rejected-user")
        )
    except Exception as e:
        print(f"Failed to notify user about debt rejection: {e}")

    # Update admin message
    try:
        if callback.message.caption:
            await callback.message.edit_caption(
                callback.message.caption + f"\n\n❌ Rad etildi: {callback.from_user.full_name}",
                reply_markup=None
            )
        elif callback.message.text:
            await callback.message.edit_text(
                callback.message.text + f"\n\n❌ Rad etildi: {callback.from_user.full_name}",
                reply_markup=None
            )
        else:
            await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        print(f"Failed to update admin message: {e}")
