"""Filter to check if user is logged in."""
from aiogram.filters import Filter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.services.client import ClientService


class IsLoggedIn(Filter):
    """
    Filter to check if user is logged in.

    Usage:
        @router.message(IsLoggedIn())
        async def my_handler(message: Message):
            # This handler will only run if user is logged in
            pass
    """

    async def __call__(
        self,
        message: Message,
        session: AsyncSession,
        client_service: ClientService
    ) -> bool:
        """Check if user is logged in."""
        try:
            client = await client_service.get_client(message.from_user.id, session)

            if not client:
                return False

            return client.is_logged_in
        except Exception:
            await session.rollback()
            return False


class ClientExists(Filter):
    """
    Filter to check if client exists in database.

    Usage:
        @router.message(ClientExists())
        async def my_handler(message: Message):
            # This handler will only run if client exists
            pass
    """

    async def __call__(
        self,
        message: Message,
        session: AsyncSession,
        client_service: ClientService
    ) -> bool:
        """Check if client exists."""
        try:
            client = await client_service.get_client(message.from_user.id, session)
            return client is not None
        except Exception:
            await session.rollback()
            return False


class IsRegistered(Filter):
    """
    Filter to check if client is fully registered (has client_code).

    Usage:
        @router.message(IsRegistered())
        async def my_handler(message: Message):
            # This handler will only run if client is registered and has client_code
            pass
    """

    async def __call__(
        self,
        message: Message,
        session: AsyncSession,
        client_service: ClientService
    ) -> bool:
        """Check if client is registered."""
        try:
            client = await client_service.get_client(message.from_user.id, session)

            if not client:
                return False

            return client.client_code is not None
        except Exception:
            await session.rollback()
            return False
