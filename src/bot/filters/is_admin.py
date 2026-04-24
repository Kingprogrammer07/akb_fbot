import logging

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from src import config
from src.infrastructure.services import ClientService

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

        if user_id in config.telegram.ADMIN_ACCESS_IDs:
            logger.info(f'User {user_id} granted admin access via config')
            return True
        try:
            client_data = await client_service.get_client(user_id, session)
            if client_data and client_data.role in ['admin', 'super-admin']:
                logger.info(f'User {user_id} has admin role in database')
                return True

            logger.warning(f'User {user_id} attempted admin access without permission')
            return False
        except Exception:
            await session.rollback()
            return False
