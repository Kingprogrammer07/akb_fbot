"""Admin start handler."""
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_private_chat import IsPrivate
from src.bot.filters.is_admin import IsAdmin
from src.bot.utils.decorators import handle_errors
from src.bot.utils.responses import reply_with_admin_panel
from src.infrastructure.services.client import ClientService

admin_start_router = Router(name="admin_start")


@admin_start_router.message(
    IsPrivate(),
    IsAdmin(),
    CommandStart()
)
@handle_errors
async def admin_start_handler(
    message: Message,
    _: callable,
    state: FSMContext,
    session: AsyncSession,
    client_service: ClientService
):
    """Handle /start command for admin users."""
    # Clear any existing state
    await state.clear()
    
    # Update username on every /start
    username = message.from_user.username
    client = await client_service.get_client(message.from_user.id, session)
    if client and client.username != (username or None):
        await client_service.update_client(
            client.telegram_id,
            {'username': username},
            session
        )
        await session.commit()
    
    # Send welcome message
    is_super = bool(client and client.role == "super-admin")
    await reply_with_admin_panel(message, _("admin-welcome"), translator=_, is_super_admin=is_super)


@admin_start_router.message(
    IsPrivate(),
    IsAdmin(),
    F.text.in_(["⬅️ Orqaga", "⬅️ Назад", "❌ Bekor qilish", "❌ Отмена"])
)
@handle_errors
async def admin_back_handler(
    message: Message,
    _: callable,
    state: FSMContext,
    session: AsyncSession,
    client_service: ClientService,
):
    """Handle back button - return to main menu."""
    await state.clear()
    client = await client_service.get_client(message.from_user.id, session)
    is_super = bool(client and client.role == "super-admin")
    await reply_with_admin_panel(message, _("admin-back-to-menu"), translator=_, is_super_admin=is_super)



