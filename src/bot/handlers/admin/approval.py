"""Admin handlers for client approval workflow."""

import json
import logging
import os
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.utils.constants import UZBEKISTAN_REGIONS
from src.bot.filters import IsAdmin
from src.bot.keyboards.user.reply_keyb.user_home_kyb import user_main_menu_kyb
from src.bot.states.approval import ApprovalStates
from src.bot.utils.decorators import handle_errors
from src.config import config
from src.infrastructure.services.client import ClientService
from src.infrastructure.tools.passport_image_resolver import resolve_passport_items
from src.infrastructure.tools.s3_manager import s3_manager

logger = logging.getLogger(__name__)

approval_router = Router(name="approval")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _cleanup_client_s3_images(client) -> None:
    """Delete client's passport images from S3 if they exist."""
    if not client or not client.passport_images:
        return
    try:
        items = json.loads(client.passport_images)
        for item in (items if isinstance(items, list) else [items]):
            if "/" in item or "." in item:
                await s3_manager.delete_file(item)
                logger.info(f"Deleted S3 file: {item}")
    except Exception as e:
        logger.error(
            f"Failed to delete S3 images for client "
            f"{getattr(client, 'primary_code', '?')} "
            f"(Telegram ID: {getattr(client, 'telegram_id', '?')}): {e}"
        )


async def _finalize_rejection(
    bot: Bot,
    chat_id: int,
    message_id: int,
    telegram_id: int,
    full_name: str,
    _: callable,
    reason: str | None = None,
    original_content: str | None = None,
) -> None:
    """
    Update admin message and notify the rejected client.
    Appends rejection stamp to the original message instead of replacing it.
    """
    if reason:
        admin_info  = _("admin-rejection-message-with-reason",
                        full_name=full_name, telegram_id=str(telegram_id), reason=reason)
        client_text = _("client-rejection-message-with-reason",
                        full_name=full_name, reason=reason)
    else:
        admin_info  = _("admin-rejection-message",
                        full_name=full_name, telegram_id=str(telegram_id))
        client_text = _("client-rejection-message", full_name=full_name)

    final_admin_text = (
        f"{original_content}\n\n{'=' * 10}\n{admin_info}"
        if original_content else admin_info
    )

    # Update admin message (text or caption)
    try:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=final_admin_text, reply_markup=None, parse_mode="HTML",
            )
        except Exception:
            await bot.edit_message_caption(
                chat_id=chat_id, message_id=message_id,
                caption=final_admin_text, reply_markup=None, parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"Failed to edit rejection message: {e}")
        try:
            await bot.send_message(chat_id, text=final_admin_text, parse_mode="HTML")
        except Exception as send_err:
            logger.error(f"Failed to send fallback rejection message: {send_err}")

    # Notify client
    try:
        await bot.send_message(chat_id=telegram_id, text=client_text)
    except Exception as e:
        logger.error(f"Failed to send rejection notification to client {telegram_id}: {e}")


async def _do_rejection(
    bot: Bot,
    session: AsyncSession,
    client_service: ClientService,
    state_data: dict,
    telegram_id: int,
    _: callable,
    reason: str | None = None,
) -> bool:
    """
    Shared deletion + notification logic for all rejection paths.
    Returns True on success, False if client not found.
    """
    client = await client_service.get_client(telegram_id, session)
    if not client:
        return False

    await _cleanup_client_s3_images(client)
    await client_service.delete_client(telegram_id, session)
    await session.commit()

    await _finalize_rejection(
        bot=bot,
        chat_id=state_data.get("reject_chat_id"),
        message_id=state_data.get("reject_message_id"),
        telegram_id=telegram_id,
        full_name=client.full_name,
        _=_,
        reason=reason,
        original_content=state_data.get("original_content"),
    )
    return True


