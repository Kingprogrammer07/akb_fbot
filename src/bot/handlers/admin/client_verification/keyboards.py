"""Keyboard builders for client verification module."""
from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config import config


def get_client_webapp_keyboard(
    client_id: int | None,
    _: callable
) -> InlineKeyboardMarkup:
    """
    Generate WebApp keyboard based on client existence.

    Args:
        client_id: Client ID if exists, None if not found
        _: i18n translation function

    Returns:
        InlineKeyboardMarkup
    """
    kb = InlineKeyboardBuilder()

    if client_id is None:
        kb.button(
            text=_("btn-add-client"),
            web_app=WebAppInfo(
                url=config.telegram.webapp_client_add
            )
        )
    else:
        kb.button(
            text=_("btn-edit-client"),
            web_app=WebAppInfo(
                url=f"{config.telegram.webapp_client_edit(client_id)}"
            )
        )
        kb.button(
            text=_("btn-delete-client"),
            callback_data=f"admin:delete_client:{client_id}"
        )

    kb.adjust(2)
    return kb.as_markup()
