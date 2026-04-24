"""
Telegram log handler with async queue, rate limiting,
error fingerprinting, and graceful shutdown support.

Architecture:
    1. Synchronous emit() puts log records into asyncio.Queue (non-blocking)
    2. Background worker task consumes queue and sends to Telegram
    3. Rate limiting: max 1 message per interval (configurable)
    4. Fingerprinting: duplicate errors (same hash) suppressed within interval
    5. Graceful shutdown: drain queue before stopping

Thread-safety:
    - Queue operations are thread-safe via asyncio.Queue
    - Rate limit state protected by asyncio.Lock
    - Safe to use from any thread (emit uses call_soon_threadsafe)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
import time
import weakref
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop

# Module-level registry for handler instances (for graceful shutdown)
_handler_instances: weakref.WeakSet[ReliableTelegramLogHandler] = weakref.WeakSet()


@dataclass
class LogEntry:
    """Represents a queued log entry."""

    formatted_message: str
    fingerprint: str
    level: int
    level_name: str
    logger_name: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class RateLimitState:
    """Tracks rate limiting and deduplication state."""

    last_sent_time: float = 0.0
    fingerprint_cache: dict[str, float] = field(default_factory=dict)
    suppressed_count: int = 0
    last_suppression_report_time: float = 0.0


class ReliableTelegramLogHandler(logging.Handler):
    """
    Async-safe logging handler that sends ERROR/CRITICAL logs to Telegram.

    Features:
        - Non-blocking: uses asyncio.Queue for async processing
        - Rate limiting: configurable minimum interval between messages
        - Deduplication: same error fingerprint suppressed within interval
        - Graceful shutdown: drains queue before stopping
        - Webhook-safe: won't cause recursive failures

    Usage:
        handler = ReliableTelegramLogHandler(
            bot_token="...",
            admin_chat_ids=[123456789],
            rate_limit_seconds=60,
            dedup_window_seconds=300,
        )
        handler.start(loop)  # Start background worker
        logging.getLogger().addHandler(handler)

        # On shutdown:
        await handler.shutdown()
    """

    # Telegram message limits
    MAX_MESSAGE_LENGTH = 4000
    EMOJI_ERROR = "\U0001F6A8"  # 🚨
    EMOJI_CRITICAL = "\U0001F4A5"  # 💥
    EMOJI_SUPPRESSED = "\U0001F507"  # 🔇

    def __init__(
        self,
        bot_token: str,
        admin_chat_ids: int | Iterable[int],
        level: int = logging.ERROR,
        rate_limit_seconds: float = 60.0,
        dedup_window_seconds: float = 300.0,
        queue_size: int = 1000,
        flush_timeout_seconds: float = 10.0,
        suppression_report_interval: float = 300.0,
    ) -> None:
        """
        Initialize the handler.

        Args:
            bot_token: Telegram bot token
            admin_chat_ids: Single chat ID or iterable of chat IDs to send logs to
            level: Minimum log level (default: ERROR)
            rate_limit_seconds: Minimum seconds between any two messages
            dedup_window_seconds: Window for suppressing duplicate errors
            queue_size: Maximum queue size (oldest dropped if full)
            flush_timeout_seconds: Max time to wait for queue drain on shutdown
            suppression_report_interval: How often to report suppressed message counts
        """
        super().__init__(level)

        # Normalize admin_chat_ids to list
        if isinstance(admin_chat_ids, int):
            self._admin_chat_ids: list[int] = [admin_chat_ids]
        else:
            self._admin_chat_ids = list(admin_chat_ids)

        if not self._admin_chat_ids:
            raise ValueError("At least one admin_chat_id must be provided")

        self._bot_token = bot_token
        self._bot: Bot | None = None

        # Configuration
        self._rate_limit_seconds = rate_limit_seconds
        self._dedup_window_seconds = dedup_window_seconds
        self._queue_size = queue_size
        self._flush_timeout_seconds = flush_timeout_seconds
        self._suppression_report_interval = suppression_report_interval

        # Runtime state
        self._queue: asyncio.Queue[LogEntry | None] | None = None
        self._worker_task: asyncio.Task | None = None
        self._state = RateLimitState()
        self._state_lock: asyncio.Lock | None = None
        self._loop: AbstractEventLoop | None = None
        self._started = False
        self._shutting_down = False

        # Register for global shutdown
        _handler_instances.add(self)

    def _compute_fingerprint(self, record: logging.LogRecord) -> str:
        """
        Compute a fingerprint for deduplication.

        Uses: logger name + level + message template (without args).
        This groups similar errors even if arguments differ slightly.
        """
        # Use getMessage() but hash it - this captures the formatted message
        # For more aggressive dedup, could use record.msg (template) instead
        content = f"{record.name}:{record.levelno}:{record.getMessage()}"
        return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()[:16]

    def start(self, loop: AbstractEventLoop | None = None) -> None:
        """
        Start the background worker task.

        Must be called after the event loop is running.

        Args:
            loop: Event loop to use. If None, uses asyncio.get_running_loop()
        """
        if self._started:
            return

        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running loop - defer start
                return

        self._loop = loop
        self._queue = asyncio.Queue(maxsize=self._queue_size)
        self._state_lock = asyncio.Lock()
        self._bot = Bot(token=self._bot_token)

        self._worker_task = loop.create_task(
            self._worker(),
            name="telegram_log_worker",
        )
        self._started = True

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record by queuing it for async processing.

        This method is called by the logging framework and must be non-blocking.
        It is thread-safe.
        """
        # Skip if not started or shutting down
        if not self._started or self._shutting_down:
            return

        # Skip internal logging to prevent recursion
        if record.name.startswith("aiogram") or record.name.startswith("aiohttp"):
            return

        try:
            # Format the message synchronously
            formatted = self.format(record)
            fingerprint = self._compute_fingerprint(record)

            entry = LogEntry(
                formatted_message=formatted,
                fingerprint=fingerprint,
                level=record.levelno,
                level_name=record.levelname,
                logger_name=record.name,
            )

            # Queue the entry (non-blocking from sync context)
            if self._loop is not None and self._queue is not None:
                # Thread-safe queue put
                self._loop.call_soon_threadsafe(self._try_put, entry)

        except Exception:
            # Never raise from emit - silently drop on error
            self.handleError(record)

    def _try_put(self, entry: LogEntry) -> None:
        """Try to put entry in queue, dropping oldest if full."""
        if self._queue is None:
            return

        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            # Drop oldest entry and retry
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(entry)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    async def _worker(self) -> None:
        """
        Background worker that processes the log queue.

        Handles rate limiting, deduplication, and sending to Telegram.
        """
        while True:
            try:
                # Wait for next entry (or shutdown signal)
                entry = await self._queue.get()

                # None signals shutdown
                if entry is None:
                    self._queue.task_done()
                    break

                # Process the entry
                await self._process_entry(entry)
                self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log to stderr to avoid recursion
                print(
                    f"[TelegramLogHandler] Worker error: {type(e).__name__}: {e}",
                    file=sys.stderr,
                )
                await asyncio.sleep(1)  # Backoff on error

    async def _process_entry(self, entry: LogEntry) -> None:
        """Process a single log entry with rate limiting and deduplication."""
        if self._state_lock is None:
            return

        async with self._state_lock:
            now = time.time()

            # Check deduplication
            if entry.fingerprint in self._state.fingerprint_cache:
                last_seen = self._state.fingerprint_cache[entry.fingerprint]
                if now - last_seen < self._dedup_window_seconds:
                    self._state.suppressed_count += 1
                    # Maybe send suppression report
                    await self._maybe_send_suppression_report(now)
                    return

            # Check rate limit
            time_since_last = now - self._state.last_sent_time
            if time_since_last < self._rate_limit_seconds:
                # Queue entry for later? For now, just note suppression
                self._state.suppressed_count += 1
                await self._maybe_send_suppression_report(now)
                return

            # Update state
            self._state.fingerprint_cache[entry.fingerprint] = now
            self._state.last_sent_time = now

            # Clean old fingerprints
            self._cleanup_fingerprint_cache(now)

        # Send message (outside lock)
        await self._send_to_telegram(entry)

    def _cleanup_fingerprint_cache(self, now: float) -> None:
        """Remove expired fingerprints from cache."""
        expired = [
            fp
            for fp, ts in self._state.fingerprint_cache.items()
            if now - ts > self._dedup_window_seconds
        ]
        for fp in expired:
            del self._state.fingerprint_cache[fp]

    async def _maybe_send_suppression_report(self, now: float) -> None:
        """Periodically report how many messages were suppressed."""
        if self._state.suppressed_count == 0:
            return

        time_since_report = now - self._state.last_suppression_report_time
        if time_since_report < self._suppression_report_interval:
            return

        # Check rate limit for suppression report too
        time_since_last = now - self._state.last_sent_time
        if time_since_last < self._rate_limit_seconds:
            return

        count = self._state.suppressed_count
        self._state.suppressed_count = 0
        self._state.last_suppression_report_time = now
        self._state.last_sent_time = now

        message = (
            f"{self.EMOJI_SUPPRESSED} <b>Log Suppression Report</b>\n\n"
            f"Suppressed <b>{count}</b> duplicate/rate-limited log messages "
            f"in the last {int(self._suppression_report_interval)} seconds."
        )

        await self._send_raw_message(message)

    async def _send_to_telegram(self, entry: LogEntry) -> None:
        """Format and send a log entry to Telegram."""
        emoji = self.EMOJI_CRITICAL if entry.level >= logging.CRITICAL else self.EMOJI_ERROR

        # Truncate message if needed
        msg_body = entry.formatted_message
        if len(msg_body) > self.MAX_MESSAGE_LENGTH - 200:  # Reserve space for header
            msg_body = msg_body[: self.MAX_MESSAGE_LENGTH - 200] + "\n\n[...truncated...]"

        message = (
            f"{emoji} <b>{entry.level_name}</b> {emoji}\n"
            f"<code>{entry.logger_name}</code>\n\n"
            f"<pre>{self._escape_html(msg_body)}</pre>"
        )

        await self._send_raw_message(message)

    async def _send_raw_message(self, message: str) -> None:
        """Send a raw message to all admin chat IDs."""
        if self._bot is None:
            return

        for chat_id in self._admin_chat_ids:
            try:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=message[:self.MAX_MESSAGE_LENGTH],
                    parse_mode="HTML",
                )
            except TelegramAPIError as e:
                # Log to stderr to avoid recursion
                print(
                    f"[TelegramLogHandler] Failed to send to {chat_id}: {e}",
                    file=sys.stderr,
                )
            except Exception as e:
                print(
                    f"[TelegramLogHandler] Unexpected error sending to {chat_id}: "
                    f"{type(e).__name__}: {e}",
                    file=sys.stderr,
                )

    @staticmethod
    def _escape_html(text: str) -> str:
        """Escape HTML special characters for Telegram."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    async def shutdown(self, timeout: float | None = None) -> None:
        """
        Gracefully shutdown the handler.

        Drains the queue and stops the worker task.

        Args:
            timeout: Max seconds to wait for drain. Uses flush_timeout_seconds if None.
        """
        if not self._started or self._shutting_down:
            return

        self._shutting_down = True
        timeout = timeout if timeout is not None else self._flush_timeout_seconds

        try:
            # Signal worker to stop
            if self._queue is not None:
                await asyncio.wait_for(
                    self._queue.put(None),
                    timeout=timeout / 2,
                )

            # Wait for worker to finish
            if self._worker_task is not None:
                await asyncio.wait_for(
                    self._worker_task,
                    timeout=timeout / 2,
                )

        except asyncio.TimeoutError:
            print(
                "[TelegramLogHandler] Shutdown timeout - some logs may be lost",
                file=sys.stderr,
            )
            if self._worker_task is not None:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass

        finally:
            # Close bot session
            if self._bot is not None:
                try:
                    await self._bot.session.close()
                except Exception:
                    pass
                self._bot = None

            self._started = False

    def close(self) -> None:
        """
        Close the handler (synchronous).

        For async cleanup, use shutdown() instead.
        """
        if self._loop is not None and self._started:
            # Schedule async shutdown
            try:
                if self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(self.shutdown(), self._loop)
                else:
                    # Loop not running, force cleanup
                    self._shutting_down = True
                    if self._worker_task is not None:
                        self._worker_task.cancel()
            except Exception:
                pass

        super().close()


def get_handler_instance() -> ReliableTelegramLogHandler | None:
    """Get the first registered handler instance, if any."""
    for handler in _handler_instances:
        return handler
    return None


async def shutdown_handler(timeout: float = 10.0) -> None:
    """
    Shutdown all registered handler instances.

    Call this during application shutdown to ensure all logs are flushed.

    Args:
        timeout: Max seconds to wait for each handler
    """
    tasks = []
    for handler in list(_handler_instances):
        tasks.append(handler.shutdown(timeout=timeout))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def shutdown_all_handlers(timeout: float = 10.0) -> None:
    """Alias for shutdown_handler for compatibility."""
    await shutdown_handler(timeout)
