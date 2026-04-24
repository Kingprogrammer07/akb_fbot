"""Profile inline keyboards."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def profile_actions_kyb(translator: callable = None) -> InlineKeyboardMarkup:
    """
    Profile actions inline keyboard (shown below profile info).

    Args:
        translator: Translation function (_)
    """
    # Default translator
    def _(key):
        return key

    if translator:
        _ = translator

    builder = InlineKeyboardBuilder()

    # Row 1
    builder.row(
        InlineKeyboardButton(text=_("btn-edit-profile"), callback_data="profile_edit"),
        InlineKeyboardButton(text=_("btn-logout"), callback_data="profile_logout")
    )

    return builder.as_markup()


def logout_confirm_kyb(translator: callable = None) -> InlineKeyboardMarkup:
    """
    Logout confirmation keyboard.

    Args:
        translator: Translation function (_)
    """
    # Default translator
    def _(key):
        return key

    if translator:
        _ = translator

    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text=_("btn-yes-delete"), callback_data="logout_confirm_yes"),
        InlineKeyboardButton(text=_("btn-no-cancel"), callback_data="logout_confirm_no")
    )

    return builder.as_markup()


def edit_profile_kyb(translator: callable = None) -> InlineKeyboardMarkup:
    """
    Edit profile options keyboard.

    Args:
        translator: Translation function (_)
    """
    # Default translator
    def _(key):
        return key

    if translator:
        _ = translator

    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="✏️ " + _("profile-edit-name").split(":")[0], callback_data="edit_name")
    )
    builder.row(
        InlineKeyboardButton(text="📱 " + _("profile-edit-phone_btn"), callback_data="edit_phone")
    )
    builder.row(
        InlineKeyboardButton(text="📍 " + _("btn-edit-address"), callback_data="edit_address")
    )
    builder.row(
        InlineKeyboardButton(text=_("btn-cancel"), callback_data="edit_cancel")
    )

    return builder.as_markup()
