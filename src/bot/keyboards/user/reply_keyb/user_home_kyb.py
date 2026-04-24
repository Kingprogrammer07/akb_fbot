from urllib.parse import quote
from aiogram.types import InlineKeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder



def user_main_menu_kyb(translator: callable = None) -> ReplyKeyboardMarkup:
    """
    User main menu keyboard with i18n support.

    Args:
        translator: Translation function (_)
    """
    # Default translator if not provided
    def _(key):
        return key

    if translator:
        _ = translator

    builder = ReplyKeyboardBuilder()

    # 1-qator — Profil va Xizmatlar
    builder.button(text=_("btn-profile"))
    builder.button(text=_("btn-services"))

    # 2-qator — Do'stlarni taklif qilish va Bog'lanish
    builder.button(text=_("btn-invite-friends"))
    builder.button(text=_("btn-contact"))

    # 3-qator — Til
    builder.button(text=_("btn-language"))

    # MUHIM: adjust bilan qatorma-qator joylash
    builder.adjust(
        2,  # Profil | Xizmatlar
        2,  # Do'stlarni taklif qilish | Bog'lanish
        1,  # Til
    )

    return builder.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False
    )
    
def share_inline_keyboard(share_url: str, description: str):
    """
    🔗 Inline ulashish (share) tugmasi yaratadi.
    :param share_url: Ulashiladigan tashqi havola (URL) -> {bot_url}?start={telegram_id}-{client_code}
    :param description: Tavsif (text)
    :return: InlineKeyboardMarkup
    """
    markup = InlineKeyboardBuilder()

    encoded_url = quote(share_url, safe='')
    encoded_text = quote(description, safe='')

    markup.button(
        InlineKeyboardButton(
            text="📢 Ulashish",
            url=f"https://t.me/share/url?url={encoded_url}&text={encoded_text}"
        )
    )

    return markup
