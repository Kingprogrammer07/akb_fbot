"""User inline keyboards."""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def user_menu_kb() -> InlineKeyboardMarkup:
    """
    Create user menu keyboard.

    Returns:
        InlineKeyboardMarkup with user menu options
    """
    builder = InlineKeyboardBuilder()

    builder.button(text="ℹ️ Ma'lumot", callback_data="user:info")
    builder.button(text="❓ Yordam", callback_data="user:help")
    builder.button(text="⚙️ Sozlamalar", callback_data="user:settings")
    builder.button(text="🌐 Til", callback_data="user:language")

    builder.adjust(2, 2)  # 2 buttons per row

    return builder.as_markup()


def user_info_kb() -> InlineKeyboardMarkup:
    """
    Create user info keyboard with back button.

    Returns:
        InlineKeyboardMarkup with back button
    """
    builder = InlineKeyboardBuilder()

    builder.button(text="⬅️ Orqaga", callback_data="home")

    return builder.as_markup()


def user_settings_kb() -> InlineKeyboardMarkup:
    """
    Create user settings keyboard.

    Returns:
        InlineKeyboardMarkup with settings options
    """
    builder = InlineKeyboardBuilder()

    builder.button(text="🔔 Bildirishnomalar", callback_data="user:notifications")
    builder.button(text="🌐 Til o'zgartirish", callback_data="user:change_lang")
    builder.button(text="🗑️ Hisobni o'chirish", callback_data="user:delete_account")
    builder.button(text="⬅️ Orqaga", callback_data="home")

    builder.adjust(1)  # 1 button per row

    return builder.as_markup()
