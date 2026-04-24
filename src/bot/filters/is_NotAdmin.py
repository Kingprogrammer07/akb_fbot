import logging

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from src import config
from src.infrastructure.services import ClientService

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

        # Config adminlar
        if user_id in config.telegram.ADMIN_ACCESS_IDs:
            return False

        try:
            client = await client_service.get_client(user_id, session)
            if client and client.role in ['admin', 'super-admin']:
                return False
            return True
        except Exception:
            await session.rollback()
            return False
