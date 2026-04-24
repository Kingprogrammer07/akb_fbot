"""Notification model for user alert history."""
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base


class Notification(Base):
    """
    Persisted notification for WebApp display.
    
    Created when the bot sends alerts to users (e.g., payment reminders,
    leftover cargo notifications). Tracks read status for unread badges.
    
    Types: 'payment', 'info', 'warning', 'cargo', etc.
    """
    
    __tablename__ = "notifications"

    client_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK to clients.id"
    )
    title: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="Notification title"
    )
    body: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Notification body text"
    )
    type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="info",
        comment="Notification type: 'payment', 'info', 'warning', 'cargo'"
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Whether the user has read this notification"
    )

    __table_args__ = (
        Index('ix_notifications_client_read', 'client_id', 'is_read'),
        Index('ix_notifications_client_created', 'client_id', 'created_at'),
    )

    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, client={self.client_id}, type={self.type}, read={self.is_read})>"
