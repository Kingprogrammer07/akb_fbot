import logging
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from src import config

logger = logging.getLogger(__name__)


async def notify_admins(bot: Bot) -> None:
    """
    Bot ishga tushganda adminlarga xabar yuborish
    """
    if not config.telegram.ADMIN_ACCESS_IDs:
        logger.warning("ADMINS ro'yxati bo'sh")
        return

    for admin_id in config.telegram.ADMIN_ACCESS_IDs:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text="🚀 Bot muvaffaqiyatli ishga tushdi\n/start"
            )
        except TelegramAPIError as e:
            logger.exception(f"Admin {admin_id} ga xabar yuborilmadi: {e}")
