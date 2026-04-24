"""Admin message handlers."""
import logging
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from sqlalchemy.ext.asyncio import AsyncSession
from src.config import config
from src.bot.utils.decorators import handle_errors
from src.bot.utils.safe_sender import safe_send_message
from aiogram import Bot


logger = logging.getLogger(__name__)
admin_messages_router = Router(name="admin_messages")


@admin_messages_router.message(F.text == "/regenerate")
@handle_errors
async def handle_broadcast(
    message: Message,
    session: AsyncSession
) -> None:
    await message.answer(
        text="Regenerating file_id...",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Open Web App", web_app=WebAppInfo(url=f"{config.telegram.WEBAPP_BASE_URL}/user/home"))]
                # [InlineKeyboardButton(text="Open Web App", web_app=WebAppInfo(url=f"{config.telegram.WEBAPP_BASE_URL}/user/home?tab=request"))]
            ]
        )
    )
    # await message.answer_photo(photo='AgACAgIAAxkDAAIeF2ls_N9lv-fOUFnZEtzR7DZTXLUqAAKIEGsbD-FoS9K8eHNCOx2xAQADAgADdwADOAQ')

@admin_messages_router.message(F.text == "/testing")
@handle_errors
async def handle_broadcast(
    message: Message,
    session: AsyncSession,
    bot: Bot
) -> None:
    gr = config.telegram.AKB_OSTATKA_GROUP_ID
    try:
        await bot.send_message(chat_id=gr, text="Testing message!")
    except Exception as e:
        logger.error(f"Error sending testing message: {e}")