"""Broadcast message sender."""

import asyncio
import time
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import (
    InputMediaPhoto, InputMediaVideo,
    InputMediaDocument, InputMediaAudio
)
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from src.bot.handlers.admin.broadcast.constants import (
    MESSAGE_DELAY, PROGRESS_UPDATE_INTERVAL, MAX_ALBUM_SIZE,
    STATS_SAVE_INTERVAL
)
from src.bot.handlers.admin.broadcast.models import BroadcastContent, BroadcastStats
from src.bot.handlers.admin.broadcast.utils import (
    build_inline_keyboard, format_time_remaining, entities_to_telegram_format
)
from src.bot.handlers.admin.broadcast.keyboards import BroadcastKeyboards
from src.infrastructure.database.dao.broadcast import BroadcastDAO
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.models.broadcast import BroadcastStatus
from src.infrastructure.database.client import DatabaseClient
from src.config import config


class BroadcastSender:
    """Handles broadcast message delivery."""
    
    def __init__(
        self,
        bot: Bot,
        broadcast_id: int,
        content: BroadcastContent,
        admin_chat_id: int,
        progress_message_id: int,
        task_id: str,
        cancellation_flag: dict
    ):
        self.bot = bot
        self.broadcast_id = broadcast_id
        self.content = content
        self.admin_chat_id = admin_chat_id
        self.progress_message_id = progress_message_id
        self.task_id = task_id
        self.cancellation_flag = cancellation_flag
        
        self.stats = BroadcastStats()
        self.start_time = time.time()
    
    async def send_to_all(self) -> BroadcastStats:
        """
        Send broadcast to all users with progress tracking.
        
        Uses a single DB session for the entire broadcast lifecycle
        to prevent connection pool exhaustion.
        
        Returns:
            Final broadcast statistics
        """
        async with DatabaseClient(config.database.database_url) as db_client:
            async with db_client.session_factory() as session:
                try:
                    # Update status to sending
                    await self._update_status(session, BroadcastStatus.SENDING)
                    await self._mark_started(session)
                    
                    # Get all recipients
                    clients = await self._get_recipients(session)
                    self.stats.total = len(clients)
                    
                    # Send to each user
                    for client in clients:
                        if self.cancellation_flag.get("cancelled"):
                            await self._handle_cancellation(session)
                            break
                        
                        if not client.telegram_id:
                            self.stats.failed += 1
                            self.stats.processed += 1
                            continue
                        
                        # Send message
                        result = await self._send_to_user(client.telegram_id)
                        
                        # Update statistics
                        self._update_stats(result)
                        
                        # Update progress display
                        await self._maybe_update_progress()
                        
                        # Batch save stats to DB (every N users)
                        if self.stats.processed % STATS_SAVE_INTERVAL == 0:
                            await self._save_stats(session)
                        
                        # Anti-spam delay
                        await asyncio.sleep(MESSAGE_DELAY)
                    
                    # Final save of stats
                    await self._save_stats(session)
                    
                    # Mark as completed
                    if not self.cancellation_flag.get("cancelled"):
                        await self._mark_completed(session)
                        await self._show_final_results()
                    
                    return self.stats
                    
                except Exception as e:
                    await self._handle_error(session, e)
                    raise
    
    async def _send_to_user(self, telegram_id: int) -> dict:
        """
        Send broadcast message to single user.

        Args:
            telegram_id: User's Telegram ID

        Returns:
            Result dictionary with status
        """
        keyboard = build_inline_keyboard(self.content.buttons)
        entities = entities_to_telegram_format(self.content.caption_entities)

        try:
            if self.content.is_forward():
                await self.bot.forward_message(
                    chat_id=telegram_id,
                    from_chat_id=self.content.forward_from_chat_id,
                    message_id=self.content.forward_message_id
                )
            elif self.content.media_type == "text":
                await self.bot.send_message(
                    chat_id=telegram_id,
                    text=self.content.caption or "Xabar",
                    entities=entities,
                    reply_markup=keyboard
                )
            elif self.content.is_album():
                await self._send_album(telegram_id, keyboard)
            else:
                await self._send_single_media(telegram_id, keyboard)

            return {"success": True, "status": "sent"}

        except TelegramForbiddenError:
            return {"success": False, "status": "blocked"}
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            return {"success": False, "status": "retry_after"}
        except Exception as e:
            return {"success": False, "status": "error", "error": str(e)}
    
    async def _send_single_media(self, telegram_id: int, keyboard):
        """Send single media item."""
        file_id = self.content.file_ids[0]
        caption = self.content.caption
        entities = entities_to_telegram_format(self.content.caption_entities)

        if self.content.media_type == "photo":
            await self.bot.send_photo(
                telegram_id, file_id, caption=caption,
                caption_entities=entities,
                reply_markup=keyboard
            )
        elif self.content.media_type == "video":
            await self.bot.send_video(
                telegram_id, file_id, caption=caption,
                caption_entities=entities,
                reply_markup=keyboard
            )
        elif self.content.media_type == "document":
            await self.bot.send_document(
                telegram_id, file_id, caption=caption,
                caption_entities=entities,
                reply_markup=keyboard
            )
        elif self.content.media_type == "audio":
            await self.bot.send_audio(
                telegram_id, file_id, caption=caption,
                caption_entities=entities,
                reply_markup=keyboard
            )
        elif self.content.media_type == "voice":
            await self.bot.send_voice(
                telegram_id, file_id, caption=caption,
                caption_entities=entities,
                reply_markup=keyboard
            )
    
    async def _send_album(self, telegram_id: int, keyboard):
        """Send media album."""
        media_class_map = {
            "photo_album": InputMediaPhoto,
            "video_album": InputMediaVideo,
            "document_album": InputMediaDocument,
            "audio_album": InputMediaAudio
        }

        media_class = media_class_map.get(self.content.media_type)
        if not media_class:
            return

        entities = entities_to_telegram_format(self.content.caption_entities)

        # Build media group (max 10 items)
        media = [
            media_class(
                media=file_id,
                caption=self.content.caption if idx == 0 else None,
                caption_entities=entities if idx == 0 else None
            )
            for idx, file_id in enumerate(self.content.file_ids[:MAX_ALBUM_SIZE])
        ]

        await self.bot.send_media_group(telegram_id, media)

        # Send buttons separately if present
        if keyboard:
            await self.bot.send_message(
                telegram_id, "⬇️", reply_markup=keyboard
            )
    
    def _update_stats(self, result: dict):
        """Update statistics based on send result."""
        self.stats.processed += 1
        
        if result["success"]:
            self.stats.sent += 1
        elif result["status"] == "blocked":
            self.stats.blocked += 1
        else:
            self.stats.failed += 1
    
    async def _maybe_update_progress(self):
        """Update progress display if threshold reached."""
        update_interval = max(1, self.stats.total // PROGRESS_UPDATE_INTERVAL)
        
        if (self.stats.processed % update_interval == 0 or 
            self.stats.processed == self.stats.total):
            await self._update_progress_display()
    
    async def _update_progress_display(self):
        """Update progress message with current statistics."""
        elapsed = time.time() - self.start_time
        avg_time = elapsed / self.stats.processed if self.stats.processed > 0 else 0
        remaining_count = self.stats.total - self.stats.processed
        remaining_seconds = remaining_count * avg_time
        
        text = (
            f"📤 <b>Yuborilmoqda...</b>\n\n"
            f"{self.stats.format_status()}\n\n"
            f"⏱ Qolgan vaqt: {format_time_remaining(remaining_seconds)}"
        )
        
        try:
            await self.bot.edit_message_text(
                chat_id=self.admin_chat_id,
                message_id=self.progress_message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=BroadcastKeyboards.stop_broadcast(self.task_id)
            )
        except Exception:
            pass  # Ignore edit errors
    
    async def _show_final_results(self):
        """Display final broadcast results."""
        total_time = time.time() - self.start_time
        
        text = (
            f"✅ <b>Yuborish yakunlandi!</b>\n\n"
            f"{self.stats.format_status()}\n\n"
            f"⏱ Jami vaqt: {format_time_remaining(total_time)}\n"
            f"📈 Muvaffaqiyat darajasi: {self.stats.success_rate:.1f}%"
        )
        
        try:
            await self.bot.edit_message_text(
                chat_id=self.admin_chat_id,
                message_id=self.progress_message_id,
                text=text,
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    async def _get_recipients(self, session) -> list:
        """Get broadcast recipients based on audience type."""
        if self.content.audience_type == "all":
            return await ClientDAO.get_all(session)
        elif self.content.audience_type == "selected":
            return await ClientDAO.get_by_client_codes(
                session, self.content.target_client_codes
            )
        else:
            return []
    
    async def _update_status(self, session, status: BroadcastStatus):
        """Update broadcast status in database."""
        await BroadcastDAO.update_status(session, self.broadcast_id, status)
        await session.commit()
    
    async def _mark_started(self, session):
        """Mark broadcast as started."""
        broadcast = await BroadcastDAO.get_by_id(session, self.broadcast_id)
        broadcast.started_at = datetime.now(timezone.utc)
        await session.commit()
    
    async def _mark_completed(self, session):
        """Mark broadcast as completed."""
        broadcast = await BroadcastDAO.get_by_id(session, self.broadcast_id)
        broadcast.status = BroadcastStatus.COMPLETED
        broadcast.completed_at = datetime.now(timezone.utc)
        await session.commit()
    
    async def _save_stats(self, session):
        """Save current statistics to database."""
        await BroadcastDAO.update_statistics(
            session, self.broadcast_id,
            self.stats.sent, self.stats.failed, self.stats.blocked
        )
        await session.commit()
    
    async def _handle_cancellation(self, session):
        """Handle broadcast cancellation."""
        await self._update_status(session, BroadcastStatus.CANCELLED)
        
        try:
            await self.bot.edit_message_text(
                chat_id=self.admin_chat_id,
                message_id=self.progress_message_id,
                text=(
                    f"⏸ <b>Yuborish to'xtatildi!</b>\n\n"
                    f"{self.stats.format_status()}"
                ),
                parse_mode="HTML"
            )
        except Exception:
            await session.rollback()
            pass
    
    async def _handle_error(self, session, error: Exception):
        """Handle broadcast error."""
        await self._update_status(session, BroadcastStatus.FAILED)
        
        try:
            await self.bot.send_message(
                chat_id=self.admin_chat_id,
                text=f"❌ Yuborishda xatolik: {str(error)}"
            )
        except Exception:
            await session.rollback()
            pass