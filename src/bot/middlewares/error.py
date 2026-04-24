# src/bot/middlewares/error.py
import logging
from aiogram import BaseMiddleware

from src.bot.utils.responses import reply_with_internal_error


logger = logging.getLogger(__name__)


class ErrorMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        except Exception as e:
            logger.error(e)
            await reply_with_internal_error(event)
