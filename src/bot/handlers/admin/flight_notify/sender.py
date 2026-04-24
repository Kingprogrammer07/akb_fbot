"""Flight-notify sender — dispatches personalised track-code messages.

Architecture mirrors ``bulk_cargo_sender.BulkCargoSender`` but is intentionally
simpler: no photos, no S3, no payment cards, no cargo-status DB updates.
The only side-effects are Telegram messages and channel log entries.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from src.bot.handlers.admin.bulk_cargo_sender import (
    ChannelLogger,
    _format_duration,
    _generate_task_id,
)
from src.bot.handlers.admin.flight_notify.keyboards import FlightNotifyKeyboards
from src.bot.handlers.admin.flight_notify.models import (
    ClientNotifyData,
    FlightNotifyStats,
    FlightNotifyTask,
)
from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.bot.utils.safe_sender import safe_execute, safe_send_message
from src.config import config

logger = logging.getLogger(__name__)

# Module-level registry: task_id → FlightNotifyTask
_active_notify_tasks: dict[str, FlightNotifyTask] = {}

# Seconds between individual sends (same throttle as bulk_cargo_sender)
_MESSAGE_DELAY: float = 0.05
# Minimum percent progress change that triggers a UI update
_PROGRESS_INTERVAL_PERCENT: int = 5


def generate_notify_task_id(user_id: int) -> str:
    """Generate a unique task identifier for a notify send initiated by *user_id*."""
    return _generate_task_id(user_id)


def get_active_tasks() -> dict[str, FlightNotifyTask]:
    """Return the shared active-task registry (read-only intended)."""
    return _active_notify_tasks


class FlightNotifySender:
    """Sends a personalised track-code notification to every client in a flight.

    Usage::

        sender = FlightNotifySender(
            bot=bot,
            flight_name="M190-M191",
            admin_text="bu sizning M190-M191 dagi yuk hisobingiz",
            clients=resolved_clients,
            admin_chat_id=admin_id,
            task_id=task_id,
        )
        await sender.initialize(progress_message_id)
        stats = await sender.run()
    """

    def __init__(
        self,
        bot: Bot,
        flight_name: str,
        admin_text: str,
        clients: list[ClientNotifyData],
        admin_chat_id: int,
        task_id: str,
    ) -> None:
        self.bot = bot
        self.flight_name = flight_name
        self.admin_text = admin_text
        self.clients = clients
        self.admin_chat_id = admin_chat_id
        self.task_id = task_id

        self.stats = FlightNotifyStats(total=len(clients))
        self.channel_logger = ChannelLogger(bot)
        self._progress_message_id: int | None = None

        # Google Sheets fallback for clients with no DB track codes
        self._sheets_checker = GoogleSheetsChecker(
            spreadsheet_id=config.google_sheets.SHEETS_ID,
            api_key=config.google_sheets.API_KEY,
            last_n_sheets=5,
        )
        # Resolved once in initialize(); None means Sheets lookup will be skipped
        self._resolved_sheet_name: str | None = None

    async def initialize(self, progress_message_id: int) -> None:
        """Store the progress message ID and resolve the Google Sheets worksheet name.

        Args:
            progress_message_id: Telegram message ID that will be edited for progress.
        """
        self._progress_message_id = progress_message_id
        self._resolved_sheet_name = await self._resolve_sheet_name()
        if self._resolved_sheet_name:
            logger.info(
                "flight_notify: resolved %s → worksheet %s",
                self.flight_name,
                self._resolved_sheet_name,
            )
        else:
            logger.warning(
                "flight_notify: could not resolve worksheet for %s — Sheets fallback disabled",
                self.flight_name,
            )

    async def run(self) -> FlightNotifyStats:
        """Execute the send loop and return final statistics.

        Registers itself in ``_active_notify_tasks`` before starting and removes
        itself upon completion regardless of outcome.
        """
        try:
            for client in self.clients:
                if self._is_cancelled():
                    logger.info(
                        "flight_notify: task %s cancelled at %d/%d",
                        self.task_id,
                        self.stats.processed,
                        self.stats.total,
                    )
                    break

                self.stats.processed += 1
                await self._process_client(client)

                if self.stats.should_update_progress(_PROGRESS_INTERVAL_PERCENT):
                    await self._update_progress()

                await asyncio.sleep(_MESSAGE_DELAY)

            await self._finalize()

        except Exception:
            logger.exception("flight_notify: unexpected error in run()")
            await self._report_fatal_error()
        finally:
            _active_notify_tasks.pop(self.task_id, None)

        return self.stats

    # ------------------------------------------------------------------
    # Internal: per-client dispatch
    # ------------------------------------------------------------------

    async def _process_client(self, client: ClientNotifyData) -> None:
        """Send one notification, resolving Sheets fallback when needed."""
        # Resolve track codes from Sheets if DB had none
        if not client.track_codes and self._resolved_sheet_name:
            client.track_codes = await self._fetch_track_codes_from_sheets(
                client.client_code
            )

        if client.is_gx:
            await self._send_to_xorazm_group(client)
            return

        if client.telegram_id is None:
            self.stats.skipped_no_telegram += 1
            self.stats.errors.append(
                (client.client_code, "Telegram ID topilmadi")
            )
            await self.channel_logger.log_failure(
                flight_name=self.flight_name,
                client_id=client.client_code,
                error="Foydalanuvchi bazada topilmadi yoki bot bilan suhbatni boshlamagani",
            )
            return

        message_text = client.build_message(self.flight_name, self.admin_text)
        try:
            await safe_send_message(
                self.bot,
                chat_id=client.telegram_id,
                text=message_text,
                parse_mode="HTML",
            )
            self.stats.sent += 1
            await self.channel_logger.log_success(
                flight_name=self.flight_name,
                client_id=client.client_code,
                telegram_id=client.telegram_id,
                message_text=message_text,
                photo_file_ids=[],
            )

        except TelegramForbiddenError:
            # User has blocked the bot
            self.stats.blocked += 1
            self.stats.errors.append(
                (client.client_code, "Bot bloklangan")
            )
            await self.channel_logger.log_failure(
                flight_name=self.flight_name,
                client_id=client.client_code,
                error="Foydalanuvchi botni bloklagan",
            )

        except Exception as exc:
            reason = str(exc)[:120]
            self.stats.failed += 1
            self.stats.errors.append((client.client_code, reason))
            await self.channel_logger.log_failure(
                flight_name=self.flight_name,
                client_id=client.client_code,
                error=reason,
            )
            logger.warning(
                "flight_notify: send error for %s/%s: %s",
                self.flight_name,
                client.client_code,
                exc,
            )

    async def _send_to_xorazm_group(self, client: ClientNotifyData) -> None:
        """Route GX-coded clients to the AKB Xorazm branch group.

        This mirrors the behaviour of ``BulkCargoSender._send_to_xorazm_group``.
        """
        group_id: int = config.telegram.AKB_XORAZM_FILIALI_GROUP_ID
        message_text = client.build_message(self.flight_name, self.admin_text)
        try:
            await safe_send_message(
                self.bot,
                chat_id=group_id,
                text=message_text,
                parse_mode="HTML",
            )
            self.stats.sent += 1
            await self.channel_logger.log_success(
                flight_name=self.flight_name,
                client_id=client.client_code,
                telegram_id=group_id,
                message_text=message_text,
                photo_file_ids=[],
            )
        except Exception as exc:
            reason = f"GX→guruh xato: {exc!s}"[:120]
            self.stats.failed += 1
            self.stats.errors.append((client.client_code, reason))
            await self.channel_logger.log_failure(
                flight_name=self.flight_name,
                client_id=client.client_code,
                error=reason,
            )

    # ------------------------------------------------------------------
    # Internal: Google Sheets fallback
    # ------------------------------------------------------------------

    async def _fetch_track_codes_from_sheets(self, client_code: str) -> list[str]:
        """Attempt to retrieve track codes from Google Sheets for *client_code*.

        Uses the already-resolved worksheet name so no extra API call is needed
        to map the flight code.
        """
        if not self._resolved_sheet_name:
            return []
        try:
            return await self._sheets_checker.get_track_codes_by_flight_and_client(
                flight_name=self._resolved_sheet_name,
                client_code=client_code,
            )
        except Exception as exc:
            logger.warning(
                "flight_notify: Sheets fallback failed for %s/%s: %s",
                self.flight_name,
                client_code,
                exc,
            )
            return []

    async def _resolve_sheet_name(self) -> str | None:
        """Map the stored flight code to the full Google Sheets worksheet name.

        e.g., "M190" → "M190-M191-2025".
        """
        try:
            sheet_names = await self._sheets_checker.get_flight_sheet_names(last_n=10)
            flight_upper = self.flight_name.strip().upper()
            for name in sheet_names:
                if name.upper().startswith(flight_upper):
                    return name
            # Fallback: return the flight name as-is (may still work if exact)
            return self.flight_name
        except Exception as exc:
            logger.warning(
                "flight_notify: could not fetch sheet names: %s", exc
            )
            return None

    # ------------------------------------------------------------------
    # Internal: progress / finalization
    # ------------------------------------------------------------------

    def _is_cancelled(self) -> bool:
        task = _active_notify_tasks.get(self.task_id)
        return task.cancelled if task else False

    async def _update_progress(self) -> None:
        """Edit the progress message with current counters and a stop button."""
        if self._progress_message_id is None:
            return
        text = (
            f"🚀 <b>Yuborish davom etmoqda...</b>\n\n"
            f"✈️ Reys: {self.flight_name}\n"
            f"👥 Jami: {self.stats.total}\n"
            f"📤 Yuborilmoqda: {self.stats.processed}/{self.stats.total} "
            f"({self.stats.progress_percent}%)\n"
            f"✅ Muvaffaqiyatli: {self.stats.sent}\n"
            f"❌ Xato: {self.stats.failed}\n"
            f"🚫 Bloklangan: {self.stats.blocked}\n"
            f"⏭ O'tkazilgan: {self.stats.skipped_no_telegram}\n\n"
            f"⏱ Qolgan vaqt: {_format_duration(self.stats.estimated_remaining)}"
        )
        try:
            await safe_execute(
                self.bot.edit_message_text,
                chat_id=self.admin_chat_id,
                message_id=self._progress_message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=FlightNotifyKeyboards.stop_button(self.task_id),
            )
        except Exception as exc:
            logger.warning("flight_notify: progress update failed: %s", exc)

    async def _finalize(self) -> None:
        """Replace the progress message with the final summary."""
        text = (
            f"✅ <b>Yuborish yakunlandi!</b>\n\n"
            f"✈️ Reys: {self.flight_name}\n"
            f"👥 Jami mijozlar: {self.stats.total}\n"
            f"✅ Muvaffaqiyatli: {self.stats.sent}\n"
            f"❌ Xato: {self.stats.failed}\n"
            f"🚫 Bloklangan: {self.stats.blocked}\n"
            f"⏭ Telegram ID yo'q: {self.stats.skipped_no_telegram}\n\n"
            f"⏱ Jami vaqt: {_format_duration(self.stats.elapsed_time)}"
        )
        if self._progress_message_id is not None:
            try:
                await safe_execute(
                    self.bot.edit_message_text,
                    chat_id=self.admin_chat_id,
                    message_id=self._progress_message_id,
                    text=text,
                    parse_mode="HTML",
                )
            except Exception as exc:
                logger.warning("flight_notify: finalize edit failed: %s", exc)
                await safe_send_message(
                    self.bot,
                    chat_id=self.admin_chat_id,
                    text=text,
                    parse_mode="HTML",
                )

        if self.stats.errors:
            await self._send_error_summary()

    async def _report_fatal_error(self) -> None:
        """Notify admin of an unexpected crash."""
        try:
            await safe_send_message(
                self.bot,
                chat_id=self.admin_chat_id,
                text=(
                    f"❌ <b>Yuborish jarayonida kutilmagan xato yuz berdi!</b>\n\n"
                    f"✈️ Reys: {self.flight_name}\n"
                    f"📤 Yuborilgan: {self.stats.sent}/{self.stats.total}"
                ),
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("flight_notify: could not report fatal error to admin")

    async def _send_error_summary(self) -> None:
        """Send a plain-text error summary when there were failed sends."""
        lines = [
            f"• {code}: {reason[:60]}"
            for code, reason in self.stats.errors[:20]
        ]
        overflow = (
            f"\n... va yana {len(self.stats.errors) - 20} ta"
            if len(self.stats.errors) > 20
            else ""
        )
        text = (
            f"⚠️ <b>Yuborilmagan mijozlar</b>\n\n"
            f"✈️ Reys: {self.flight_name}\n"
            f"❌ Jami: {len(self.stats.errors)}\n\n"
            + "\n".join(lines)
            + overflow
        )
        await safe_send_message(
            self.bot,
            chat_id=self.admin_chat_id,
            text=text,
            parse_mode="HTML",
        )


