"""Client info handlers - full info display."""
import json
from aiogram import Router, F
from aiogram.types import CallbackQuery, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_admin import IsAdmin
from src.infrastructure.services.client import ClientService
from src.infrastructure.services.client_transaction import ClientTransactionService
from src.bot.utils.decorators import handle_errors

from .utils import safe_answer_callback
from .keyboards import get_client_webapp_keyboard

router = Router()


@router.callback_query(F.data.startswith("v:fi:"), IsAdmin())
@handle_errors
async def show_full_client_info(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    transaction_service: ClientTransactionService
):
    """Show full client information."""
    client_id = int(callback.data.split(":")[2])

    client = await client_service.get_client_by_id(client_id, session)

    if not client:
        await safe_answer_callback(callback, _("client-not-found"), show_alert=True)
        return

    # Use all active codes to count transactions across all of the client's aliases.
    active_codes = client.active_codes

    transaction_count = await transaction_service.count_transactions_by_client_code(
        active_codes, session
    )
    latest_transaction = await transaction_service.get_latest_transaction_by_client_code(
        client.primary_code, session
    )

    extra_passports_count = await client_service.count_extra_passports_by_client_code(
        client.primary_code, session
    )

    referral_count = await client_service.count_referrals_by_client_code(client.primary_code, session)

    info_text = _("admin-search-basic-info",
        code=client.client_code,
        new_code=client.extra_code or _("not-provided"),
        legacy_code=client.legacy_code or _("not-provided"),
        telegram_id=str(client.telegram_id) or _("not-provided"),
        name=client.full_name,
        phone=client.phone or _("not-provided"),
        birthday=client.date_of_birth.strftime('%Y-%m-%d') if client.date_of_birth else _("not-provided"),
        passport=client.passport_series or _("not-provided"),
        pinfl=client.pinfl or _("not-provided"),
        region=client.region or _("not-provided"),
        address=client.address or _("not-provided"),
        referral_count=str(referral_count),
        created=client.created_at.strftime('%Y-%m-%d %H:%M')
    )

    info_text += "\n\n"
    info_text += _("admin-search-payments-info", count=transaction_count)

    if latest_transaction:
        info_text += "\n\n"
        info_text += _("admin-search-last-payment",
            flight=latest_transaction.reys,
            row=latest_transaction.qator_raqami,
            amount=latest_transaction.summa,
            date=latest_transaction.created_at.strftime('%Y-%m-%d %H:%M')
        )

        if latest_transaction.payment_receipt_file_id:
            info_text += "\n" + _("admin-search-has-payment-receipt")

        if latest_transaction.is_taken_away:
            taken_date = latest_transaction.taken_away_date.strftime('%Y-%m-%d %H:%M') if latest_transaction.taken_away_date else _("unknown")
            info_text += "\n" + _("admin-search-cargo-taken", date=taken_date)
        else:
            info_text += "\n" + _("admin-search-cargo-not-taken")

    info_text += "\n\n"
    info_text += _("admin-search-extra-passports", count=extra_passports_count)

    if client.passport_images:
        try:
            file_ids = json.loads(client.passport_images)
            if file_ids:
                from src.infrastructure.tools.passport_image_resolver import resolve_passport_items
                resolved = await resolve_passport_items(file_ids)
                media_group = [
                    InputMediaPhoto(media=ref, caption=info_text if i == 0 else "")
                    for i, ref in enumerate(resolved)
                ]

                keyboard = get_client_webapp_keyboard(client.id, _)
                await callback.message.delete()
                await callback.message.answer_media_group(media=media_group)
                await callback.message.answer(
                    text=_("admin-search-passport-images"),
                    reply_markup=keyboard
                )
                await safe_answer_callback(callback)
                return
        except (json.JSONDecodeError, Exception):
            await session.rollback()
            pass

    await callback.message.edit_text(
        text=info_text,
        reply_markup=get_client_webapp_keyboard(client.id, _)
    )
    await safe_answer_callback(callback)
