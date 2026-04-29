import logging

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.services import ClientService
from src.bot.utils.admin_access import is_admin_by_telegram_id

logger = logging.getLogger(__name__)


class IsAdmin(BaseFilter):
    """
    Filter checks if the user is an administrator.
    First checks the ID from the config, then the role field in the cache/database.
    """

    async def __call__(
        self, event: TelegramObject, session: AsyncSession, client_service: ClientService
    ):
        if not hasattr(event, 'from_user'):
            return False

        user_id = event.from_user.id

        try:
            if await is_admin_by_telegram_id(session, user_id):
                logger.info(f'User {user_id} has admin access')
                return True

            logger.warning(f'User {user_id} attempted admin access without permission')
            return False
        except Exception:
            await session.rollback()
            return False
