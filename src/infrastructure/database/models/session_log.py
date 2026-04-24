"""Session log model for tracking login events."""
from datetime import datetime
from sqlalchemy import String, BigInteger, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base


class SessionLog(Base):
    """
    Model for tracking user session events (login, relink, logout).
    
    Maintains a "Last 20 records" retention policy per user.
    """
    __tablename__ = "session_logs"

    # Foreign key to clients table
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Telegram ID at the time of the event
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    
    # Event type: 'LOGIN', 'RELINK', 'LOGOUT'
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    
    # Optional metadata
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    device_info: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    # User details for display (denormalized for better UX)
    client_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Indexes for efficient querying
    __table_args__ = (
        Index('ix_session_logs_client_created', 'client_id', 'created_at'),
    )
