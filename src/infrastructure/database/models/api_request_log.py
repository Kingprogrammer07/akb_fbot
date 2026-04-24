"""API Request Log database model."""
from sqlalchemy import String, Integer, BigInteger, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base


class APIRequestLog(Base):
    """
    API Request Log model.
    
    Logs all HTTP requests to the API for monitoring, analytics, and debugging.
    Stores request metadata, response status, timing, and errors.
    
    No foreign key constraints - user_id is stored as integer to avoid blocking writes.
    """
    
    __tablename__ = "api_request_logs"
    
    # HTTP method (GET, POST, PUT, DELETE, etc.)
    method: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        comment="HTTP method (GET, POST, PUT, DELETE, etc.)"
    )
    
    # API endpoint path (e.g., '/auth/login', '/api/v1/flights/photos')
    endpoint: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        index=True,
        comment="API endpoint path"
    )
    
    # User identifier (nullable - unauthenticated requests don't have user_id)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
        comment="Telegram ID of authenticated user (no FK to avoid blocking writes)"
    )
    
    # HTTP response status code (200, 400, 404, 500, etc.)
    response_status: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="HTTP response status code"
    )
    
    # Response time in milliseconds
    response_time_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Request processing time in milliseconds"
    )
    
    # Error message (nullable - successful requests don't have errors)
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error message if request failed (null for successful requests)"
    )
    
    # IP address of client (optional, for security/geo analytics)
    ip_address: Mapped[str | None] = mapped_column(
        String(45),  # IPv6 max length
        nullable=True,
        comment="Client IP address"
    )
    
    # Indexes for efficient queries
    __table_args__ = (
        Index('ix_api_request_logs_endpoint_created_at', 'endpoint', 'created_at'),
        Index('ix_api_request_logs_response_status_created_at', 'response_status', 'created_at'),
        Index('ix_api_request_logs_user_id_created_at', 'user_id', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return f"<APIRequestLog(id={self.id}, method={self.method}, endpoint={self.endpoint}, status={self.response_status}, created_at={self.created_at})>"

