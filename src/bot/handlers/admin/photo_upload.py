"""Admin photo upload handler - WebApp integration."""
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from src.bot.filters.is_admin import IsAdmin
from src.bot.filters.is_private_chat import IsPrivate
from src.config import config

photo_upload_router = Router()


@photo_upload_router.message(
    IsPrivate(),
    IsAdmin(),
    F.text.in_([
        "📸 Загрузить фото",
        "📸 Foto yuklash",
    ]),
    StateFilter("*")
)
async def photo_upload_handler(message: Message, state: FSMContext, _: callable):
    """
    Handle photo upload button - opens WebApp for flight photo management.

    Admin can:
    - View all flights
    - Create new flights
    - Upload cargo photos with client ID and weight
    - View uploaded photos
    """
    # Clear any active state
    await state.clear()

    # Create WebApp button with bulk send button
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_("btn-open-photo-webapp"),
                    web_app=WebAppInfo(url=config.telegram.webapp_flights)
                )
            ],
            [
                InlineKeyboardButton(
                    text="📤 Ma'lumot yuborish",
                    callback_data="start_bulk_send"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌐 Web hisobot yuborish",
                    callback_data="start_web_bulk_send"
                )
            ]
        ]
    )

    await message.answer(
        text=_("msg-photo-upload-webapp"),
        reply_markup=keyboard
    )
