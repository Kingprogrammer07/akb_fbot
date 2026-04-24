"""Broadcast system constants."""

from typing import Final

# Performance settings
MESSAGE_DELAY: Final[float] = 0.05  # 50ms between messages
PROGRESS_UPDATE_INTERVAL: Final[int] = 20  # Update every 5%
MEDIA_GROUP_WAIT: Final[float] = 0.5  # Wait for album completion
MAX_ALBUM_SIZE: Final[int] = 10  # Telegram limit
STATS_SAVE_INTERVAL: Final[int] = 50  # Save stats to DB every N users

# UI texts
MEDIA_TYPE_NAMES: Final[dict[str, str]] = {
    "photo": "rasm",
    "video": "video",
    "document": "hujjat",
    "audio": "audio",
    "voice": "ovozli xabar",
    "text": "matn",
    "forward": "forward"
}

STATUS_EMOJIS: Final[dict[str, str]] = {
    "draft": "✏️",
    "scheduled": "⏰",
    "sending": "📤",
    "completed": "✅",
    "cancelled": "❌",
    "failed": "⚠️"
}

# Error messages
ERROR_MESSAGES: Final[dict[str, str]] = {
    "no_media": "❌ Media topilmadi. Qaytadan urinib ko'ring.",
    "send_failed": "❌ Yuborishda xatolik yuz berdi.",
    "invalid_format": "❌ Noto'g'ri format.",
    "cancelled": "❌ Bekor qilindi.",
    "stopped": "⏸ Yuborish to'xtatildi!"
}

# Success messages
SUCCESS_MESSAGES: Final[dict[str, str]] = {
    "media_received": "✅ Media qabul qilindi!",
    "caption_saved": "✅ Caption saqlandi!",
    "button_added": "✅ Tugma qo'shildi!",
    "completed": "✅ Yuborish yakunlandi!"
}