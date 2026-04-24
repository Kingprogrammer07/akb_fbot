"""Flight Cargo database model."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Text, Numeric, Boolean, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from src.infrastructure.database.models.base import Base


class FlightCargo(Base):
    """
    Flight cargo photo model.

    Stores cargo photos with client ID, flight name, weight, and Telegram file_id.
    Used for admin photo upload system via WebApp.
    """

    __tablename__ = "flight_cargos"

    # Flight information
    flight_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Flight/Reys name from Google Sheets (e.g., M123-2025)",
    )

    # Client information
    client_id: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Client code (e.g., SS123, AD456)",
    )

    # Telegram photo file IDs (JSON array of file_ids)
    photo_file_ids: Mapped[str] = mapped_column(
        Text, nullable=False, comment="JSON array of Telegram photo file IDs"
    )

    # Cargo details
    weight_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True, comment="Weight in kilograms"
    )

    price_per_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True, comment="Price per kilogram (e.g., 9.2, 10.4)"
    )

    comment: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Optional comment or notes"
    )

    # Delivery status
    is_sent: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="Whether this cargo photo has been sent to the client",
    )

    is_sent_date: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="Date/time when cargo was sent to the client"
    )

    # Web delivery status
    is_sent_web: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=expression.false(),
        nullable=False,
        comment="Whether this cargo has been sent via web interface",
    )
    is_sent_web_date: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="Date/time when cargo was sent via web interface",
    )

    # Composite index for efficient queries
    __table_args__ = (
        Index("ix_flight_cargos_flight_client", "flight_name", "client_id"),
    )

    def __repr__(self) -> str:
        return f"<FlightCargo(id={self.id}, flight={self.flight_name}, client={self.client_id})>"
