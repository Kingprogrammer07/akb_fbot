import logging

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from src import config
from src.infrastructure.services import ClientService

logger = logging.getLogger(__name__)


class IsSuperAdmin(BaseFilter):
    """Pass only for clients whose role is ``super-admin``.

    Config-level ``ADMIN_ACCESS_IDs`` are treated as super-admins because
    they are trusted operators who provisioned the bot — they should always
    have full access regardless of DB state.
    """

    async def __call__(
        self,
        event: TelegramObject,
        session: AsyncSession,
        client_service: ClientService,
    ) -> bool:
        if not hasattr(event, "from_user"):
            return False

        user_id = event.from_user.id

        if user_id in config.telegram.ADMIN_ACCESS_IDs:
            return True

        try:
            client_data = await client_service.get_client(user_id, session)
            return bool(client_data and client_data.role == "super-admin")
        except Exception:
            await session.rollback()
            return False
