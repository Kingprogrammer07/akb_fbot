import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from src.bot.filters.is_admin import IsAdmin
from src.bot.keyboards import back_to_main_menu_kb

logger = logging.getLogger(__name__)
admin_access_denied_router = Router()


# @admin_access_denied_router.message(~IsAdmin())
# @admin_access_denied_router.callback_query(~IsAdmin())
# async def handle_access_denied(event: Message | CallbackQuery):
#     """Handle access denial for non-admin users trying to access admin features."""
#     try:
#         user_id = event.from_user.id
#         logger.warning(
#             f'User {user_id} attempted to access admin functionality without permission'
#         )

#         text = '🚫 Access Denied!'
#         kb = back_to_main_menu_kb()

#         if isinstance(event, Message):
#             await event.answer(text=text, reply_markup=kb)
#         elif isinstance(event, CallbackQuery):
#             await event.answer(text=text, show_alert=True)
#     except TelegramBadRequest as e:
#         logger.warning(f'Failed to send access denied message to user {event.from_user.id}: {e}')
