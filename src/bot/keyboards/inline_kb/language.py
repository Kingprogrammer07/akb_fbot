"""Language selection inline keyboards."""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def language_kb(current_lang: str = "uz") -> InlineKeyboardMarkup:
    """
    Create language selection keyboard.

    Args:
        current_lang: Current language code (uz/ru)

    Returns:
        InlineKeyboardMarkup with language options
    """
    builder = InlineKeyboardBuilder()

    # Uzbek button
    uz_text = "✅ 🇺🇿 O'zbekcha" if current_lang == "uz" else "🇺🇿 O'zbekcha"
    builder.button(text=uz_text, callback_data="lang:uz")

    # Russian button
    ru_text = "✅ 🇷🇺 Ruscha" if current_lang == "ru" else "🇷🇺 Ruscha"
    builder.button(text=ru_text, callback_data="lang:ru")

    builder.adjust(2)  # 2 buttons per row

    return builder.as_markup()
