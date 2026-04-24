"""Cargo photos handlers for client verification."""
import json
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_admin import IsAdmin
from src.infrastructure.services.flight_cargo import FlightCargoService
from src.infrastructure.services.client_transaction import ClientTransactionService
from src.bot.utils.decorators import handle_errors

from .utils import safe_answer_callback

router = Router()


@router.callback_query(F.data.startswith("v:cgo:"), IsAdmin())
@handle_errors
async def show_cargo_photos(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession,
    flight_cargo_service: FlightCargoService,
    transaction_service: ClientTransactionService,
    bot: Bot
):
    """Show cargo photos for specific flight and client."""
    parts = callback.data.split(":")
    transaction_id = int(parts[2])

    from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
    transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)
    if not transaction:
        await safe_answer_callback(callback, _("error-occurred"), show_alert=True)
        return

    flight_name = transaction.reys
    client_code = transaction.client_code

    result = await flight_cargo_service.get_client_cargos(
        session,
        flight_name=flight_name,
        client_id=client_code
    )

    cargos = result.get('cargos', [])

    if not cargos:
        await safe_answer_callback(callback, _("admin-verification-no-cargos"), show_alert=True)
        return

    await safe_answer_callback(callback)

    for cargo in cargos:
        try:
            photo_file_ids = json.loads(cargo.photo_file_ids)
        except (json.JSONDecodeError, TypeError):
            await session.rollback()
            photo_file_ids = [cargo.photo_file_ids] if cargo.photo_file_ids else []

        if not photo_file_ids:
            await callback.message.answer(
                f"❌ Yuk #{cargo.id} uchun rasmlar topilmadi",
                parse_mode="HTML"
            )
            continue

        weight_info = ""
        if cargo.weight_kg:
            weight_info = _("admin-verification-cargo-weight", weight=float(cargo.weight_kg)) + "\n    "

        comment_info = ""
        if cargo.comment:
            comment_info = _("admin-verification-cargo-comment", comment=cargo.comment) + "\n    "

        info_text = _("admin-verification-cargo-info",
            flight=cargo.flight_name,
            client=cargo.client_id,
            weight_info=weight_info,
            comment_info=comment_info,
            date=cargo.created_at.strftime('%Y-%m-%d %H:%M'),
            status=_("admin-verification-cargo-sent") if cargo.is_sent else _("admin-verification-cargo-not-sent")
        )

        try:
            if len(photo_file_ids) == 1:
                await bot.send_photo(
                    chat_id=callback.message.chat.id,
                    photo=photo_file_ids[0],
                    caption=info_text,
                    parse_mode="HTML"
                )
            else:
                media_group = []
                for idx, file_id in enumerate(photo_file_ids):
                    caption = info_text if idx == 0 else None
                    media_group.append(
                        InputMediaPhoto(
                            media=file_id,
                            caption=caption,
                            parse_mode="HTML" if caption else None
                        )
                    )

                await bot.send_media_group(
                    chat_id=callback.message.chat.id,
                    media=media_group
                )

        except Exception as e:
            await session.rollback()
            error_msg = info_text + "\n\n" + _("admin-verification-cargo-photo-error", error=str(e))
            await callback.message.answer(
                error_msg,
                parse_mode="HTML"
            )

    await callback.message.answer(
        _("admin-verification-cargos-shown", count=len(cargos))
    )
