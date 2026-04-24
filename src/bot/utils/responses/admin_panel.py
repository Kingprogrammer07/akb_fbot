from aiogram.types import CallbackQuery, Message, TelegramObject

from src.bot.keyboards.reply_kb.admin_menu import get_admin_main_menu



async def reply_with_admin_panel(
    event: TelegramObject,
    text: str,
    translator: callable = None,
    is_super_admin: bool = False,
) -> None:
    """Send admin panel message to admin for Message or CallbackQuery."""

    def _(key):
        return key
    if translator:
        _ = translator

    menu = get_admin_main_menu(_, is_super_admin=is_super_admin)

    if isinstance(event, Message):
        await event.answer(text=text, reply_markup=menu)

    elif isinstance(event, CallbackQuery):
        callback_query = event
        await callback_query.message.delete()
        await callback_query.answer()
        await callback_query.message.answer(text=text, reply_markup=menu)
