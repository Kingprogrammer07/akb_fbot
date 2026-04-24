"""Telegram utilities for API operations."""
import asyncio
import logging
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import (
    BufferedInputFile,
    InputMediaDocument,
    InputMediaPhoto,
    ReplyKeyboardRemove,
)
from fastapi import UploadFile

from src.config import config
from src.bot.keyboards.inline_kb.approval import approval_keyboard
from src.api.utils.image_processing import process_upload_file
from src.bot.utils.safe_sender import safe_send_message
from src.infrastructure.tools.passport_image_resolver import resolve_passport_items

logger = logging.getLogger(__name__)

# Delay between sequential messages to avoid Telegram flood limits
SEQUENTIAL_SEND_DELAY = 0.3


async def upload_passport_images_to_telegram(
    chat_id: int,
    passport_images: list[UploadFile],
    bot: Bot
) -> list[str]:
    """
    Upload passport images to Telegram and get file_ids.
    Deletes uploaded messages from chat after getting file_id.

    Each file is pre-processed via ``process_upload_file`` (JPEG conversion).
    Tries send_photo first; falls back to send_document on failure
    (e.g. IMAGE_PROCESS_FAILED for unsupported formats).

    Args:
        chat_id: Chat ID to upload images to (user or admin)
        passport_images: List of uploaded files
        bot: Bot instance

    Returns:
        List of file_ids
    """
    file_ids = []
    message_ids_to_delete = []
    files_count = len(passport_images)

    logger.info(f"⬆️ Starting passport upload: chat_id={chat_id}, files_count={files_count}")

    try:
        for idx, image in enumerate(passport_images):
            # Process image (JPEG conversion with fallback to original)
            image_data, filename = await process_upload_file(image)

            if not image_data:
                logger.warning(f"⚠️ Skipping empty file: filename={image.filename}, index={idx}/{files_count}")
                continue

            input_file = BufferedInputFile(image_data, filename=filename)

            try:
                # Try sending as photo first
                msg = await bot.send_photo(chat_id=chat_id, photo=input_file)
                file_ids.append(msg.photo[-1].file_id)
                logger.debug(f"✅ Uploaded as photo: filename={filename}, index={idx}/{files_count}")
            except TelegramBadRequest as e:
                logger.warning(
                    f"⚠️ send_photo failed for filename={filename}, index={idx}/{files_count}, "
                    f"chat_id={chat_id}: {e}. Falling back to send_document.",
                    exc_info=True
                )
                # Re-wrap bytes because the input file may have been consumed
                input_file = BufferedInputFile(image_data, filename=filename)
                try:
                    msg = await bot.send_document(chat_id=chat_id, document=input_file)
                    file_ids.append(msg.document.file_id)
                    logger.debug(f"✅ Uploaded as document (fallback): filename={filename}, index={idx}/{files_count}")
                except Exception as doc_err:
                    logger.error(
                        f"❌ send_document also failed for filename={filename}, index={idx}/{files_count}, "
                        f"chat_id={chat_id}: {doc_err}",
                        exc_info=True
                    )
                    raise

            message_ids_to_delete.append(msg.message_id)

        # Delete all uploaded messages from chat
        for msg_id in message_ids_to_delete:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.warning(f"⚠️ Failed to delete message {msg_id} in chat_id={chat_id}: {e}")

        logger.info(f"✅ Passport upload complete: chat_id={chat_id}, uploaded={len(file_ids)}/{files_count}")
        return file_ids

    except Exception as e:
        logger.error(
            f"❌ Failed to upload passport images: chat_id={chat_id}, files_count={files_count}, "
            f"uploaded_so_far={len(file_ids)}: {e}",
            exc_info=True
        )
        raise


# ---------------------------------------------------------------------------
#  Phase 1 helpers — best-effort image delivery (never raises)
# ---------------------------------------------------------------------------

