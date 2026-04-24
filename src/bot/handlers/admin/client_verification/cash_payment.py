"""Cash payment handlers for client verification."""
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from redis.client import Redis
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


class VerificationCashPaymentState(StatesGroup):
    """State for cash payment approval in verification with amount input."""
    waiting_for_amount = State()


@router.callback_query(F.data.startswith("v:cp:"), IsAdmin())
@handle_errors
async def cash_payment_start_in_verification(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    state: FSMContext,
    redis: Redis
):
    """Start cash payment confirmation in client verification - ask for amount input."""
    await safe_answer_callback(callback)

    parts = callback.data.split(":")
    if len(parts) < 3:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    transaction_id = int(parts[2])

    from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
    transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)
    if not transaction:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    worksheet = transaction.reys
    row_number = transaction.qator_raqami
    tx_id_str = str(transaction_id)
    client_code = transaction.client_code

    client = await client_service.get_client_by_code(client_code, session)
    if not client:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    telegram_id = client.telegram_id

    if tx_id_str != "new":
        try:
            tx_id = int(tx_id_str)
            existing_tx = await ClientTransactionDAO.get_by_id(session, tx_id)
            if existing_tx and existing_tx.is_taken_away:
                await safe_answer_callback(callback, _("payment-already-taken"), show_alert=True)
                return
        except (ValueError, Exception):
            await session.rollback()
            pass

    exists = await transaction_service.check_payment_exists(
        client.client_code,
        worksheet,
        row_number,
        session
    )
    if exists and tx_id_str == "new":
        await safe_answer_callback(callback, _("payment-already-exists"), show_alert=True)
        return

    from src.bot.handlers.user.info import calculate_flight_payment

    payment_data = await calculate_flight_payment(
        session=session,
        flight_name=worksheet,
        client_code=client.client_code,
        redis=redis
    )

    if not payment_data:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    expected_amount = payment_data["total_payment"]
    vazn = payment_data["total_weight"] if payment_data["total_weight"] else "N/A"

    # Store context in FSM state
    await state.update_data(
        vcp_transaction_id=transaction_id,
        vcp_client_code=client_code,
        vcp_worksheet=worksheet,
        vcp_row_number=row_number,
        vcp_telegram_id=telegram_id,
        vcp_expected_amount=expected_amount,
        vcp_vazn=vazn,
        vcp_phone=client.phone,
        vcp_message_id=callback.message.message_id,
        vcp_chat_id=callback.message.chat.id
    )

    # Ask for amount input
    await callback.message.answer(
        _("admin-cash-payment-enter-amount", expected=f"{expected_amount:,.0f}")
    )
    await callback.message.answer(
        f"ℹ️ Istalgan summani kiriting:\n"
        f"• Ko'proq → ortiqcha balansga o'tadi\n"
        f"• Kamroq → qisman to'lov sifatida saqlanadi\n"
        f"• Kutilgan summa: {expected_amount:,.2f} so'm"
    )
    await state.set_state(VerificationCashPaymentState.waiting_for_amount)


@router.message(IsAdmin(), VerificationCashPaymentState.waiting_for_amount, F.text)
async def cash_payment_amount_received_in_verification(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    state: FSMContext,
    bot: Bot
):
    """Process cash payment amount from admin in verification."""
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
    transaction_id = data.get("vcp_transaction_id")
    client_code = data.get("vcp_client_code")
    worksheet = data.get("vcp_worksheet")
    row_number = data.get("vcp_row_number")
    telegram_id = data.get("vcp_telegram_id")
    expected_amount = data.get("vcp_expected_amount", 0)
    vazn = data.get("vcp_vazn")
    phone = data.get("vcp_phone")
    admin_message_id = data.get("vcp_message_id")
    admin_chat_id = data.get("vcp_chat_id")

    if not client_code or not worksheet:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    from src.infrastructure.tools.datetime_utils import get_current_time
    from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
    from src.infrastructure.database.dao.client_payment_event import ClientPaymentEventDAO

    tx_id_str = str(transaction_id)

    if tx_id_str == "new":
        client = await client_service.get_client_by_code(client_code, session)

        # Calculate payment_balance_difference correctly:
        # paid_amount - expected_amount
        payment_balance_diff = float(amount) - float(expected_amount)

        # Create new transaction with correct payment_balance_difference
        tx_data = {
            "telegram_id": telegram_id if telegram_id else 0,
            "client_code": client_code,
            "qator_raqami": row_number,
            "reys": worksheet,
            "summa": float(amount),
            "vazn": str(vazn),
            "payment_receipt_file_id": None,
            "payment_type": "cash",
            "payment_status": "paid" if payment_balance_diff >= 0 else "partial",
            "paid_amount": float(amount),
            "total_amount": float(expected_amount),
            "remaining_amount": max(0.0, float(expected_amount) - float(amount)),
            "is_taken_away": True,
            "taken_away_date": get_current_time(),
            "payment_balance_difference": payment_balance_diff,  # Key field!
        }
        new_tx = await ClientTransactionDAO.create(session, tx_data)

        await ClientPaymentEventDAO.create(
            session=session,
            transaction_id=new_tx.id,
            payment_type="cash",
            amount=amount,
            approved_by_admin_id=message.from_user.id,
            payment_provider="cash"
        )

        await session.commit()
    else:
        try:
            tx_id = int(tx_id_str)
            tx = await ClientTransactionDAO.get_by_id(session, tx_id)
            if tx:
                await ClientPaymentEventDAO.create(
                    session=session,
                    transaction_id=tx.id,
                    payment_type="cash",
                    amount=amount,
                    approved_by_admin_id=message.from_user.id,
                    payment_provider="cash"
                )

                # Recalculate payment_balance_difference using PaymentAllocationService
                await PaymentAllocationService.recalculate_transaction_balance(
                    session, tx.id
                )

                # Refresh to get updated values
                await session.refresh(tx)

                if tx.remaining_amount <= 0:
                    tx.is_taken_away = True
                    tx.taken_away_date = get_current_time()

                # payment_balance_difference already updated by recalculate_transaction_balance

                await session.commit()
        except (ValueError, Exception) as e:
            await session.rollback()
            print(f"Error updating transaction: {e}")

    # Notify user
    if telegram_id:
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=_("payment-cash-confirmed-user")
            )
        except Exception as e:
            await session.rollback()
            print(f"Failed to notify user: {e}")

    # Send to confirmation channel
    channel_id = config.telegram.TOLOV_TASDIQLANGAN_CHANNEL_ID
    channel_notification = _(
        "payment-confirmed-channel-cash",
        client_code=client_code,
        worksheet=worksheet,
        summa=f"{amount:.0f} so'm",
        full_name=message.from_user.full_name,
        phone=phone or "N/A",
        telegram_id=str(telegram_id) if telegram_id else "N/A"
    )

    try:
        await bot.send_message(
            chat_id=channel_id,
            text=channel_notification
        )
    except Exception as e:
        await session.rollback()
        print(f"Failed to send to channel: {e}")

    # Update original admin message
    if admin_message_id and admin_chat_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=admin_chat_id,
                message_id=admin_message_id,
                reply_markup=None
            )
            await bot.send_message(
                chat_id=admin_chat_id,
                text=f"✅ Naqd to'lov tasdiqlandi\n👤 Mijoz: {client_code}\n✈️ Reys: {worksheet}\n💰 Summa: {amount:,.0f} so'm",
                reply_to_message_id=admin_message_id
            )
        except Exception as e:
            await session.rollback()
            print(f"Failed to update admin message: {e}")

    await message.answer(_("admin-payment-success"))
    await state.clear()
