"""
Logging configuration with production-ready Telegram integration.

Usage:
    from src.logging_config import setup_logging, start_telegram_logging, shutdown_logging

    # During startup (after event loop is running):
    setup_logging("my_service")
    start_telegram_logging()

    # During shutdown:
    await shutdown_logging()
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from typing import TYPE_CHECKING

from pythonjsonlogger import json

from src.config import BASE_DIR, config
from src.logging.reliable_telegram_handler import (
    ReliableTelegramLogHandler,
    shutdown_handler,
)

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop

# Module-level reference to the telegram handler for lifecycle management
_telegram_handler: ReliableTelegramLogHandler | None = None


def setup_logging(service_name: str) -> None:
    """
    Configure the logging system.

    Sets up console, file (optional), and Telegram (optional) handlers.
    For Telegram handler to work, you must call start_telegram_logging()
    after the event loop is running.

    Args:
        service_name: Name of the service for log identification
    """
    global _telegram_handler

    logger = logging.getLogger()
    logger.setLevel(config.logging.LEVEL)
    if logger.handlers:
        logger.handlers.clear()

    # JSON formatter for structured logging
    formatter = json.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(service)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S %Z",
        static_fields={"service": service_name},
    )

    # Console handler (always enabled)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (optional)
    if config.logging.FILE_ENABLED:
        log_dir = BASE_DIR / "logs" / service_name
        try:
            log_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
        except (PermissionError, OSError) as e:
            logger.error(f"Cannot create log directory: {log_dir}, error: {e}")
            raise RuntimeError(f"Cannot create log directory: {log_dir}") from e

        log_file = log_dir / f"{service_name}.log"
        file_handler = TimedRotatingFileHandler(
            filename=log_file,
            when="midnight",
            backupCount=config.logging.BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Telegram handler (optional, requires explicit start)
    if config.logging.TELEGRAM_ENABLED:
        admin_ids = config.telegram.ADMIN_ACCESS_IDs
        if admin_ids:
            _telegram_handler = ReliableTelegramLogHandler(
                bot_token=config.telegram.TOKEN.get_secret_value(),
                admin_chat_ids=list(admin_ids),
                level=logging.ERROR,
                rate_limit_seconds=60.0,
                dedup_window_seconds=300.0,
                queue_size=1000,
                flush_timeout_seconds=10.0,
                suppression_report_interval=300.0,
            )
            _telegram_handler.setLevel(logging.ERROR)
            _telegram_handler.setFormatter(formatter)
            logger.addHandler(_telegram_handler)


def start_telegram_logging(loop: AbstractEventLoop | None = None) -> None:
    """
    Start the Telegram logging background worker.

    Must be called after the event loop is running.

    Args:
        loop: Event loop to use. If None, uses the current running loop.
    """
    if _telegram_handler is not None:
        _telegram_handler.start(loop)


async def shutdown_logging(timeout: float = 10.0) -> None:
    """
    Gracefully shutdown logging handlers.

    Drains the Telegram log queue before stopping.

    Args:
        timeout: Max seconds to wait for queue drain
    """
    await shutdown_handler(timeout)


def get_telegram_handler() -> ReliableTelegramLogHandler | None:
    """Get the current Telegram handler instance, if configured."""
    return _telegram_handler
