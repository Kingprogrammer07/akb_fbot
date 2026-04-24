"""Flight Schedule ORM model.

Tracks planned, delayed, and arrived flights so managers can publish
a visible schedule to the operations team without editing raw data.
"""
from datetime import date

from sqlalchemy import CheckConstraint, Date, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base

_VALID_TYPES = ("avia", "aksiya")
_VALID_STATUSES = ("arrived", "scheduled", "delayed")


class FlightSchedule(Base):
    """
    A single entry in the manager-maintained flight calendar.

    Attributes:
        flight_name: Human-readable identifier for the shipment batch.
        flight_date: Expected or actual arrival/departure date.
        type:        Cargo category — 'avia' (air freight) or 'aksiya' (promo/special).
        status:      Current state — 'scheduled', 'delayed', or 'arrived'.
        notes:       Free-form manager notes (optional).
    """

    __tablename__ = "flight_schedules"

    flight_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Shipment batch identifier, e.g. M123-2025",
    )
    flight_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Expected or actual flight date",
    )
    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="'avia' or 'aksiya'",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="scheduled",
        comment="'scheduled', 'delayed', or 'arrived'",
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional manager notes",
    )

    __table_args__ = (
        CheckConstraint(f"type IN {_VALID_TYPES}", name="ck_flight_schedule_type"),
        CheckConstraint(f"status IN {_VALID_STATUSES}", name="ck_flight_schedule_status"),
        Index("ix_flight_schedule_date_status", "flight_date", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<FlightSchedule("
            f"id={self.id}, "
            f"flight={self.flight_name!r}, "
            f"date={self.flight_date}, "
            f"status={self.status!r}"
            f")>"
        )
