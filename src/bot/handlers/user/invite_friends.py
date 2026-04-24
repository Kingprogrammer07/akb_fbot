"""Invite friends handler."""

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.utils.deep_linking import create_start_link
from aiogram.types.copy_text_button import CopyTextButton
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.bot_instance import bot
from src.bot.filters.is_private_chat import IsPrivate
from src.bot.filters.is_logged_in import ClientExists, IsRegistered, IsLoggedIn
from src.bot.utils.decorators import handle_errors
from src.infrastructure.services import ClientService


invite_friends_router = Router(name="invite_friends")


async def get_invite_url(telegram_id: int, client_code: str) -> str:
    """Generate invite URL for user."""
    # Format: start=telegram_id_client_code
    start_param = f"{telegram_id}_{client_code}"
    # Use shared bot instance
    return await create_start_link(bot=bot, payload=start_param, encode=False)


def create_invite_keyboard(
    invite_url: str, translator: callable
) -> InlineKeyboardBuilder:
    """Create invite keyboard with share and copy buttons."""
    builder = InlineKeyboardBuilder()

    # Share button
    builder.button(
        text=translator("btn-share-bot"), url=f"https://t.me/share/url?url={invite_url}"
    )

    # Copy URL button with CopyTextButton
    copy_button = InlineKeyboardButton(
        text=translator("btn-copy-url"), copy_text=CopyTextButton(text=invite_url)
    )
    builder.row(copy_button)

    builder.adjust(1, 1)  # One button per row
    return builder


@invite_friends_router.message(
    IsPrivate(),
    ClientExists(),
    IsRegistered(),
    IsLoggedIn(),
    F.text.in_(["👥 Do'stlarni taklif qilish", "👥 Пригласить друзей"]),
)
@handle_errors
async def invite_friends_handler(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
):
    """Show invite friends information with referral count."""
    await state.clear()
    # Get client for client_code
    client = await client_service.get_client(message.from_user.id, session)

    if not client:
        await message.answer(_("error-occurred"))
        return

    # Generate invite URL
    invite_url = await get_invite_url(client.telegram_id, client.primary_code)

    keyboard = create_invite_keyboard(invite_url, _)

    # Count how many people this user has referred
    referral_count = await client_service.count_referrals(client.telegram_id, session)

    invite_text = (
        _("invite-friends-title", referral_count=referral_count)
        + f"\n\n<code>{invite_url}</code>"
    )

    await message.answer(
        invite_text, parse_mode="HTML", reply_markup=keyboard.as_markup()
    )
