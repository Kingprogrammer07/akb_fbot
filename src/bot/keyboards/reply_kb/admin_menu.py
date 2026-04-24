"""Admin panel reply keyboards."""
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def get_admin_main_menu(translator: callable = None, is_super_admin: bool = False) -> ReplyKeyboardMarkup:
    """
    Get admin main menu keyboard.

    Layout:
    Row 1: 📥 Bazalar
    Row 2: 📦 Track kod | 👤 Foydalanuvchi
    Row 3: ✅ Foydalanuvchi tekshirish
    Row 4: 🖼 Foto | 📢 Reklama yuborish
    Row 5: Malumot olish | 📁 Referal baza
    """
    
    def _(key):
        return key
    if translator:
        _ = translator
        
    
    builder = ReplyKeyboardBuilder()

    # Row 1 - Most important action
    builder.row(
        KeyboardButton(text=_("btn-admin-databases"))
    )

    # Row 2 - Search functions
    builder.row(
        KeyboardButton(text=_("btn-admin-track-check")),
        KeyboardButton(text=_("btn-admin-user-search"))
    )

    # Row 3 - Client verification
    builder.row(
        KeyboardButton(text=_("btn-admin-client-verification"))
    )

    # Row 4 - Data and messaging
    builder.row(
        KeyboardButton(text=_("btn-admin-upload-photo")),
        KeyboardButton(text=_("btn-admin-send-message"))
    )

    # Row 5 - Media and reports
    builder.row(
        KeyboardButton(text=_("btn-admin-get-data")),
        KeyboardButton(text=_("btn-admin-referral-data"))
    )
    
    # Row 6 - Leftover cargo
    builder.row(
        KeyboardButton(text=_("btn-admin-leftover-cargo")),
        KeyboardButton(text=_("btn-admin-leftover-notifications"))
    )

    # # Row 7 - Leftover notifications
    # builder.row(
    # )

    # Row 8 - Settings (super-admin only)
    if is_super_admin:
        builder.row(
            KeyboardButton(text=_("btn-admin-settings"))
        )

    return builder.as_markup(resize_keyboard=True)
