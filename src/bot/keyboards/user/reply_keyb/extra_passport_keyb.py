from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import  ReplyKeyboardBuilder


def ask_for_document_type(translator: callable = None) -> ReplyKeyboardMarkup:
    """
    Ask for document type keyboard.
    
    Args:
        translator (callable, optional): Translator function to localize keys. Defaults to None.
    """
        
    # Default translator if not provided
    def _(key):
        return key
    if translator:
        _ = translator
    
    builder = ReplyKeyboardBuilder()
    
    builder.add(KeyboardButton(text=_("add-passport-id-card")))
    builder.add(KeyboardButton(text=_("add-passport-passport")))
    builder.add(KeyboardButton(text=_("btn-cancel")))
    
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)

def save_and_cancel_kyb(translator: callable = None) -> ReplyKeyboardMarkup:
    """
    Save and cancel keyboard with i18n support.
    
    Args:
        translator (callable, optional): Translator function to localize keys. Defaults to None.
    """
    # Default translator if not provided
    def _(key):
        return key
    if translator:
        _ = translator
        
    builder = ReplyKeyboardBuilder()
    builder.button(text=_("btn-save"))
    builder.button(text=_("btn-cancel"))
    
    return builder.as_markup(
        resize_keyboard=True,
    )
