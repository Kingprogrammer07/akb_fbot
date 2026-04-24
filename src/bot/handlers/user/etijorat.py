"""User-side handlers for E-tijorat screenshot verification flow."""
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from src.bot.filters import IsPrivate
from src.bot.keyboards.admin.etijorat_admin import etijorat_admin_kb
from src.bot.states.etijorat import ETijoratState
from src.bot.utils.decorators import handle_errors
from src.config import config

logger = logging.getLogger(__name__)

etijorat_user_router = Router(name="etijorat_user")


@etijorat_user_router.callback_query(F.data == "etijorat_confirmed")
@handle_errors
async def etijorat_confirmed_cb(
    callback: CallbackQuery,
    _: callable,
    state: FSMContext,
):
    """User pressed '✅ Men ro'yxatdan o'tdim' — ask them to send a screenshot."""
    await callback.answer()
    await state.set_state(ETijoratState.waiting_for_screenshot)

    await callback.message.answer(_("etijorat-send-screenshot"))


@etijorat_user_router.message(
    ETijoratState.waiting_for_screenshot,
    F.photo,
    IsPrivate(),
)
@handle_errors
async def etijorat_screenshot_received(
    message: Message,
    _: callable,
    state: FSMContext,
    bot: Bot,
):
    """User sent a screenshot while in waiting_for_screenshot state."""
    telegram_id = message.from_user.id
    full_name = message.from_user.full_name
    username = f"@{message.from_user.username}" if message.from_user.username else "—"

    # Build the caption for the channel post
    caption = (
        f"📋 <b>E-tijorat screenshot</b>\n\n"
        f"👤 <b>Ism:</b> {full_name}\n"
        f"🆔 <b>Telegram ID:</b> <code>{telegram_id}</code>\n"
        f"📎 <b>Username:</b> {username}"
    )

    # Send the photo to the E-Tijorat approval channel
    photo_file_id = message.photo[-1].file_id
    await bot.send_photo(
        chat_id=config.telegram.E_TIJORAT_CHANNEL_ID,
        photo=photo_file_id,
        caption=caption,
        parse_mode="HTML",
        reply_markup=etijorat_admin_kb(telegram_id),
    )

    # Notify user and clear state
    await message.answer(_("etijorat-screenshot-under-review"))
    await state.clear()


@etijorat_user_router.message(
    ETijoratState.waiting_for_screenshot,
    IsPrivate(),
)
@handle_errors
async def etijorat_screenshot_invalid(
    message: Message,
    _: callable,
    state: FSMContext,
):
    """User sent something other than a photo while in waiting_for_screenshot state."""
    await message.answer(_("etijorat-send-screenshot-only-photo"))
