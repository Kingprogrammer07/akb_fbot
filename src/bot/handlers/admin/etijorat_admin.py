"""Admin handlers for E-tijorat screenshot approval/rejection in the channel."""
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from src.bot.keyboards import auth_kb
from src.bot.utils.decorators import handle_errors
from src.bot.utils.i18n import i18n, DEFAULT_LANGUAGE
from src.config import config

logger = logging.getLogger(__name__)

etijorat_admin_router = Router(name="etijorat_admin")


def _user_translator(lang: str = DEFAULT_LANGUAGE):
    """Create a translator function for a specific language."""
    return lambda key, **kwargs: i18n.get(lang, key, **kwargs)


@etijorat_admin_router.callback_query(F.data.startswith("etijorat_approve:"))
@handle_errors
async def etijorat_approve(
    callback: CallbackQuery,
    bot: Bot,
    _: callable,
):
    """Admin approved the E-tijorat screenshot."""
    telegram_id = int(callback.data.split(":")[1])
    admin = callback.from_user

    # Edit the channel message to show approval status
    original_caption = callback.message.caption or ""
    updated_caption = (
        f"{original_caption}\n\n"
        f"{'=' * 20}\n"
        f"✅ <b>Tasdiqlangan</b>\n"
        f"👮 Admin: {admin.full_name} (ID: {admin.id})"
    )

    try:
        await callback.message.edit_caption(
            caption=updated_caption,
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception as e:
        logger.error(f"Failed to edit E-tijorat approval message: {e}")

    await callback.answer("✅ Tasdiqlandi", show_alert=False)

    # Send approval message to the user with the registration keyboard
    _ = _user_translator()
    welcome_text = _("start") + "\n\n" + _("etijorat-approved") + "\n\n" + _("start-new-user")

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=welcome_text,
            reply_markup=auth_kb(_),
        )
    except Exception as e:
        logger.error(
            f"Failed to send E-tijorat approval to user {telegram_id}: {e}"
        )


@etijorat_admin_router.callback_query(F.data.startswith("etijorat_reject:"))
@handle_errors
async def etijorat_reject(
    callback: CallbackQuery,
    bot: Bot,
    _: callable,
):
    """Admin rejected the E-tijorat screenshot."""
    telegram_id = int(callback.data.split(":")[1])
    admin = callback.from_user

    # Edit the channel message to show rejection status
    original_caption = callback.message.caption or ""
    updated_caption = (
        f"{original_caption}\n\n"
        f"{'=' * 20}\n"
        f"❌ <b>Rad etilgan</b>\n"
        f"👮 Admin: {admin.full_name} (ID: {admin.id})"
    )

    try:
        await callback.message.edit_caption(
            caption=updated_caption,
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception as e:
        logger.error(f"Failed to edit E-tijorat rejection message: {e}")

    await callback.answer("❌ Rad etildi", show_alert=False)

    # Notify the user about rejection
    _ = _user_translator()

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=_("etijorat-rejected"),
        )
    except Exception as e:
        logger.error(
            f"Failed to send E-tijorat rejection to user {telegram_id}: {e}"
        )
