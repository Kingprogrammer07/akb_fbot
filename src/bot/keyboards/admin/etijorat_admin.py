"""Inline keyboards for E-tijorat admin approval in the channel."""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def etijorat_admin_kb(telegram_id: int) -> InlineKeyboardMarkup:
    """
    Inline keyboard sent to the E-tijorat approval channel.

    Args:
        telegram_id: The user's Telegram ID (embedded in callback data)

    Returns:
        InlineKeyboardMarkup with Approve and Reject buttons
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Tasdiqlash",
        callback_data=f"etijorat_approve:{telegram_id}",
    )
    builder.button(
        text="❌ Bekor qilish",
        callback_data=f"etijorat_reject:{telegram_id}",
    )
    builder.adjust(2)
    return builder.as_markup()
