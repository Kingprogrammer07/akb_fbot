"""My passports handler with pagination."""
import json
import logging
from math import ceil

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters import IsPrivate
from src.bot.utils.decorators import handle_errors
from src.infrastructure.database.dao.client_extra_passport import ClientExtraPassportDAO

logger = logging.getLogger(__name__)

my_passports_router = Router(name="my_passports")

PAGE_SIZE = 5


@my_passports_router.message(F.text.in_(["📋 Mening passportlarim", "📋 Мои паспорта"]), IsPrivate())
@handle_errors
async def show_my_passports(
    message: Message,
    session: AsyncSession,
    _: callable
):
    """Show user's passports with pagination."""
    await show_passports_page(message, session, _, page=1)


async def show_passports_page(
    message: Message,
    session: AsyncSession,
    _: callable,
    page: int = 1
):
    """Show specific page of passports."""
    # Get total count
    total = await ClientExtraPassportDAO.count_by_telegram_id(session, message.from_user.id)

    if total == 0:
        await message.answer(_("my-passports-empty"))
        return

    # Calculate pagination
    total_pages = ceil(total / PAGE_SIZE)
    offset = (page - 1) * PAGE_SIZE

    # Get passports for page
    passports = await ClientExtraPassportDAO.get_by_telegram_id(
        session,
        message.from_user.id,
        limit=PAGE_SIZE,
        offset=offset
    )

    # Build message
    text = _("my-passports-title", total=total) + "\n\n"

    for idx, passport in enumerate(passports, start=offset + 1):
        text += f"{idx}. " + _("my-passports-item",
                                passport_series=passport.passport_series,
                                pinfl=passport.pinfl,
                                dob=passport.date_of_birth.strftime("%d.%m.%Y"),
                                created_at=passport.created_at.strftime("%d.%m.%Y %H:%M")
                                ) + "\n\n"

    # Build keyboard with view buttons + pagination
    kb = build_passports_keyboard(passports, page, total_pages, _)
    await message.answer(text, reply_markup=kb)


def build_passports_keyboard(passports: list, current_page: int, total_pages: int, _: callable) -> InlineKeyboardMarkup:
    """Build keyboard with view/delete buttons + pagination."""
    builder = InlineKeyboardBuilder()

    # View/Delete buttons for each passport
    for passport in passports:
        builder.row(
            InlineKeyboardButton(
                text=f"👁 {passport.passport_series}",
                callback_data=f"passport_view:{passport.id}"
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"passport_delete:{passport.id}"
            )
        )

    # Pagination buttons
    if total_pages > 1:
        buttons = []
        if current_page > 1:
            buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"passports_page:{current_page - 1}"))
        buttons.append(InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="passports_noop"))
        if current_page < total_pages:
            buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"passports_page:{current_page + 1}"))
        builder.row(*buttons)

    return builder.as_markup()


@my_passports_router.callback_query(F.data.startswith("passports_page:"))
@handle_errors
async def pagination_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable
):
    """Handle pagination callback."""
    page = int(callback.data.split(":")[1])

    # Get total count
    total = await ClientExtraPassportDAO.count_by_telegram_id(session, callback.from_user.id)
    total_pages = ceil(total / PAGE_SIZE)
    offset = (page - 1) * PAGE_SIZE

    # Get passports
    passports = await ClientExtraPassportDAO.get_by_telegram_id(
        session,
        callback.from_user.id,
        limit=PAGE_SIZE,
        offset=offset
    )

    # Build message
    text = _("my-passports-title", total=total) + "\n\n"

    for idx, passport in enumerate(passports, start=offset + 1):
        text += f"{idx}. " + _("my-passports-item",
                                passport_series=passport.passport_series,
                                pinfl=passport.pinfl,
                                dob=passport.date_of_birth.strftime("%d.%m.%Y"),
                                created_at=passport.created_at.strftime("%d.%m.%Y %H:%M")
                                ) + "\n\n"

    text += _("my-passports-page", current=page, total=total_pages)

    # Update message
    await callback.message.edit_text(
        text,
        reply_markup=build_passports_keyboard(passports, page, total_pages, _)
    )
    await callback.answer()


@my_passports_router.callback_query(F.data == "passports_noop")
async def noop_callback(callback: CallbackQuery):
    """No-op callback for page indicator."""
    await callback.answer()


@my_passports_router.callback_query(F.data.startswith("passport_view:"))
@handle_errors
async def view_passport_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable
):
    """View passport details with images."""
    passport_id = int(callback.data.split(":")[1])

    # Get passport from database
    passport = await ClientExtraPassportDAO.get_by_id(session, passport_id)

    if not passport:
        await callback.answer(_("passport-not-found"), show_alert=True)
        return

    # Parse images from JSON and resolve S3 keys to presigned URLs
    images = json.loads(passport.passport_images)
    from src.infrastructure.tools.passport_image_resolver import resolve_passport_items
    resolved_images = await resolve_passport_items(images)

    # Send images as media group (album) if multiple, or single photo
    from aiogram.types import InputMediaPhoto

    if len(resolved_images) > 1:
        # Album mode
        media_group = [
            InputMediaPhoto(media=resolved_images[0], caption=_("passport-detail-caption",
                                                       passport_series=passport.passport_series,
                                                       pinfl=passport.pinfl,
                                                       dob=passport.date_of_birth.strftime("%d.%m.%Y"),
                                                       created_at=passport.created_at.strftime("%d.%m.%Y %H:%M"))),
            *[InputMediaPhoto(media=img) for img in resolved_images[1:]]
        ]
        await callback.message.answer_media_group(media=media_group)
    else:
        # Single image
        await callback.message.answer_photo(
            photo=resolved_images[0],
            caption=_("passport-detail-caption",
                      passport_series=passport.passport_series,
                      pinfl=passport.pinfl,
                      dob=passport.date_of_birth.strftime("%d.%m.%Y"))
        )

    # Send delete button separately
    delete_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_("btn-delete-passport"), callback_data=f"passport_delete_confirm:{passport_id}")]
    ])
    await callback.message.answer(_("passport-delete-prompt"), reply_markup=delete_kb)
    await callback.answer()


@my_passports_router.callback_query(F.data.startswith("passport_delete:"))
@handle_errors
async def delete_passport_callback(
    callback: CallbackQuery,
    _: callable
):
    """Ask for delete confirmation."""
    passport_id = callback.data.split(":")[1]

    # Confirmation keyboard
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_("btn-yes-delete"), callback_data=f"passport_delete_confirm:{passport_id}"),
            InlineKeyboardButton(text=_("btn-no-cancel"), callback_data="passports_noop")
        ]
    ])

    await callback.message.answer(_("passport-delete-confirm"), reply_markup=kb)
    await callback.answer()


@my_passports_router.callback_query(F.data.startswith("passport_delete_confirm:"))
@handle_errors
async def delete_passport_confirm_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable
):
    """Confirm and delete passport."""
    passport_id = int(callback.data.split(":")[1])

    # Get passport
    passport = await ClientExtraPassportDAO.get_by_id(session, passport_id)

    if not passport:
        await callback.answer(_("passport-not-found"), show_alert=True)
        return

    # Verify ownership
    if passport.telegram_id != callback.from_user.id:
        await callback.answer(_("access-denied"), show_alert=True)
        return

    # Delete from database
    await ClientExtraPassportDAO.delete(session, passport)
    await session.commit()

    await callback.message.answer(_("passport-deleted-success"))
    await callback.answer()

    # Refresh list
    await show_passports_page(callback.message, session, _, page=1)
