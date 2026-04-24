"""
TelegramFileService - Production-grade file_id management with auto-regeneration.

This service handles:
1. file_id validation
2. URL resolution for valid file_ids
3. Auto-regeneration when file_ids expire or become invalid
4. Database atomic updates
5. Rate limiting and Redis-backed caching
6. Concurrent request protection via per-cargo locks

IMPORTANT: Telegram file URLs expire after ~1 hour.
This service transparently handles regeneration when needed.
"""
import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from contextlib import asynccontextmanager
import json
import aiohttp
from aiogram import Bot
from aiogram.types import BufferedInputFile
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from aiohttp import ClientOSError
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter, TelegramNetworkError

from src.config import config

logger = logging.getLogger(__name__)


@dataclass
class FileIdResult:
    """Result of file_id resolution."""
    file_id: str
    telegram_url: Optional[str] = None
    is_regenerated: bool = False
    error: Optional[str] = None


@dataclass
class FileIdValidation:
    """Result of file_id validation."""
    is_valid: bool
    file_path: Optional[str] = None
    error: Optional[str] = None


class TelegramFileServiceError(Exception):
    """Base exception for TelegramFileService."""
    def __init__(self, message: str, error_code: str, details: Optional[Dict] = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(message)


class TelegramFileService:
    """
    Production-grade service for Telegram file_id management.

    Features:
    - Validates file_ids against Telegram API
    - Resolves file_ids to temporary URLs
    - Auto-regenerates expired/invalid file_ids
    - Thread-safe with per-resource locks
    - Rate limiting protection
    - Memory-efficient streaming
    - Retry logic with exponential backoff

    Usage:
        service = TelegramFileService(bot, redis)
        result = await service.resolve_file_id(file_id, cargo_id, session)
        # result.telegram_url contains the resolved URL (if valid)
        # result.is_regenerated indicates if file_id was refreshed
    """

    # Class-level lock dictionary for per-cargo concurrency control
    _locks: Dict[str, asyncio.Lock] = {}
    _locks_lock = asyncio.Lock()

    # Redis cache key prefix and TTL (Telegram URLs expire after ~1 hour)
    _cache_prefix = "tg_file:"
    _cache_ttl_seconds = 3600  # 1 hour

    # Rate limiting
    _last_request_time: Dict[str, datetime] = {}
    _min_request_interval = timedelta(milliseconds=50)  # 20 req/sec max

    def __init__(self, bot: Bot, redis: Redis):
        """
        Initialize TelegramFileService.

        Args:
            bot: aiogram Bot instance for Telegram API calls
            redis: Redis connection for URL caching
        """
        self.bot = bot
        self.redis = redis
        self._admin_chat_id = next(iter(config.telegram.ADMIN_ACCESS_IDs))

    @asynccontextmanager
    async def _get_lock(self, resource_id: str):
        """
        Get or create a lock for a specific resource (cargo_id/client_id).

        Prevents concurrent regeneration of the same file.
        """
        async with self._locks_lock:
            if resource_id not in self._locks:
                self._locks[resource_id] = asyncio.Lock()
            lock = self._locks[resource_id]

        try:
            await lock.acquire()
            yield
        finally:
            lock.release()

    async def upload_file_to_telegram(
        self,
        file_content: bytes,
        filename: str,
        target_chat_id: int
    ) -> str:
        """
        Upload a file to Telegram with retries and return file_id.
        Handles ConnectionReset and FloodWait.

        Args:
            file_content: Raw bytes of the file
            filename: Name of the file
            target_chat_id: Chat ID to send to (admin ID)

        Returns:
            file_id of the uploaded photo
        """
        await self._rate_limit()

        input_file = BufferedInputFile(file=file_content, filename=filename)

        # Use existing retry wrapper
        message = await self._execute_with_retry(
            self.bot.send_photo,
            chat_id=target_chat_id,
            photo=input_file
        )

        # Get highest resolution
        file_id = message.photo[-1].file_id

        # Cleanup message
        try:
            await self._execute_with_retry(
                self.bot.delete_message,
                chat_id=target_chat_id,
                message_id=message.message_id
            )
        except Exception as e:
            logger.warning(f"Failed to delete temp upload message: {e}")

        return file_id

    async def _execute_with_retry(self, func, *args, **kwargs):
        """
        Execute a Telegram API call with retry logic for FloodWait (429) errors.

        Retries up to 3 times, waiting the required duration on TelegramRetryAfter.
        """
        retries = 3
        for attempt in range(retries):
            try:
                return await func(*args, **kwargs)
            except TelegramRetryAfter as e:
                wait_time = e.retry_after + 1
                logger.warning(
                    f"FloodWait detected (attempt {attempt + 1}/{retries}). "
                    f"Sleeping {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
            except (ClientOSError, ConnectionResetError, TelegramNetworkError) as e:
                wait_time = (attempt + 1) * 2  # Exponential backoff: 2s, 4s, 6s
                logger.warning(
                    f"Network error during Telegram API call (attempt {attempt + 1}/{retries}): {e}. "
                    f"Retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
            except Exception as e:
                if attempt == retries - 1:
                    raise
                logger.warning(
                    f"Telegram API error (attempt {attempt + 1}/{retries}): {e}. "
                    f"Retrying in 1s..."
                )
                await asyncio.sleep(1)
        # Should not reach here, but just in case
        raise TelegramFileServiceError(
            "Max retries exceeded", "max_retries_exceeded"
        )

    async def _rate_limit(self):
        """Apply rate limiting to Telegram API calls."""
        now = datetime.now()
        key = "global"

        if key in self._last_request_time:
            elapsed = now - self._last_request_time[key]
            if elapsed < self._min_request_interval:
                await asyncio.sleep((self._min_request_interval - elapsed).total_seconds())

        self._last_request_time[key] = datetime.now()

    async def _get_cached_url(self, file_id: str) -> Optional[str]:
        """Get URL from Redis cache (returns None if expired/missing)."""
        try:
            return await self.redis.get(f"{self._cache_prefix}{file_id}")
        except Exception as e:
            logger.warning(f"Redis cache get failed for {file_id[:16]}...: {e}")
            return None

    async def _cache_url(self, file_id: str, url: str):
        """Cache a resolved URL in Redis with TTL."""
        try:
            await self.redis.set(
                f"{self._cache_prefix}{file_id}",
                url,
                ex=self._cache_ttl_seconds
            )
        except Exception as e:
            logger.warning(f"Redis cache set failed for {file_id[:16]}...: {e}")

    async def validate_file_id(self, file_id: str) -> FileIdValidation:
        """
        Validate a Telegram file_id.

        Attempts to get file info from Telegram API.
        Returns validation result with file_path if valid.

        Args:
            file_id: Telegram file_id to validate

        Returns:
            FileIdValidation with is_valid flag and file_path
        """
        await self._rate_limit()

        try:
            file = await self._execute_with_retry(self.bot.get_file, file_id)
            return FileIdValidation(
                is_valid=True,
                file_path=file.file_path
            )
        except TelegramBadRequest as e:
            error_msg = str(e)
            # Common invalid file_id errors
            if "file is too big" in error_msg.lower():
                return FileIdValidation(is_valid=False, error="file_too_big")
            elif "wrong file_id" in error_msg.lower() or "invalid file_id" in error_msg.lower():
                return FileIdValidation(is_valid=False, error="invalid_file_id")
            else:
                return FileIdValidation(is_valid=False, error=error_msg)
        except Exception as e:
            logger.error(f"Error validating file_id {file_id[:16]}...: {e}")
            return FileIdValidation(is_valid=False, error=str(e))

    async def get_file_url(self, file_id: str) -> Optional[str]:
        """
        Get temporary Telegram URL for a file_id.

        Uses caching to reduce API calls.
        URL is valid for ~1 hour from Telegram.

        Args:
            file_id: Telegram file_id

        Returns:
            Temporary download URL or None if invalid
        """
        # Check cache first
        cached = await self._get_cached_url(file_id)
        if cached:
            return cached

        # Validate and get file path
        validation = await self.validate_file_id(file_id)
        if not validation.is_valid:
            return None

        # Build URL
        url = (
            f"https://api.telegram.org/file/bot"
            f"{config.telegram.TOKEN.get_secret_value()}/"
            f"{validation.file_path}"
        )

        # Cache and return
        await self._cache_url(file_id, url)
        return url

    async def download_file(
        self,
        file_id: str,
        timeout: int = 30
    ) -> Optional[bytes]:
        """
        Download file content from Telegram.

        Uses aiohttp for async streaming download.

        Args:
            file_id: Telegram file_id
            timeout: Download timeout in seconds

        Returns:
            File content as bytes or None if failed
        """
        url = await self.get_file_url(file_id)
        if not url:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            f"Failed to download file {file_id[:16]}...: "
                            f"status={response.status}"
                        )
                        return None

                    return await response.read()
        except asyncio.TimeoutError:
            logger.error(f"Timeout downloading file {file_id[:16]}...")
            return None
        except Exception as e:
            logger.error(f"Error downloading file {file_id[:16]}...: {e}")
            return None

    async def regenerate_file_id(
        self,
        old_file_id: str,
        filename: str = "regenerated_image.jpg"
    ) -> Optional[str]:
        """
        Regenerate a file_id by re-uploading the file.

        Downloads the file using old file_id, re-uploads to Telegram,
        and returns the new file_id.

        Args:
            old_file_id: Original file_id (may be expired)
            filename: Filename for re-upload

        Returns:
            New file_id or None if regeneration failed
        """
        logger.info(f"Regenerating file_id: {old_file_id[:16]}...")

        # Download original file
        content = await self.download_file(old_file_id)
        if not content:
            logger.error(f"Failed to download for regeneration: {old_file_id[:16]}...")
            return None

        await self._rate_limit()

        try:
            # Re-upload to Telegram
            input_file = BufferedInputFile(file=content, filename=filename)
            message = await self._execute_with_retry(
                self.bot.send_photo,
                chat_id=self._admin_chat_id,
                photo=input_file
            )

            new_file_id = message.photo[-1].file_id
            # Delete the temporary message
            try:
                await self._execute_with_retry(
                    self.bot.delete_message,
                    chat_id=self._admin_chat_id,
                    message_id=message.message_id
                )
            except Exception as e:
                logger.warning(f"Failed to delete temp message: {e}")

            logger.info(
                f"Regenerated file_id: {old_file_id[:16]}... -> {new_file_id[:16]}..."
            )
            return new_file_id

        except Exception as e:
            logger.error(f"Failed to regenerate file_id: {e}")
            return None

    async def resolve_cargo_file_id(
        self,
        cargo_id: int,
        file_id: str,
        photo_index: int,
        session: AsyncSession,
        auto_regenerate: bool = True
    ) -> FileIdResult:
        """
        Resolve a cargo photo file_id with optional auto-regeneration.

        This is the main entry point for cargo image resolution.
        Handles validation, regeneration, and database updates atomically.

        Args:
            cargo_id: FlightCargo ID
            file_id: Current file_id from database
            photo_index: Index of photo in the JSON array
            session: Database session for atomic updates
            auto_regenerate: Whether to regenerate invalid file_ids

        Returns:
            FileIdResult with file_id and optional telegram_url
        """
        lock_key = f"cargo_{cargo_id}"

        async with self._get_lock(lock_key):
            # Try to validate current file_id
            validation = await self.validate_file_id(file_id)

            if validation.is_valid:
                # File is valid, get URL
                url = await self.get_file_url(file_id)
                return FileIdResult(
                    file_id=file_id,
                    telegram_url=url
                )

            # File is invalid
            if not auto_regenerate:
                return FileIdResult(
                    file_id=file_id,
                    error=validation.error
                )

            # Try to regenerate
            logger.info(
                f"File_id invalid for cargo {cargo_id}, attempting regeneration..."
            )

            new_file_id = await self.regenerate_file_id(
                old_file_id=file_id,
                filename=f"cargo_{cargo_id}_photo_{photo_index}.jpg"
            )

            if not new_file_id:
                return FileIdResult(
                    file_id=file_id,
                    error="regeneration_failed"
                )

            # Update database atomically
            try:
                from src.infrastructure.services.flight_cargo import FlightCargoService
                cargo_service = FlightCargoService()
                cargo = await cargo_service.get_cargo_by_id(session, cargo_id)

                if cargo:
                    # Parse current file_ids
                    try:
                        file_ids = json.loads(cargo.photo_file_ids)
                    except (json.JSONDecodeError, TypeError):
                        file_ids = [cargo.photo_file_ids] if cargo.photo_file_ids else []

                    # Update the specific file_id
                    if 0 <= photo_index < len(file_ids):
                        file_ids[photo_index] = new_file_id
                        cargo.photo_file_ids = json.dumps(file_ids)
                        await session.commit()
                        logger.info(
                            f"Updated cargo {cargo_id} with new file_id at index {photo_index}"
                        )

            except Exception as e:
                logger.error(f"Failed to update database with new file_id: {e}")
                await session.rollback()
                # Still return the new file_id even if DB update failed

            # Get URL for new file_id
            url = await self.get_file_url(new_file_id)

            return FileIdResult(
                file_id=new_file_id,
                telegram_url=url,
                is_regenerated=True
            )

    async def resolve_passport_file_id(
        self,
        client_id: int,
        file_id: str,
        image_index: int,
        session: AsyncSession,
        auto_regenerate: bool = True
    ) -> FileIdResult:
        """
        Resolve a passport image file_id with optional auto-regeneration.

        Similar to resolve_cargo_file_id but for passport images.

        Args:
            client_id: Client ID
            file_id: Current file_id from database
            image_index: Index of image in the JSON array
            session: Database session for atomic updates
            auto_regenerate: Whether to regenerate invalid file_ids

        Returns:
            FileIdResult with file_id and optional telegram_url
        """
        lock_key = f"passport_{client_id}"

        async with self._get_lock(lock_key):
            # Try to validate current file_id
            validation = await self.validate_file_id(file_id)

            if validation.is_valid:
                # File is valid, get URL
                url = await self.get_file_url(file_id)
                return FileIdResult(
                    file_id=file_id,
                    telegram_url=url
                )

            # File is invalid
            if not auto_regenerate:
                return FileIdResult(
                    file_id=file_id,
                    error=validation.error
                )

            # Try to regenerate
            logger.info(
                f"File_id invalid for client {client_id} passport, "
                f"attempting regeneration..."
            )

            new_file_id = await self.regenerate_file_id(
                old_file_id=file_id,
                filename=f"passport_{client_id}_image_{image_index}.jpg"
            )

            if not new_file_id:
                return FileIdResult(
                    file_id=file_id,
                    error="regeneration_failed"
                )

            # Update database atomically
            try:
                from src.infrastructure.database.dao.client import ClientDAO
                client = await ClientDAO.get_by_id(session, client_id)

                if client and client.passport_images:
                    # Parse current file_ids
                    try:
                        file_ids = json.loads(client.passport_images)
                    except (json.JSONDecodeError, TypeError):
                        file_ids = [client.passport_images]

                    # Update the specific file_id
                    if 0 <= image_index < len(file_ids):
                        file_ids[image_index] = new_file_id
                        client.passport_images = json.dumps(file_ids)
                        await session.commit()
                        logger.info(
                            f"Updated client {client_id} passport with new file_id "
                            f"at index {image_index}"
                        )

            except Exception as e:
                logger.error(f"Failed to update database with new file_id: {e}")
                await session.rollback()

            # Get URL for new file_id
            url = await self.get_file_url(new_file_id)

            return FileIdResult(
                file_id=new_file_id,
                telegram_url=url,
                is_regenerated=True
            )

    async def get_cargo_photo_metadata(
        self,
        cargo_id: int,
        session: AsyncSession
    ) -> Dict[str, Any]:
        """
        Get metadata for all photos of a cargo item.

        Returns file_ids with optional resolved URLs.
        Does NOT download binary data.

        Args:
            cargo_id: FlightCargo ID
            session: Database session

        Returns:
            Dict with photo metadata
        """
        from src.infrastructure.services.flight_cargo import FlightCargoService
        cargo_service = FlightCargoService()
        cargo = await cargo_service.get_cargo_by_id(session, cargo_id)

        if not cargo:
            return {"error": "cargo_not_found", "cargo_id": cargo_id}

        # Parse file_ids
        try:
            file_ids = json.loads(cargo.photo_file_ids)
        except (json.JSONDecodeError, TypeError):
            file_ids = [cargo.photo_file_ids] if cargo.photo_file_ids else []

        photos = []
        for idx, file_id in enumerate(file_ids):
            result = await self.resolve_cargo_file_id(
                cargo_id=cargo_id,
                file_id=file_id,
                photo_index=idx,
                session=session,
                auto_regenerate=True
            )
            photos.append({
                "index": idx,
                "file_id": result.file_id,
                "telegram_url": result.telegram_url,
                "is_regenerated": result.is_regenerated,
                "error": result.error
            })

        return {
            "cargo_id": cargo_id,
            "flight_name": cargo.flight_name,
            "client_id": cargo.client_id,
            "photo_count": len(photos),
            "photos": photos
        }

    async def clear_cache(self):
        """Clear all cached Telegram file URLs from Redis."""
        try:
            cursor = "0"
            deleted = 0
            while cursor != 0:
                cursor, keys = await self.redis.scan(
                    cursor=cursor, match=f"{self._cache_prefix}*", count=100
                )
                if keys:
                    await self.redis.delete(*keys)
                    deleted += len(keys)
            logger.info(f"Cleared {deleted} cached Telegram file URLs from Redis")
        except Exception as e:
            logger.error(f"Failed to clear Redis cache: {e}")

    async def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics from Redis."""
        try:
            cursor = "0"
            total = 0
            while cursor != 0:
                cursor, keys = await self.redis.scan(
                    cursor=cursor, match=f"{self._cache_prefix}*", count=100
                )
                total += len(keys)
            return {"total_cached": total}
        except Exception as e:
            logger.error(f"Failed to get Redis cache stats: {e}")
            return {"total_cached": 0}
