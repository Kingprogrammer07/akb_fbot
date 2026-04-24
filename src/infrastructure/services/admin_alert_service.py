import logging
from aiogram import Bot

from src.config import config

logger = logging.getLogger(__name__)


class AdminAlertService:
    """Admin autentifikatsiya hodisalari uchun Telegram ogohlantirish xizmati."""

    @staticmethod
    async def alert_4th_attempt(
        bot: Bot,
        super_admins_ids: list[int],
        target_username: str,
        ip_address: str | None,
        user_agent: str | None,
        timestamp: str
    ) -> None:
        """4-marta muvaffaqiyatsiz urinish bo‘lganda barcha super-adminlarga yuborish."""
        text = (
            f"⚠️ <b>ADMIN XAVFSIZLIK OGOHLANTIRISHI</b> ⚠️\n\n"
            f"<b>Username:</b> {target_username}\n"
            f"<b>Muvaffaqiyatsiz urinishlar:</b> 4\n"
            f"<b>Holat:</b> Bloklanishdan oldingi ogohlantirish\n\n"
            f"<b>IP:</b> {ip_address or 'Noma’lum'}\n"
            f"<b>Qurilma:</b> {user_agent or 'Noma’lum'}\n"
            f"<b>Vaqt:</b> {timestamp}"
        )
        for admin_id in super_admins_ids:
            if admin_id:
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=text
                    )
                except Exception as e:
                    logger.error(f"4-urinish ogohlantirishini {admin_id} ga yuborib bo‘lmadi: {e}")

    @staticmethod
    async def alert_new_device_to_admin(
        bot: Bot,
        admin_telegram_id: int | None,
        username: str,
        ip_address: str | None,
        user_agent: str | None,
        timestamp: str,
        super_admins_ids: list[int] | None = None,
    ) -> None:
        """Admin yangi qurilma/IP orqali kirganda, o’ziga to’g’ridan-to’g’ri xabar yuborish."""
        if not admin_telegram_id:
            return

        text = (
            f"🔐 <b>YANGI KIRISH ANIQLANDI</b> 🔐\n\n"
            f"Admin Panel akkauntingizga (<code>{username}</code>) yangi kirish aniqlandi.\n\n"
            f"<b>IP:</b> {ip_address or 'Nomalum'}\n"
            f"<b>Qurilma:</b> {user_agent or 'Nomalum'}\n"
            f"<b>Vaqt:</b> {timestamp}\n\n"
            f"<i>Agar bu siz bo’lmasangiz, darhol super-admin bilan bog’laning!</i>"
        )
        try:
            await bot.send_message(chat_id=admin_telegram_id, text=text)
        except Exception as e:
            logger.warning(
                f"Yangi qurilma ogohlantirishini admin {admin_telegram_id} ga yuborib bo’lmadi: {e}"
            )
            # Fallback: the bot hasn’t started a conversation with this admin yet,
            # or the Telegram ID is stale.  Build a recipient set from two sources:
            #   1. DB super-admins passed in by the caller.
            #   2. BOT_ADMIN_ACCESS_IDs from config — always up-to-date from .env.
            # We exclude the admin we just failed to reach (retrying the same ID is
            # pointless) and deduplicate via a set to avoid sending the same message twice.
            config_admin_ids: set[int] = config.telegram.ADMIN_ACCESS_IDs or set()
            db_super_admin_ids: set[int] = set(super_admins_ids or [])
            fallback_ids = (db_super_admin_ids | config_admin_ids) - {admin_telegram_id}

            if not fallback_ids:
                logger.warning(
                    "No fallback admin IDs available — new-device alert for "
                    f"{username} (tg_id={admin_telegram_id}) was silently dropped."
                )
                return

            fallback_text = (
                f"⚠️ Admin {admin_telegram_id} (<code>{username}</code>) ga"
                f" ogohlantirish yuborib bo’lmadi.\n"
                f"Sabab: {e}\n\n"
                f"Asl xabar:\n{text}"
            )
            for fallback_id in fallback_ids:
                try:
                    await bot.send_message(chat_id=fallback_id, text=fallback_text)
                except Exception as fallback_err:
                    logger.error(
                        f"Fallback alert to admin {fallback_id} also failed: {fallback_err}"
                    )

    @staticmethod
    async def alert_new_device_to_super_admins(
        bot: Bot,
        super_admins_ids: list[int],
        target_username: str,
        ip_address: str | None,
        user_agent: str | None
    ) -> None:
        """Admin akkauntiga yangi qurilmadan kirilganini super-adminlarga xabar berish."""
        text = (
            f"ℹ️ <b>Admin uchun yangi qurilmadan kirish</b>\n\n"
            f"<b>Admin:</b> <code>{target_username}</code>\n"
            f"<b>IP:</b> {ip_address or 'Noma’lum'}\n"
            f"<b>Qurilma:</b> {user_agent or 'Noma’lum'}"
        )
        for admin_id in super_admins_ids:
            if admin_id:
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=text
                    )
                except Exception as e:
                    logger.error(f"Yangi qurilma xabarini super-admin {admin_id} ga yuborib bo‘lmadi: {e}")