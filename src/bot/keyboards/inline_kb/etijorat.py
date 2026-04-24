"""Inline keyboards for E-tijorat user verification flow."""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def etijorat_confirm_kb(_: callable) -> InlineKeyboardMarkup:
    """
    Inline keyboard attached to the E-tijorat video message.
    User presses this after registering in the E-tijorat app.

    Args:
        _: i18n translation function

    Returns:
        InlineKeyboardMarkup with a single confirmation button
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("btn-etijorat-confirmed"),
        callback_data="etijorat_confirmed",
    )
    builder.adjust(1)
    return builder.as_markup()
