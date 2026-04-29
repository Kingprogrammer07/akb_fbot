import logging

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.services import ClientService
from src.bot.utils.admin_access import is_admin_by_telegram_id

logger = logging.getLogger(__name__)


class IsNotAdmin(BaseFilter):
    async def __call__(
        self,
        event: TelegramObject,
        session: AsyncSession,
        client_service: ClientService
    ) -> bool:
        if not hasattr(event, 'from_user'):
            return False

        user_id = event.from_user.id

        try:
            return not await is_admin_by_telegram_id(session, user_id)
        except Exception:
            await session.rollback()
            return False
