"""Paid payments list handlers for client verification."""
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_admin import IsAdmin
from src.infrastructure.services.client import ClientService
from src.infrastructure.services.client_transaction import ClientTransactionService
from src.bot.utils.decorators import handle_errors

from .utils import (
    safe_answer_callback,
    encode_flight_code,
    decode_flight_code,
    VERIFICATION_CONTEXT
)

router = Router()


@router.callback_query(F.data.startswith("v:pay:"), IsAdmin())
@handle_errors
async def show_payments_list(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService,
    bot: Bot
):
    """Show paginated payments list with filters, sorting, and flight filter."""
    parts = callback.data.split(":")
    client_code = parts[2]
    filter_type = parts[3]
    sort_order = parts[4]
    page = int(parts[5])
    flight_hash = parts[6] if len(parts) > 6 and parts[6] != "none" else None

    # Resolve all active aliases so that transactions stored under any code variant are found.
    client = await client_service.get_client_by_code(client_code, session)
    if not client:
        await safe_answer_callback(callback, _("client-not-found"), show_alert=True)
        return

    active_codes = client.active_codes
    canonical_code = client.primary_code

    flight_code = None
    if flight_hash and flight_hash != "none":
        flight_code = await decode_flight_code(flight_hash, active_codes, session, transaction_service)

    VERIFICATION_CONTEXT[callback.from_user.id] = {
        "client_code": canonical_code,
        "filter_type": filter_type,
        "sort_order": sort_order,
        "page": page,
        "flight_hash": flight_hash or "none",
    }

    per_page = 2
    offset = page * per_page

    transactions = await transaction_service.get_filtered_transactions_by_client_code(
        active_codes, session, filter_type, sort_order, per_page, offset, flight_code
    )

    if not transactions:
        await safe_answer_callback(callback, _("admin-verification-no-payments"), show_alert=True)
        return

    total_count = await transaction_service.count_filtered_transactions_by_client_code(
        active_codes, session, filter_type, flight_code
    )
    total_pages = (total_count + per_page - 1) // per_page

    for transaction in transactions:
        if transaction.total_amount is not None:
            total_amount = float(transaction.total_amount)
        else:
            total_amount = float(transaction.summa or 0)

        if transaction.paid_amount is not None:
            paid_amount = float(transaction.paid_amount)
        else:
            paid_amount = float(transaction.summa or 0) if transaction.payment_status == "paid" else 0.0

        if transaction.remaining_amount is not None:
            remaining_amount = float(transaction.remaining_amount)
        else:
            remaining_amount = max(total_amount - paid_amount, 0.0)

        display_amount = total_amount if transaction.payment_status == "partial" else float(transaction.summa or 0)

        info_text = _("admin-verification-payment-info",
            flight=transaction.reys,
            row=transaction.qator_raqami,
            amount=display_amount,
            weight=transaction.vazn,
            date=transaction.created_at.strftime('%Y-%m-%d %H:%M')
        )

        if transaction.is_taken_away:
            taken_date = transaction.taken_away_date.strftime('%Y-%m-%d %H:%M') if transaction.taken_away_date else _("unknown")
            info_text += "\n" + _("admin-search-cargo-taken", date=taken_date)
        else:
            info_text += "\n" + _("admin-search-cargo-not-taken")

        tx_builder = InlineKeyboardBuilder()
        has_buttons = False

        if transaction.payment_status == "partial":
            info_text += "\n" + _("admin-verification-partial-payment",
                paid=paid_amount,
                remaining=remaining_amount,
                deadline=transaction.payment_deadline.strftime("%Y-%m-%d %H:%M") if transaction.payment_deadline else _("not-set")
            )

        if transaction.is_taken_away:
            pass
        elif transaction.payment_status == "paid":
            tx_builder.button(
                text=_("btn-mark-as-taken"),
                callback_data=f"v:mt:{transaction.id}"
            )
            has_buttons = True
        else:
            tx_builder.button(
                text=_("btn-cash-payment-confirm"),
                callback_data=f"v:cp:{transaction.id}"
            )
            has_buttons = True

            tx_builder.button(
                text=_("btn-account-payment"),
                callback_data=f"v:ap:{transaction.id}"
            )
            has_buttons = True

        if canonical_code:
            tx_builder.button(
                text=_("btn-verification-show-cargos"),
                callback_data=f"v:cgo:{transaction.id}"
            )
            has_buttons = True

        tx_builder.adjust(1)

        keyboard = tx_builder.as_markup() if has_buttons else None

        if transaction.payment_receipt_file_id:
            try:
                await bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=transaction.payment_receipt_file_id,
                    caption=info_text,
                    reply_markup=keyboard
                )
            except Exception:
                await session.rollback()
                try:
                    await bot.send_photo(
                        chat_id=callback.message.chat.id,
                        photo=transaction.payment_receipt_file_id,
                        caption=info_text,
                        reply_markup=keyboard
                    )
                except Exception:
                    await session.rollback()
                    await callback.message.answer(
                        info_text + "\n\n" + _("admin-verification-receipt-unavailable"),
                        reply_markup=keyboard
                    )
        else:
            await callback.message.answer(
                info_text + "\n\n" + _("admin-verification-no-receipt"),
                reply_markup=keyboard
            )

    builder = InlineKeyboardBuilder()

    filter_info = ""
    if flight_code:
        filter_info = f"✈️ {flight_code} | "

    filters = [
        ("all", "btn-filter-all"),
        ("taken", "btn-filter-taken"),
        ("not_taken", "btn-filter-not-taken"),
        ("partial", "btn-filter-partial"),
    ]

    for filter_val, filter_label in filters:
        prefix = "✓ " if filter_val == filter_type else ""
        builder.button(
            text=prefix + _(filter_label),
            callback_data=f"v:pay:{canonical_code}:{filter_val}:{sort_order}:0:{flight_hash or 'none'}"
        )
    builder.adjust(3)

    sort_label = _("btn-sort-oldest") if sort_order == "desc" else _("btn-sort-newest")
    new_sort = "asc" if sort_order == "desc" else "desc"
    builder.row(
        InlineKeyboardBuilder().button(
            text=sort_label,
            callback_data=f"v:pay:{canonical_code}:{filter_type}:{new_sort}:0:{flight_hash or 'none'}"
        ).as_markup().inline_keyboard[0][0]
    )

    if flight_code:
        builder.row(
            InlineKeyboardBuilder().button(
                text=_("btn-clear-flight-filter"),
                callback_data=f"v:pay:{canonical_code}:{filter_type}:{sort_order}:0:none"
            ).as_markup().inline_keyboard[0][0]
        )
    else:
        builder.row(
            InlineKeyboardBuilder().button(
                text=_("btn-filter-by-flight"),
                callback_data=f"v:sf:{canonical_code}"
            ).as_markup().inline_keyboard[0][0]
        )

    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardBuilder().button(
                text=_("btn-previous"),
                callback_data=f"v:pay:{canonical_code}:{filter_type}:{sort_order}:{page - 1}:{flight_hash or 'none'}"
            ).as_markup().inline_keyboard[0][0]
        )

    nav_buttons.append(
        InlineKeyboardBuilder().button(
            text=f"{page + 1}/{total_pages}",
            callback_data="v:pi"
        ).as_markup().inline_keyboard[0][0]
    )

    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardBuilder().button(
                text=_("btn-next"),
                callback_data=f"v:pay:{canonical_code}:{filter_type}:{sort_order}:{page + 1}:{flight_hash or 'none'}"
            ).as_markup().inline_keyboard[0][0]
        )

    if nav_buttons:
        builder.row(*nav_buttons)

    await callback.message.answer(
        text=filter_info + _("admin-verification-page-nav", current=page + 1, total=total_pages),
        reply_markup=builder.as_markup()
    )

    await safe_answer_callback(callback)


