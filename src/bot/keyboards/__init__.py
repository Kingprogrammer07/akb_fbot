"""Keyboards module - organized by type."""

# Old imports (for backward compatibility)
from src.bot.keyboards.main_menu import (
    back_to_main_menu_button,
    back_to_main_menu_kb,
)

# Inline keyboards
from src.bot.keyboards.inline_kb.auth import auth_kb
from src.bot.keyboards.inline_kb.language import language_kb
from src.bot.keyboards.inline_kb.user import user_menu_kb, user_info_kb, user_settings_kb
from src.bot.keyboards.inline_kb.approval import approval_keyboard


from src.bot.keyboards.reply_kb.admin_menu import get_admin_main_menu

# General reply keyboards
from src.bot.keyboards.reply_kb.general_keyb import cancel_kyb, back_kyb




__all__ = [
    'back_to_main_menu_kb',
    'back_to_main_menu_button',

    # Inline keyboards
    'auth_kb',
    'language_kb',
    'user_menu_kb',
    'user_info_kb',
    'user_settings_kb',
    'approval_keyboard',

    # General reply keyboards
    'cancel_kyb',
    'back_kyb',
    
    # Reply keyboards
    'get_admin_main_menu',
]
