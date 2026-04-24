"""Contact handlers."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.bot.filters.is_private_chat import IsPrivate
from src.bot.filters.is_logged_in import ClientExists, IsRegistered, IsLoggedIn


contact_router = Router(name="contact")


@contact_router.message(IsPrivate(), ClientExists(), IsRegistered(), IsLoggedIn(), F.text.in_(["📞 Bog'lanish", "📞 Связаться"]))
async def contacts_handler(message: Message, _: callable, state: FSMContext):
    """Show contact information."""
    await state.clear()
    await message.answer(_("contact-info"))  
