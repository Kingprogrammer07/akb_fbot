"""Language selection handler."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters import IsPrivate
from src.bot.keyboards.user import user_main_menu_kyb
from src.infrastructure.services import ClientService
from src.bot.keyboards import language_kb
from src.bot.utils.decorators import handle_errors


language_router = Router(name="language")


@language_router.message(Command("lang"), IsPrivate())
@language_router.message(F.text.in_(["🌐 Til", "🌐 Язык"]), IsPrivate())
@handle_errors
async def cmd_language(
    message: Message,
    _: callable,
    language: str
) -> None:
    """Handle /lang command."""
    await message.answer(
        _("select-language"),
        reply_markup=language_kb(current_lang=language)
    )


@language_router.callback_query(F.data.startswith("lang:"))
@handle_errors
async def callback_change_language(
    callback: CallbackQuery,
    session: AsyncSession,
    client_service: ClientService,
    i18n: object,
    _: callable
) -> None:
    """Handle language selection callback."""
    # Extract language from callback data
    lang = callback.data.split(":")[1]

    # Update client's language in database
    await client_service.update_client(
        telegram_id=callback.from_user.id,
        data={"language_code": lang},
        session=session
    )
    client = await client_service.get_client(callback.from_user.id, session)

    # Commit changes to database
    await session.commit()

    # Get translation in new language
    new_translator = lambda key, **kwargs: i18n.get(lang, key, **kwargs)

    await callback.message.delete()

    user_keyboard = ReplyKeyboardRemove()

    if client and client.client_code:
        user_keyboard = user_main_menu_kyb(translator=new_translator)


    await callback.message.answer(text=
        new_translator("language-changed"),
        reply_markup=user_keyboard
    )
    await callback.answer()
