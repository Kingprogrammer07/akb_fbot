from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def back_to_main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def back_to_main_menu_button(text: str = '🔙 Main menu') -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data='home')
