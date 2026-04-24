"""Inline keyboards."""
from src.bot.keyboards.inline_kb.auth import auth_kb
from src.bot.keyboards.inline_kb.language import language_kb
from src.bot.keyboards.inline_kb.user import user_menu_kb, user_info_kb

__all__ = [
    'auth_kb',
    'language_kb',
    'user_menu_kb',
    'user_info_kb',
]
