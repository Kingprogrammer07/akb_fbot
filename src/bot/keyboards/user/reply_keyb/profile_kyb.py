"""Profile submenu keyboards."""
from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def profile_menu_kyb(translator: callable = None) -> ReplyKeyboardMarkup:
    """
    Profile submenu keyboard.

    Args:
        translator: Translation function (_)
    """
    # Default translator
    def _(key):
        return key

    if translator:
        _ = translator

    builder = ReplyKeyboardBuilder()

    # Row 1 - Passport actions
    builder.button(text=_("btn-add-passport"))
    builder.button(text=_("btn-my-passports"))

    # Row 2 - Profile actions
    builder.button(text=_("btn-edit-profile"))
    builder.button(text=_("btn-logout"))

    # Row 3 - Devices (session history)
    builder.button(text=_("btn-devices"))

    # Row 4 - Back
    builder.button(text=_("btn-back-to-menu"))

    builder.adjust(2, 2, 1, 1)

    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def services_menu_kyb(translator: callable = None) -> ReplyKeyboardMarkup:
    """
    Services submenu keyboard.

    Args:
        translator: Translation function (_)
    """
    # Default translator
    def _(key):
        return key

    if translator:
        _ = translator

    builder = ReplyKeyboardBuilder()

    # Row 1 - Track code (full width)
    builder.button(text=_("btn-check-track-code"))

    # Row 2
    builder.button(text=_("btn-send-request"))
    builder.button(text=_("btn-make-payment"))

    # Row 3
    builder.button(text=_("btn-china-address"))
    builder.button(text=_("btn-view-info"))

    # Row 4 - Wallet
    builder.button(text=_("btn-wallet"))
    builder.button(text=_("btn-payment-reminder"))

    # Row 5 - Back (full width)
    builder.button(text=_("btn-back-to-menu"))

    builder.adjust(1, 2, 2, 2, 1)

    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)
