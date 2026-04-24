"""
Passport image resolver — converts stored passport image references to usable URLs.

Handles both legacy Telegram file_ids and new S3 keys transparently.
Detection heuristic: S3 keys contain '/' (e.g. "passport-front-images//.../file.webp"),
while Telegram file_ids are opaque alphanumeric strings without slashes.
"""

import logging
from typing import Optional

from src.infrastructure.tools.s3_manager import s3_manager

logger = logging.getLogger(__name__)


def _is_s3_key(item: str) -> bool:
    """Return True if the item looks like an S3 object key rather than a Telegram file_id."""
    return "/" in item


async def resolve_passport_items(
    items: list[str],
    expires_in: int = 3600,
) -> list[str]:
    """Resolve a mixed list of passport image references for use with Telegram/Aiogram.

    - **S3 keys** (contain ``/``) are converted to temporary presigned URLs.
      Aiogram natively accepts HTTP URLs in ``send_photo``, ``InputMediaPhoto``, etc.
    - **Telegram file_ids** (no ``/``) are returned as-is — backward compatible
      with data stored before the S3 migration.

    If presigned-URL generation fails for an S3 key the item is silently
    skipped and an error is logged.

    Args:
        items: List of S3 keys or Telegram file_ids.
        expires_in: Presigned URL lifetime in seconds (default 1 hour).

    Returns:
        List of resolved references (URLs or raw file_ids) ready for Aiogram.
    """
    resolved: list[str] = []

    for item in items:
        if _is_s3_key(item):
            try:
                url = await s3_manager.generate_presigned_url(item, expires_in=expires_in)
                resolved.append(url)
            except Exception as exc:
                logger.error("Failed to generate presigned URL for S3 key %s: %s", item, exc)
        else:
            # Legacy Telegram file_id — pass through unchanged
            resolved.append(item)

    return resolved
