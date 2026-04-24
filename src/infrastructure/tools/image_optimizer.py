import asyncio
import io
import logging
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    logging.warning("pillow_heif kutubxonasi o'rnatilmagan! HEIC/HEIF rasmlar xato berishi mumkin.")

logger = logging.getLogger(__name__)


def _optimize_sync(
    file_bytes: bytes,
    quality: int,
    max_size: tuple[int, int],
) -> bytes:
    """Synchronous Pillow processing (runs inside a worker thread)."""
    img = Image.open(io.BytesIO(file_bytes))

    # iPhone EXIF orientation ni to'g'rilash
    img = ImageOps.exif_transpose(img)

    # Alpha channel mavjudligini tekshirib, to'g'ri rejimga o'tkazish
    if img.mode in ("RGBA", "LA", "PA"):
        img = img.convert("RGBA")  # Transparency saqlanadi
    elif img.mode == "P":
        # Palette mode — alpha bo'lishi mumkin, tekshirib ko'r
        if "transparency" in img.info:
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Down-scale while keeping aspect ratio (no up-scaling)
    img.thumbnail(max_size, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()


async def optimize_image_to_webp(
    file_bytes: bytes,
    quality: int = 80,
    max_size: tuple[int, int] = (1920, 1920),
) -> bytes:
    """
    Convert an image to optimized WEBP format asynchronously.

    Supported formats: JPEG, JPG, PNG, WEBP, HEIC, HEIF

    Args:
        file_bytes: Raw image bytes
        quality:    WEBP compression quality (1–100), default 80
        max_size:   Maximum (width, height), aspect ratio preserved, default (1920, 1920)

    Returns:
        Optimized WEBP image as bytes

    Raises:
        ValueError: If the file is invalid, unsupported, or processing fails
    """
    if not (1 <= quality <= 100):
        raise ValueError("Quality must be between 1 and 100")

    if not file_bytes:
        raise ValueError("Empty file bytes provided")

    try:
        return await asyncio.to_thread(_optimize_sync, file_bytes, quality, max_size)
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        logger.warning("Pillow could not identify or decode the uploaded image: %s", exc)
        raise ValueError("Invalid or unsupported image file")
    except ValueError:
        raise
    except Exception as exc:
        logger.error("Image optimisation failed: %s", exc, exc_info=True)
        raise ValueError("Image processing failed")