def _load_district_map(region: str, language_code: str) -> dict:
    """Load district name map for the given region and language."""
    filename = "district_ru.json" if language_code == "ru" else "district_uz.json"
    try:
        with open(f"locales/{filename}", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("districts", {}).get(region, {})
    except Exception as e:
        logger.warning(f"Failed to load district map ({filename}): {e}")
        return {}


# ---------------------------------------------------------------------------
# Handlers: Approval
# ---------------------------------------------------------------------------

@approval_router.callback_query(F.data.startswith("approve:"), IsAdmin())
@handle_errors
async def approve_client(
    callback: CallbackQuery,
    session: AsyncSession,
    client_service: ClientService,
    bot: Bot,
    _: callable,
) -> None:
    """Handle client approval."""
    telegram_id = int(callback.data.split(":")[1])

    client = await client_service.get_client(telegram_id, session)
    if not client:
        await callback.answer(_("error-user-not-found"), show_alert=True)
        return

    await callback.answer(_("admin-approved"))

    # Generate client code
    from src.api.utils.code_generator import generate_client_code

    client_code = await generate_client_code(session, client.region, client.district)

    await client_service.update_client(
        telegram_id=telegram_id,
        data={"client_code": client_code, "is_logged_in": True},
        session=session,
    )
    await session.commit()

    # Analytics
    from src.infrastructure.services.analytics_service import AnalyticsService

    await AnalyticsService.emit_event(
        session=session,
        event_type="client_approval",
        user_id=telegram_id,
        payload={
            "client_id":          client.id,
            "client_code":        client_code,
            "full_name":          client.full_name,
            "approved_by_admin_id": callback.from_user.id if callback.from_user else None,
        },
    )
    await session.commit()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(_("admin-approval-success", client_code=client_code))

    # Build region/district label
    district_map = _load_district_map(client.region, client.language_code or "uz")
    region_label = (
        f"{UZBEKISTAN_REGIONS.get(client.region, client.region)}, "
        f"{district_map.get(client.district, client.district)}"
    )

    caption = _(
        "admin-new-user-approved",
        client_code=client.extra_code or client_code,
        full_name=client.full_name,
        passport_series=client.passport_series or "N/A",
        date_of_birth=client.date_of_birth or "N/A",
        region=region_label,
        address=client.address or "N/A",
        phone=client.phone or "N/A",
        pinfl=client.pinfl or "N/A",
        telegram_id=str(telegram_id),
    )

    # Send passport photos to approved channel
    if client.passport_images:
        try:
            file_ids = json.loads(client.passport_images)
            if isinstance(file_ids, list) and file_ids:
                resolved = await resolve_passport_items(file_ids)

                if len(resolved) == 1:
                    await bot.send_photo(
                        chat_id=config.telegram.TASDIQLANGANLAR_CHANNEL_ID,
                        photo=resolved[0],
                        caption=caption,
                        parse_mode="HTML",
                    )
                else:
                    # First photo gets the caption, rest are plain
                    media = [
                        InputMediaPhoto(media=resolved[0], caption=caption, parse_mode="HTML"),
                        *[InputMediaPhoto(media=r) for r in resolved[1:]],
                    ]
                    await bot.send_media_group(
                        chat_id=config.telegram.TASDIQLANGANLAR_CHANNEL_ID,
                        media=media,
                    )
            else:
                logger.warning(f"Invalid passport_images format for {telegram_id}, sending text only")
                await bot.send_message(
                    chat_id=config.telegram.TASDIQLANGANLAR_CHANNEL_ID,
                    text=caption,
                    parse_mode="HTML",
                )
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing passport images for {telegram_id}: {e}")
        except Exception as e:
            logger.error(f"Failed to send passport photos to channel for {telegram_id}: {e}")
            # Fallback: send caption as text so admin at least sees the approval
            try:
                await bot.send_message(
                    chat_id=config.telegram.TASDIQLANGANLAR_CHANNEL_ID,
                    text=caption,
                    parse_mode="HTML",
                )
            except Exception as e2:
                logger.error(f"Fallback text send also failed for {telegram_id}: {e2}")
    else:
        logger.info(f"No passport images for {telegram_id}, sending text only to channel")
        await bot.send_message(
            chat_id=config.telegram.TASDIQLANGANLAR_CHANNEL_ID,
            text=caption,
            parse_mode="HTML",
        )

    # Send Chinese warehouse address + images to client
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        # Walk up to project root (4 levels: admin → handlers → bot → src → root)
        for _i in range(4):
            base_dir = os.path.dirname(base_dir)

        display_code = client.extra_code or client_code
        media = [
            InputMediaPhoto(
                media=FSInputFile(os.path.join(base_dir, "src", "assets", "images", "pindoudou_temp.jpg")),
                caption=(
                    f"{display_code} 18161955318\n"
                    "陕西省咸阳市渭城区 北杜街道\n"
                    f"昭容南街东航物流园内中京仓{display_code}号仓库"
                ),
            ),
            InputMediaPhoto(
                media=FSInputFile(os.path.join(base_dir, "src", "assets", "images", "taobao_temp.jpg")),
            ),
        ]
        await bot.send_media_group(chat_id=telegram_id, media=media)
        await bot.send_message(
            chat_id=telegram_id,
            text=_("client-approval-success-message", client_code=display_code),
            reply_markup=user_main_menu_kyb(translator=_),
        )
    except Exception as e:
        logger.error(f"Failed to send approval messages/images to client {telegram_id}: {e}")
        # DB is already committed — only notification failed, do not re-raise


# ---------------------------------------------------------------------------
# Handlers: Rejection (no reason)
# ---------------------------------------------------------------------------

@approval_router.callback_query(F.data.startswith("reject:"), IsAdmin())
@handle_errors
async def reject_client(
    callback: CallbackQuery,
    session: AsyncSession,
    client_service: ClientService,
    bot: Bot,
    _: callable,
) -> None:
    """Handle client rejection without reason."""
    telegram_id = int(callback.data.split(":")[1])

    client = await client_service.get_client(telegram_id, session)
    if not client:
        await callback.answer(_("error-user-not-found"), show_alert=True)
        return

    await callback.answer(_("admin-rejected"))

    original_content = callback.message.caption or callback.message.text or ""

    await _cleanup_client_s3_images(client)
    await client_service.delete_client(telegram_id, session)
    await session.commit()

    await _finalize_rejection(
        bot=bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        telegram_id=telegram_id,
        full_name=client.full_name,
        _=_,
        reason=None,
        original_content=original_content,
    )


# ---------------------------------------------------------------------------
# Handlers: Rejection with reason
# ---------------------------------------------------------------------------

@approval_router.callback_query(F.data.startswith("reject_reason:"), IsAdmin())
@handle_errors
async def reject_with_reason_start(
    callback: CallbackQuery, state: FSMContext, _: callable
) -> None:
    """Start reject-with-reason flow — ask admin for the reason."""
    telegram_id      = int(callback.data.split(":")[1])
    original_content = callback.message.caption or callback.message.text or ""

    await state.update_data(
        reject_telegram_id=telegram_id,
        reject_message_id=callback.message.message_id,
        reject_chat_id=callback.message.chat.id,
        original_content=original_content,
    )
    await state.set_state(ApprovalStates.waiting_for_reject_reason)
    await callback.answer()
    await callback.message.reply(_("admin-reject-reason-prompt"))


@approval_router.message(
    ApprovalStates.waiting_for_reject_reason, F.text == "/skip", IsAdmin()
)
@handle_errors
async def reject_with_reason_skip(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    client_service: ClientService,
    bot: Bot,
    _: callable,
) -> None:
    """Skip reason and reject without one."""
    data        = await state.get_data()
    telegram_id = data.get("reject_telegram_id")

    if not telegram_id:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    success = await _do_rejection(bot, session, client_service, data, telegram_id, _, reason=None)
    await message.answer(_("admin-rejected") if success else _("error-user-not-found"))
    await state.clear()


@approval_router.message(ApprovalStates.waiting_for_reject_reason, F.text, IsAdmin())
@handle_errors
async def reject_with_reason_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    client_service: ClientService,
    bot: Bot,
    _: callable,
) -> None:
    """Finish reject-with-reason flow."""
    data        = await state.get_data()
    telegram_id = data.get("reject_telegram_id")

    if not telegram_id:
        await message.answer(_("error-occurred"))
        await state.clear()
        return

    success = await _do_rejection(
        bot, session, client_service, data, telegram_id, _, reason=message.text
    )
    await message.answer(_("admin-rejected") if success else _("error-user-not-found"))
    await state.clear()