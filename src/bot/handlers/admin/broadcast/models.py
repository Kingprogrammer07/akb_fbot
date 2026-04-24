"""Broadcast data models."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BroadcastButton:
    """Inline button configuration."""
    text: str
    url: Optional[str] = None
    callback_data: Optional[str] = None
    
    def to_dict(self) -> dict:
        result = {"text": self.text}
        if self.url:
            result["url"] = self.url
        elif self.callback_data:
            result["callback_data"] = self.callback_data
        return result
    
    @classmethod
    def from_dict(cls, data: dict) -> "BroadcastButton":
        return cls(
            text=data["text"],
            url=data.get("url"),
            callback_data=data.get("callback_data")
        )


@dataclass
class BroadcastContent:
    """Broadcast message content - FSM state compatible."""
    media_type: str = "text"
    file_ids: list[str] = field(default_factory=list)
    caption: str = ""
    caption_entities: Optional[list[dict]] = None  # Telegram message entities
    buttons: list[BroadcastButton] = field(default_factory=list)
    forward_from_chat_id: Optional[int] = None
    forward_message_id: Optional[int] = None
    audience_type: str = "all"  # all, selected
    target_client_codes: list[str] = field(default_factory=list)  # Client codes for targeted sending

    def has_media(self) -> bool:
        """Check if content has media files."""
        return bool(self.file_ids)

    def is_album(self) -> bool:
        """Check if content is media album."""
        return self.media_type.endswith("_album")

    def is_forward(self) -> bool:
        """Check if content is forwarded message."""
        return self.media_type == "forward"

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict for FSM storage."""
        return {
            "media_type": self.media_type,
            "file_ids": self.file_ids,
            "caption": self.caption,
            "caption_entities": self.caption_entities,
            "buttons": [btn.to_dict() for btn in self.buttons],
            "forward_from_chat_id": self.forward_from_chat_id,
            "forward_message_id": self.forward_message_id,
            "audience_type": self.audience_type,
            "target_client_codes": self.target_client_codes
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BroadcastContent":
        """Create from dict stored in FSM."""
        buttons_data = data.get("buttons", [])
        buttons = [BroadcastButton.from_dict(btn) for btn in buttons_data]

        return cls(
            media_type=data.get("media_type", "text"),
            file_ids=data.get("file_ids", []),
            caption=data.get("caption", ""),
            caption_entities=data.get("caption_entities"),
            buttons=buttons,
            forward_from_chat_id=data.get("forward_from_chat_id"),
            forward_message_id=data.get("forward_message_id"),
            audience_type=data.get("audience_type", "all"),
            target_client_codes=data.get("target_client_codes", [])
        )


@dataclass
class BroadcastStats:
    """Broadcast sending statistics."""
    total: int = 0
    sent: int = 0
    failed: int = 0
    blocked: int = 0
    processed: int = 0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage."""
        if self.processed == 0:
            return 0.0
        return (self.sent / self.processed) * 100
    
    @property
    def progress_percent(self) -> int:
        """Calculate progress percentage."""
        if self.total == 0:
            return 0
        return int((self.processed / self.total) * 100)
    
    def format_status(self) -> str:
        """Format statistics for display."""
        return (
            f"👥 Jami: {self.total}\n"
            f"📊 Progress: {self.processed}/{self.total} ({self.progress_percent}%)\n"
            f"✅ Muvaffaqiyatli: {self.sent}\n"
            f"❌ Xato: {self.failed}\n"
            f"🚫 Bloklangan: {self.blocked}"
        )