@router.callback_query(F.data.startswith("v:mt:"), IsAdmin())
@handle_errors
async def mark_transaction_as_taken(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    transaction_service: ClientTransactionService,
    bot: Bot
):
    """Mark a transaction as cargo taken."""
    parts = callback.data.split(":")
    transaction_id = int(parts[2])

    from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
    transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)
    if not transaction:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    if transaction.is_taken_away:
        await safe_answer_callback(callback, _("admin-verification-marked-as-taken"), show_alert=True)
        return

    success = await transaction_service.mark_as_taken(transaction_id, session)

    if success:
        await session.commit()
        await safe_answer_callback(callback, _("admin-verification-marked-as-taken"), show_alert=True)

        ctx = VERIFICATION_CONTEXT.get(callback.from_user.id, {
            "client_code": transaction.client_code,
            "filter_type": "all",
            "sort_order": "desc",
            "page": 0,
            "flight_hash": "none",
        })
        await callback.message.delete()
        ctx_client_code = ctx.get('client_code') or transaction.client_code
        new_callback_data = f"v:pay:{ctx_client_code}:{ctx['filter_type']}:{ctx['sort_order']}:{ctx['page']}:{ctx.get('flight_hash','none')}"

        from aiogram.types import CallbackQuery as CQ
        refresh_callback = CQ(
            id=callback.id,
            from_user=callback.from_user,
            message=callback.message,
            chat_instance=callback.chat_instance,
            data=new_callback_data
        )

        await show_payments_list(refresh_callback, _, session, transaction_service, bot)
    else:
        await safe_answer_callback(callback, _("admin-verification-mark-failed"), show_alert=True)


@router.callback_query(F.data == "v:pi", IsAdmin())
async def ignore_page_info(callback: CallbackQuery):
    """Ignore page info button clicks."""
    await safe_answer_callback(callback)
