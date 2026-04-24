from aiogram import Bot
from aiogram.types import BotCommand


async def set_default_commands(bot: Bot) -> None:
    """
    Bot uchun default komandalarni sozlash
    """
    commands = [
        BotCommand(command="start", description="Botni ishga tushurish"),
        BotCommand(command="lang", description="Botning tilini tanlash"),
    ]

    await bot.set_my_commands(commands)
