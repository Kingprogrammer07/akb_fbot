import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.bot.bot_instance import bot
from src.bot.filters import IsPrivate
from src.bot.keyboards.inline_kb.auth import auth_login_kb
from src.bot.keyboards import auth_kb
# from src.bot.keyboards.inline_kb.etijorat import etijorat_confirm_kb  # E-tijorat vaqtinchalik o'chirilgan
from src.bot.keyboards.user.reply_keyb.user_home_kyb import user_main_menu_kyb
from src.bot.utils.decorators import handle_errors
from src.bot.utils.referral_cache import save_referral_data
from src.infrastructure.services.client import ClientService

logger = logging.getLogger(__name__)
commands_router = Router()


@commands_router.message(
    F.text.in_(["⬅️ Orqaga", "❌ Bekor qilish", "⬅️ Назад", "❌ Отмена"]), IsPrivate()
)
@commands_router.message(IsPrivate(), CommandStart())
@handle_errors
async def start_handler(
    message: Message,
    session: AsyncSession,
    client_service: ClientService,
    redis: Redis,
    _: callable,
    state: FSMContext,
):
    """Handle /start command with referral support."""
    await state.clear()
    # Parse referral args (format: "telegram_id_client_code")
    args = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else None
    referrer_telegram_id = None
    referrer_client_code = None

    if args and "_" in args:
        try:
            parts = args.split("_", 1)
            referrer_telegram_id = int(parts[0])
            referrer_client_code = parts[1] if len(parts) > 1 else None
        except (ValueError, IndexError):
            await session.rollback()
            logger.warning(f"Invalid referral format: {args}")

    # Check if client already exists
    client = await client_service.get_client(message.from_user.id, session)

    # Update username on every /start
    username = message.from_user.username
    if client:
        # Update username if changed or missing
        if client.username != (username or None):
            await client_service.update_client(
                client.telegram_id, {"username": username}, session
            )
            await session.commit()

        # User already registered - check both client_code and is_logged_in
        if client.primary_code and client.is_logged_in:
            # Fully registered and logged in
            await message.answer(
                _("start")
                + "\n\n"
                + _(
                    "start-registered",
                    full_name=client.full_name,
                    phone=client.phone or _("not-provided"),
                    client_code=client.primary_code,
                ),
                reply_markup=user_main_menu_kyb(translator=_),
            )
        elif client.primary_code and not client.is_logged_in:
            # Has client_code but not logged in
            await message.answer(
                _("start")
                + "\n\n"
                + _("start-not-logged-in", full_name=client.full_name),
                reply_markup=auth_login_kb(_),
            )
        else:
            # Registered but waiting for approval (no client_code yet)
            await message.answer(
                _("start")
                + "\n\n"
                + _("start-pending-approval", full_name=client.full_name),
                reply_markup=ReplyKeyboardRemove(),
            )
        return

    # New user — save referral data first (must happen before any response)
    if (
        referrer_telegram_id and referrer_client_code
    ) and referrer_telegram_id != message.from_user.id:
        # Save referral data to Redis cache (TTL: 24 hours)
        # This will be retrieved during registration API call
        await save_referral_data(
            redis=redis,
            telegram_id=message.from_user.id,
            referrer_telegram_id=referrer_telegram_id,
            referrer_client_code=referrer_client_code,
        )
        logger.info(
            f"Saved referral data for {message.from_user.id} from {referrer_telegram_id}"
        )

    # # Send E-tijorat verification video with confirmation button
    # await bot.copy_message(
    #     chat_id=message.from_user.id,
    #     from_chat_id=-1003871828748,
    #     message_id=3,
    #     caption=_("etijorat-caption"),
    #     parse_mode="HTML",
    #     reply_markup=etijorat_confirm_kb(_),
    # )

    # Send approval message to the user with the registration keyboard
    welcome_text = _("start") + "\n\n" + _("start-new-user")

    try:
        await bot.send_message(
            chat_id=message.from_user.id,
            text=welcome_text,
            reply_markup=auth_kb(_),
        )
    except Exception as e:
        logger.error(
            f"Failed to send E-tijorat approval to user {message.from_user.id}: {e}"
        )