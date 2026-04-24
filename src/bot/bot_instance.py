"""
Global Telegram Bot instance.

This module provides a single shared Bot instance to be used throughout the application.
All modules should import the bot from here instead of creating new Bot instances.
"""
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import Config

config = Config()

# Single global Bot instance with default HTML parse mode
bot = Bot(
    token=config.telegram.TOKEN.get_secret_value(),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
