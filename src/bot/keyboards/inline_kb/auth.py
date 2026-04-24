"""Authentication inline keyboards."""
from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config import config


def auth_kb(_: callable) -> InlineKeyboardMarkup:
    """
    Create authentication keyboard with WebApp buttons.

    WebApp URLs are loaded from config (BOT_WEBAPP_REGISTER_URL and BOT_WEBAPP_LOGIN_URL).

    Args:
        _: i18n translation function

    Returns:
        InlineKeyboardMarkup with Register and Login buttons
    """
    builder = InlineKeyboardBuilder()

    # Register button with WebApp (URL from config)
    builder.button(
        text=_("btn-register"),
        web_app=WebAppInfo(url=config.telegram.webapp_register_url)
    )

    # Login button with WebApp (URL from config)
    builder.button(
        text=_("btn-login"),
        web_app=WebAppInfo(url=config.telegram.webapp_login_url)
    )

    builder.adjust(1)  # 1 button per row

    return builder.as_markup()



def auth_login_kb(_: callable) -> InlineKeyboardMarkup:
    """
    Create authentication keyboard with WebApp button.

    WebApp URL is loaded from config (BOT_WEBAPP_LOGIN_URL).

    Args:
        _: i18n translation function

    Returns:
        InlineKeyboardMarkup with Login button
    """
    builder = InlineKeyboardBuilder()

    # Login button with WebApp (URL from config)
    builder.button(
        text=_("btn-login"),
        web_app=WebAppInfo(url=config.telegram.webapp_login_url)
    )

    builder.adjust(1)

    return builder.as_markup()
