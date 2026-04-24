"""
Async S3 Manager — singleton wrapper around aioboto3 for non-blocking S3 operations.

All methods use an async context-manager so the underlying aiohttp session is
opened for each operation and closed immediately afterwards, keeping the
FastAPI event-loop free of dangling connections.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

import aioboto3
from botocore.exceptions import ClientError

from src.config import config

logger = logging.getLogger(__name__)


class AsyncS3Manager:
    """Async AWS S3 Manager (singleton)."""

    def __init__(self) -> None:
        self._session = aioboto3.Session(
            aws_access_key_id=config.aws.ACCESS_KEY_ID,
            aws_secret_access_key=config.aws.SECRET_ACCESS_KEY.get_secret_value(),
            region_name=config.aws.REGION,
        )
        self._bucket = config.aws.BUCKET_NAME
        self._region = config.aws.REGION

    # ------------------------------------------------------------------ #
    #  Upload
    # ------------------------------------------------------------------ #
    async def upload_file(
        self,
        file_content: bytes,
        file_name: str,
        telegram_id: int,
        client_code: Optional[str],
        base_folder: str,
        sub_folder: str,
        content_type: str = "image/jpeg",
    ) -> str:
        """
        Upload a file to S3 and return the generated object key.

        Key format:
            {base_folder}/{sub_folder}/{telegram_id}_{client_code}_{timestamp}_{uuid8}.{ext}

        Args:
            file_content: Raw bytes of the file.
            file_name: Original filename (used to extract extension).
            telegram_id: User's Telegram ID.
            client_code: Client code; falls back to ``"NEW"`` when *None*.
            base_folder: Top-level S3 folder (e.g. ``"extra-passports"``).
            sub_folder: Sub-folder inside base (e.g. ``"passport_front"``).
            content_type: MIME type for the object.

        Returns:
            The S3 object key that was written.

        Raises:
            ClientError: On AWS SDK errors.
        """
        safe_code = client_code or "NEW"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        ext = file_name.rsplit(".", 1)[-1] if "." in file_name else "jpg"

        s3_key = (
            f"{base_folder}/{sub_folder}/"
            f"{telegram_id}_{safe_code}_{timestamp}_{unique_id}.{ext}"
        )

        async with self._session.client("s3") as s3:
            await s3.put_object(
                Bucket=self._bucket,
                Key=s3_key,
                Body=file_content,
                ContentType=content_type,
            )

        logger.info("✅ S3 upload OK: %s", s3_key)
        return s3_key

    # ------------------------------------------------------------------ #
    #  Public URL helper (no network call — pure string construction)
    # ------------------------------------------------------------------ #
    def get_public_url(self, s3_key: str) -> str:
        """Return the public HTTPS URL for an S3 object.

        Requires the object (or its prefix) to have public-read access on the
        bucket.  For carousel media this is the standard configuration since the
        items are shown to all app users without authentication.
        """
        return f"https://{self._bucket}.s3.{self._region}.amazonaws.com/{s3_key}"

    # ------------------------------------------------------------------ #
    #  Presigned URL
    # ------------------------------------------------------------------ #
    async def generate_presigned_url(
        self,
        s3_key: str,
        expires_in: int = 3600,
    ) -> str:
        """
        Generate a temporary presigned URL for a private S3 object.

        Args:
            s3_key: The S3 object key.
            expires_in: Link lifetime in seconds (default 1 hour).

        Returns:
            Presigned URL string.
        """
        async with self._session.client("s3") as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": s3_key},
                ExpiresIn=expires_in,
            )
        return url

    # ------------------------------------------------------------------ #
    #  Delete
    # ------------------------------------------------------------------ #
    async def delete_file(self, s3_key: str) -> bool:
        """
        Delete an object from S3.

        Args:
            s3_key: The S3 object key to remove.

        Returns:
            ``True`` on success, ``False`` on error.
        """
        try:
            async with self._session.client("s3") as s3:
                await s3.delete_object(Bucket=self._bucket, Key=s3_key)
            logger.info("✅ S3 delete OK: %s", s3_key)
            return True
        except ClientError as exc:
            logger.error("❌ S3 delete error for %s: %s", s3_key, exc)
            return False


# ------------------------------------------------------------------ #
#  Module-level singleton
# ------------------------------------------------------------------ #
s3_manager = AsyncS3Manager()