async def _try_send_album(
    bot: Bot,
    chat_id: int,
    file_ids: list[str],
) -> bool:
    """Try sending file_ids as a photo album, falling back to document album."""
    try:
        media = [InputMediaPhoto(media=fid) for fid in file_ids]
        await bot.send_media_group(chat_id=chat_id, media=media)
        logger.debug(f"✅ Album sent as photos: file_ids={len(file_ids)}")
        return True
    except Exception as photo_err:
        logger.warning(f"⚠️ Photo album failed: {photo_err}")

    try:
        media = [InputMediaDocument(media=fid) for fid in file_ids]
        await bot.send_media_group(chat_id=chat_id, media=media)
        logger.debug(f"✅ Album sent as documents: file_ids={len(file_ids)}")
        return True
    except Exception as doc_err:
        logger.warning(f"⚠️ Document album also failed: {doc_err}")
        return False


async def _try_send_sequential(
    bot: Bot,
    chat_id: int,
    file_ids: list[str],
) -> bool:
    """Try sending each file_id individually as photo, then document fallback."""
    for i, file_id in enumerate(file_ids):
        if i > 0:
            await asyncio.sleep(SEQUENTIAL_SEND_DELAY)

        sent = False
        # Try photo
        try:
            await bot.send_photo(chat_id=chat_id, photo=file_id)
            sent = True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.send_photo(chat_id=chat_id, photo=file_id)
                sent = True
            except Exception:
                pass
        except Exception:
            pass

        if sent:
            continue

        # Try document fallback
        try:
            await bot.send_document(chat_id=chat_id, document=file_id)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.send_document(chat_id=chat_id, document=file_id)
            except Exception as exc:
                logger.warning(f"⚠️ Sequential send failed for file {i}: {exc}")
                return False
        except Exception as exc:
            logger.warning(f"⚠️ Sequential send failed for file {i}: {exc}")
            return False

    logger.debug(f"✅ Sequential send complete: {len(file_ids)} files")
    return True


async def _best_effort_send_images(
    bot: Bot,
    chat_id: int,
    file_ids: list[str],
) -> None:
    """Phase 1: Try every strategy to send images. Never raises.

    Order:
    1. Single image → send_photo → send_document
    2. Multiple images → album → sequential photo/document
    """
    if not file_ids:
        return

    try:
        if len(file_ids) == 1:
            fid = file_ids[0]
            try:
                await bot.send_photo(chat_id=chat_id, photo=fid)
                return
            except Exception:
                pass
            try:
                await bot.send_document(chat_id=chat_id, document=fid)
                return
            except Exception:
                logger.warning(f"⚠️ Single image send failed for chat_id={chat_id}")
                return

        # Multiple images
        if await _try_send_album(bot, chat_id, file_ids):
            return

        if await _try_send_sequential(bot, chat_id, file_ids):
            return

        logger.warning(
            f"⚠️ All image send strategies failed: chat_id={chat_id}, "
            f"file_ids_count={len(file_ids)}"
        )
    except Exception as exc:
        logger.error(
            f"❌ Unexpected error in image delivery: chat_id={chat_id}, "
            f"file_ids_count={len(file_ids)}: {exc}",
            exc_info=True,
        )


# ---------------------------------------------------------------------------
#  Public API — guaranteed delivery functions
# ---------------------------------------------------------------------------

