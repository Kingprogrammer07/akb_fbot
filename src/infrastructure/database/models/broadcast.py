"""Broadcast message model."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Boolean, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
import enum

from src.infrastructure.database.models.base import Base


class BroadcastStatus(str, enum.Enum):
    """Broadcast message status."""
    DRAFT = "draft"  # Creating/editing
    SCHEDULED = "scheduled"  # Ready to send
    SENDING = "sending"  # Currently sending
    COMPLETED = "completed"  # Finished sending
    CANCELLED = "cancelled"  # Cancelled by admin
    FAILED = "failed"  # Failed to send


class BroadcastMediaType(str, enum.Enum):
    """Broadcast media types."""
    TEXT = "text"  # Text only
    PHOTO = "photo"  # Single photo
    PHOTO_ALBUM = "photo_album"  # Multiple photos
    VIDEO = "video"  # Single video
    VIDEO_ALBUM = "video_album"  # Multiple videos
    DOCUMENT = "document"  # Single document
    DOCUMENT_ALBUM = "document_album"  # Multiple documents
    AUDIO = "audio"  # Single audio
    AUDIO_ALBUM = "audio_album"  # Multiple audio files
    VOICE = "voice"  # Voice message
    FORWARD = "forward"  # Forwarded message


class BroadcastMessage(Base):
    """
    Broadcast message model for admin announcements.

    Stores all broadcast campaigns including:
    - Media content (photos, videos, documents, audio, voice)
    - Caption text
    - Inline buttons
    - Sending statistics
    """
    __tablename__ = "broadcast_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Admin who created this broadcast
    created_by_telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="Telegram ID of admin who created this broadcast"
    )

    # Content
    media_type: Mapped[str] = mapped_column(
        SQLEnum(BroadcastMediaType),
        nullable=False,
        default=BroadcastMediaType.TEXT,
        comment="Type of media content"
    )

    caption: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Message caption/text"
    )

    # Media file IDs (JSON array for albums, single string for single media)
    media_file_ids: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="JSON array of Telegram file_id or single file_id"
    )

    # Forward info (if media_type is FORWARD)
    forward_from_chat_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="Chat ID to forward from"
    )

    forward_message_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Message ID to forward"
    )

    # Inline buttons (JSON array)
    inline_buttons: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="JSON array of inline keyboard buttons"
    )

    # Status
    status: Mapped[str] = mapped_column(
        SQLEnum(BroadcastStatus),
        nullable=False,
        default=BroadcastStatus.DRAFT,
        comment="Current status of broadcast"
    )

    # Statistics
    total_users: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total number of users to send to"
    )

    sent_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of successfully sent messages"
    )

    failed_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of failed sends"
    )

    blocked_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of users who blocked the bot"
    )

    # Timing
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="When broadcast was created"
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="When sending started"
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="When sending completed"
    )

    # Pin message option
    pin_message: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether to pin the message for users"
    )

    def __repr__(self):
        return f"<BroadcastMessage(id={self.id}, status={self.status}, sent={self.sent_count}/{self.total_users})>"
