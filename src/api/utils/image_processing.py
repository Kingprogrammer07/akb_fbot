"""Image processing utilities for passport uploads."""
import io
import logging
from pathlib import PurePosixPath

from fastapi import UploadFile

logger = logging.getLogger(__name__)


async def process_upload_file(file: UploadFile) -> tuple[bytes, str]:
    """Convert an uploaded image to JPEG for maximum Telegram compatibility.

    Attempts to open the file with Pillow, convert to RGB, and re-encode as
    JPEG.  If *any* error occurs (unsupported format, corrupt data, Pillow not
    installed, etc.) the original bytes and filename are returned unchanged.

    Args:
        file: The incoming ``UploadFile`` from FastAPI.

    Returns:
        A ``(processed_bytes, filename)`` tuple.  On success the bytes are a
        JPEG image and the filename ends with ``.jpg``.  On failure the
        original bytes and filename are returned as-is.
    """
    await file.seek(0)
    original_bytes = await file.read()
    original_filename = file.filename or "upload"

    try:
        from PIL import Image

        image = Image.open(io.BytesIO(original_bytes))
        rgb_image = image.convert("RGB")

        buf = io.BytesIO()
        rgb_image.save(buf, format="JPEG")
        jpeg_bytes = buf.getvalue()

        # Build a .jpg filename from the original stem
        stem = PurePosixPath(original_filename).stem
        jpeg_filename = f"{stem}.jpg"

        logger.debug(
            "Image converted to JPEG: original=%s, new=%s, "
            "original_size=%d, jpeg_size=%d",
            original_filename, jpeg_filename,
            len(original_bytes), len(jpeg_bytes),
        )
        return jpeg_bytes, jpeg_filename

    except Exception as exc:
        logger.warning(
            "Image conversion failed for %s, using original file: %s",
            original_filename, exc,
        )
        # Reset file pointer so callers can re-read if needed
        await file.seek(0)
        return original_bytes, original_filename
