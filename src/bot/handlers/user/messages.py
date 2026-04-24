"""User message handlers."""
import logging
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters import IsNotAdmin, IsPrivate
from src.bot.filters.is_logged_in import ClientExists, IsRegistered, IsLoggedIn
from src.bot.utils.decorators import handle_errors
from src.infrastructure.services.client import ClientService

logger = logging.getLogger(__name__)
user_messages_router = Router(name="user_messages")


@user_messages_router.message(IsNotAdmin(), IsPrivate(), ClientExists(), IsRegistered(), IsLoggedIn(), F.text)
@handle_errors
async def handle_user_text(
    message: Message,
    session: AsyncSession,
    client_service: ClientService,
    _: callable
) -> None:
    """Handle any text message from users."""
    # Check if user is registered
    client = await client_service.get_client(message.from_user.id, session)

    if not client:
        try:
            await message.answer(
                "❌ Avval /start buyrug'ini bosing va ro'yxatdan o'ting!",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            await session.rollback()
            logger.error(f"Error in handle_user_text: {e}")
            await message.answer(
                "❌ Avval /start buyrug'ini bosing va ro'yxatdan o'ting!"
            )
        return

    if not client.client_code:
        # Registered but waiting for approval (no client_code yet)
        await message.answer(
            _("start") + "\n\n" + _(
                "start-pending-approval",
                full_name=client.full_name
            ),
            reply_markup=ReplyKeyboardRemove()
        )
        return