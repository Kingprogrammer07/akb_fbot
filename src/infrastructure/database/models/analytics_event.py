"""Analytics Event database model."""
from sqlalchemy import String, BigInteger, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base


class AnalyticsEvent(Base):
    """
    Analytics Event model.
    
    Tracks custom events for analytics purposes (registration, uploads, payments, etc.).
    Events are stored with flexible JSONB payload to allow schema evolution.
    
    No foreign key constraints - user_id is stored as integer to avoid blocking writes
    if referenced records don't exist.
    """
    
    __tablename__ = "analytics_events"
    
    # Event type identifier (e.g., 'client_registration', 'cargo_upload', 'payment_approval')
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Type of event (e.g., 'client_registration', 'cargo_upload')"
    )
    
    # User/Client identifier (nullable - events may not always have a user context)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
        comment="Telegram ID of user who triggered the event (no FK to avoid blocking writes)"
    )
    
    # Flexible event payload as JSONB
    event_data: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Flexible JSON payload with event-specific data"
    )
    
    # Indexes for efficient queries
    __table_args__ = (
        Index('ix_analytics_events_event_type_created_at', 'event_type', 'created_at'),
        Index('ix_analytics_events_user_id_created_at', 'user_id', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return f"<AnalyticsEvent(id={self.id}, event_type={self.event_type}, user_id={self.user_id}, created_at={self.created_at})>"