async def send_registration_to_approval_group(
    telegram_id: int | None,
    full_name: str,
    passport_series: str,
    date_of_birth: str,
    region: str,
    address: str,
    phone: str,
    pinfl: str,
    s3_keys: list[str],
    bot: Bot
) -> None:
    """
    Send registration request to approval group with **guaranteed delivery**.

    Phase 1 (Visuals — best effort):
        Resolve S3 keys to presigned URLs and send passport images.
        Falls back gracefully for legacy Telegram file_ids.
        If images fail, log the error and continue — do NOT return.

    Phase 2 (Action — guaranteed):
        Always send the caption text with approval buttons via send_message.
        This ensures the admin always gets the data and can act on it.
    """
    tg_id_display = str(telegram_id) if telegram_id else "❌ Mavjud emas (Offline)"

    caption = (
        f"📝 <b>Yangi ro'yxatdan o'tish so'rovi:</b>\n\n"
        f"👤 <b>Ism:</b> {full_name}\n"
        f"📇 <b>Passport:</b> {passport_series}\n"
        f"📅 <b>Tug'ilgan sana:</b> {date_of_birth}\n"
        f"🏠 <b>Manzil:</b> {region}, {address}\n"
        f"📞 <b>Telefon:</b> {phone}\n"
        f"🔢 <b>PINFL:</b> {pinfl}\n"
        f"🆔 <b>Telegram ID:</b> {tg_id_display}\n"
    )

    reply_markup = approval_keyboard(telegram_id) if telegram_id else None
    group_id = config.telegram.TASDIQLASH_GROUP_ID

    logger.info(
        f"📤 Sending approval request: telegram_id={telegram_id}, full_name={full_name}, "
        f"s3_keys_count={len(s3_keys)}, group_id={group_id}"
    )

    # ── Phase 1: Visuals (best effort) ──────────────────────────────
    if s3_keys:
        resolved = await resolve_passport_items(s3_keys)
        if resolved:
            await _best_effort_send_images(bot, group_id, resolved)

    # ── Phase 2: Caption + Buttons (guaranteed) ─────────────────────
    try:
        await bot.send_message(
            chat_id=group_id,
            text=caption,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        logger.info(f"✅ Approval caption sent: telegram_id={telegram_id}")
    except Exception as exc:
        logger.critical(
            f"❌ CRITICAL: Failed to send approval caption! "
            f"telegram_id={telegram_id}, full_name={full_name}, "
            f"group_id={group_id}: {exc}",
            exc_info=True,
        )


async def send_approved_notification(
    bot: Bot,
    channel_id: int | str,
    file_ids: list[str],
    caption: str,
    telegram_id: int
) -> None:
    """Send approved client notification to channel with **guaranteed delivery**.

    Phase 1 (Visuals — best effort):
        Resolve S3 keys to presigned URLs and send passport images.
        Falls back gracefully for legacy Telegram file_ids.
        Failures are logged, never raised.

    Phase 2 (Caption — guaranteed):
        Always send the caption text via send_message.

    Args:
        bot: Bot instance
        channel_id: Target channel ID
        file_ids: List of passport image S3 keys or legacy Telegram file_ids
        caption: Full caption text for the notification
        telegram_id: User's Telegram ID (used for logging)
    """
    logger.info(
        f"📤 Sending approved notification: telegram_id={telegram_id}, "
        f"file_ids_count={len(file_ids)}, channel_id={channel_id}"
    )

    # ── Phase 1: Visuals (best effort) ──────────────────────────────
    if file_ids:
        resolved = await resolve_passport_items(file_ids)
        if resolved:
            await _best_effort_send_images(bot, channel_id, resolved)

    # ── Phase 2: Caption (guaranteed with retry) ────────────────────
    try:
        await safe_send_message(
            bot=bot,
            chat_id=channel_id,
            text=caption,
            parse_mode="HTML",
        )
        logger.info(f"✅ Approved caption sent to channel: telegram_id={telegram_id}")
    except Exception as exc:
        logger.critical(
            f"❌ CRITICAL: Failed to send approved caption to channel! "
            f"telegram_id={telegram_id}, channel_id={channel_id}: {exc}",
            exc_info=True,
        )


async def send_waiting_message_to_user(telegram_id: int | None, bot: Bot, message: str) -> None:
    """
    Send waiting message to user after registration.

    Args:
        telegram_id: User's Telegram ID (can be None for offline clients)
        bot: Bot instance
        message: Message text to send
    """
    if not telegram_id:
        return  # Skip sending message if user has no Telegram

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=message,
            reply_markup=ReplyKeyboardRemove()
        )
        logger.debug(f"✅ Waiting message sent to telegram_id={telegram_id}")
    except Exception as e:
        logger.error(
            f"❌ Failed to send waiting message: telegram_id={telegram_id}, "
            f"message_preview='{message[:20]}...': {e}",
            exc_info=True
        )
