"""Broadcast utility functions."""

import json
from datetime import datetime, timedelta
from typing import Optional

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from src.bot.handlers.admin.broadcast.constants import MESSAGE_DELAY, MEDIA_TYPE_NAMES
from src.bot.handlers.admin.broadcast.models import BroadcastButton, BroadcastContent


def calculate_broadcast_time(total_users: int, delay: float = MESSAGE_DELAY) -> dict:
    """
    Calculate estimated broadcast completion time.
    
    Args:
        total_users: Number of recipients
        delay: Delay between messages in seconds
        
    Returns:
        Dictionary with time breakdown and estimates
    """
    total_seconds = total_users * delay
    
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    
    # Format human-readable time
    parts = []
    if hours > 0:
        parts.append(f"{hours} soat")
    if minutes > 0:
        parts.append(f"{minutes} daqiqa")
    if seconds > 0 or not parts:
        parts.append(f"{seconds} soniya")
    
    return {
        "total_seconds": total_seconds,
        "hours": hours,
        "minutes": minutes,
        "seconds": seconds,
        "formatted": " ".join(parts),
        "estimated_completion": datetime.now() + timedelta(seconds=total_seconds)
    }


def parse_media_from_message(message: Message) -> BroadcastContent:
    """
    Extract media content from Telegram message.

    Supports: photo, video, document, audio, voice, albums, forwards
    Preserves text formatting (bold, italic, links, etc.) via entities

    Args:
        message: Telegram message object

    Returns:
        BroadcastContent object
    """
    # Extract entities (formatting: bold, italic, links, etc.)
    entities = None
    if message.caption_entities:
        entities = [entity.model_dump() for entity in message.caption_entities]
    elif message.entities:
        entities = [entity.model_dump() for entity in message.entities]

    content = BroadcastContent(
        caption=message.caption or message.text or "",
        caption_entities=entities
    )

    # Check for forwarded message
    if message.forward_from or message.forward_from_chat:
        content.media_type = "forward"
        content.forward_from_chat_id = message.chat.id
        content.forward_message_id = message.message_id
        return content

    # Handle media groups (albums)
    if message.media_group_id:
        if message.photo:
            content.media_type = "photo_album"
            content.file_ids = [message.photo[-1].file_id]
        elif message.video:
            content.media_type = "video_album"
            content.file_ids = [message.video.file_id]
        elif message.document:
            content.media_type = "document_album"
            content.file_ids = [message.document.file_id]
        elif message.audio:
            content.media_type = "audio_album"
            content.file_ids = [message.audio.file_id]
        return content

    # Handle single media
    if message.photo:
        content.media_type = "photo"
        content.file_ids = [message.photo[-1].file_id]
    elif message.video:
        content.media_type = "video"
        content.file_ids = [message.video.file_id]
    elif message.document:
        content.media_type = "document"
        content.file_ids = [message.document.file_id]
    elif message.audio:
        content.media_type = "audio"
        content.file_ids = [message.audio.file_id]
    elif message.voice:
        content.media_type = "voice"
        content.file_ids = [message.voice.file_id]
    elif message.text:
        content.media_type = "text"

    return content


def build_inline_keyboard(buttons: list[BroadcastButton]) -> Optional[InlineKeyboardMarkup]:
    """
    Build inline keyboard from button objects.
    
    Args:
        buttons: List of BroadcastButton objects
        
    Returns:
        InlineKeyboardMarkup or None if no valid buttons
    """
    if not buttons:
        return None
    
    keyboard = []
    for button in buttons:
        if button.url:
            kb_button = InlineKeyboardButton(text=button.text, url=button.url)
        elif button.callback_data:
            kb_button = InlineKeyboardButton(text=button.text, callback_data=button.callback_data)
        else:
            continue
        
        keyboard.append([kb_button])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard) if keyboard else None


def serialize_buttons(buttons: list[BroadcastButton]) -> str:
    """
    Serialize buttons to JSON string for database storage.
    
    Args:
        buttons: List of BroadcastButton objects
        
    Returns:
        JSON string
    """
    return json.dumps([btn.to_dict() for btn in buttons], ensure_ascii=False)


def deserialize_buttons(buttons_json: str) -> list[BroadcastButton]:
    """
    Deserialize buttons from JSON string.
    
    Args:
        buttons_json: JSON string from database
        
    Returns:
        List of BroadcastButton objects
    """
    if not buttons_json:
        return []
    
    try:
        data = json.loads(buttons_json)
        return [BroadcastButton.from_dict(btn) for btn in data]
    except (json.JSONDecodeError, KeyError):
        return []


def format_time_remaining(seconds: float) -> str:
    """
    Format remaining time in human-readable format.
    
    Args:
        seconds: Time in seconds
        
    Returns:
        Formatted string (e.g., "2 daqiqa 30 soniya")
    """
    if seconds < 60:
        return f"{int(seconds)} soniya"
    
    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)
    
    if minutes < 60:
        parts = [f"{minutes} daqiqa"]
        if remaining_seconds > 0:
            parts.append(f"{remaining_seconds} soniya")
        return " ".join(parts)
    
    hours = int(minutes // 60)
    remaining_minutes = int(minutes % 60)
    
    parts = [f"{hours} soat"]
    if remaining_minutes > 0:
        parts.append(f"{remaining_minutes} daqiqa")
    
    return " ".join(parts)


def get_media_type_display(media_type: str) -> str:
    """
    Get display name for media type.

    Args:
        media_type: Internal media type identifier

    Returns:
        Localized display name
    """
    return MEDIA_TYPE_NAMES.get(media_type, media_type)


def validate_and_fix_url(url: str) -> str:
    """
    Validate and fix URL format.

    Converts:
    - @username -> https://t.me/username
    - username -> https://t.me/username
    - t.me/username -> https://t.me/username

    Args:
        url: Raw URL input from user

    Returns:
        Valid URL
    """
    url = url.strip()

    # Handle @username format
    if url.startswith("@"):
        return f"https://t.me/{url[1:]}"

    # Handle t.me/username without protocol
    if url.startswith("t.me/"):
        return f"https://{url}"

    # Handle plain username (no @, no protocol, no domain)
    if not url.startswith(("http://", "https://")) and "/" not in url:
        return f"https://t.me/{url}"

    # Already valid URL
    return url


def entities_to_telegram_format(entities_data: Optional[list[dict]]):
    """
    Convert entities dict to Telegram MessageEntity objects.

    Args:
        entities_data: List of entity dicts from content

    Returns:
        List of MessageEntity objects or None
    """
    from aiogram.types import MessageEntity

    if not entities_data:
        return None

    try:
        return [MessageEntity(**entity) for entity in entities_data]
    except Exception:
        return None