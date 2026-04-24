from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import  ReplyKeyboardBuilder


def cancel_kyb(translator: callable = None) -> ReplyKeyboardMarkup:
    """
    Cancel keyboard with i18n support.

    Args:
        translator: Translation function (_)
    """
    # Default translator if not provided
    def _(key):
        return key
    if translator:
        _ = translator
        
    builder = ReplyKeyboardBuilder()
    builder.button(text=_("btn-cancel"))
    
    return builder.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False
    )
    
def back_kyb(translator: callable = None) -> ReplyKeyboardMarkup:
    """
    Back keyboard with i18n support.    

    Args:
        translator: Translation function (_)
    """
    # Default translator if not provided
    def _(key):
        return key
    if translator:
        _ = translator
        
    builder = ReplyKeyboardBuilder()
    builder.button(text=_("btn-back"))
    
    return builder.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False
    )