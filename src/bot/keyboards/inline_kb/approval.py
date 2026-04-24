"""Approval keyboards for client registration."""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def approval_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    """
    Create approval keyboard for client registration.

    Args:
        telegram_id: Client's Telegram ID

    Returns:
        InlineKeyboardMarkup with approve, reject, and reject with reason buttons
    """
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Tasdiqlash",
        callback_data=f"approve:{telegram_id}"
    )
    builder.button(
        text="❌ Rad etish",
        callback_data=f"reject:{telegram_id}"
    )
    builder.button(
        text="📝 Izoh bilan rad etish",
        callback_data=f"reject_reason:{telegram_id}"
    )

    builder.adjust(1)  # 1 button per row
    return builder.as_markup()
