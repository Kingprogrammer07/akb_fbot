"""Expected Flight Cargo ORM model.

Stores the pre-arrival manifest of cargo coming from China — a "what we expect
to receive" registry that bridges the Google-Sheets workflow into PostgreSQL.
Each row represents a single tracking code assigned to one client within one
flight.  The (track_code) column is UNIQUE; a given track code can belong to
exactly one flight and one client at any point in time.
"""
from sqlalchemy import Boolean, String, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from src.infrastructure.database.models.base import Base


class ExpectedFlightCargo(Base):
    """
    Pre-arrival cargo manifest entry.

    Attributes:
        flight_name: Shipment batch / flight identifier (e.g. "M123-2025").
                     Multiple clients and track codes share the same flight_name.
        client_code: The client's human-readable code (extra_code or client_code
                     from the Client table).  Stored as a plain string — not a FK —
                     consistent with the CargoItem convention used elsewhere.
        track_code:  Globally unique tracking code.  One track code belongs to
                     exactly one client in one flight.
    """

    __tablename__ = "expected_flight_cargos"

    flight_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Shipment batch / flight name, e.g. M123-2025",
    )
    client_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Client code — matches Client.extra_code or Client.client_code",
    )
    track_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
        comment="Globally unique cargo tracking code",
    )

    is_placeholder: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=expression.false(),
        index=True,
        comment=(
            "Placeholder row used to register an empty flight (no real cargo yet). "
            "Filtered out of every read/stat/export query; removed automatically "
            "when the first real track code is added under the same flight."
        ),
    )

    # Composite index: accelerates the most common query pattern
    # (filter by flight + client simultaneously).
    __table_args__ = (
        Index("ix_expected_cargo_flight_client", "flight_name", "client_code"),
    )

    # Sentinel values used for placeholder rows.  Kept constant so service code
    # can both create and identify them without magic strings scattered about.
    PLACEHOLDER_CLIENT_CODE: str = "__EMPTY__"

    @classmethod
    def make_placeholder_track_code(cls, flight_name: str) -> str:
        """Return the deterministic sentinel track code for a given flight."""
        return f"__EMPTY__{flight_name.strip().upper()}"

    def __repr__(self) -> str:
        return (
            f"<ExpectedFlightCargo("
            f"id={self.id}, "
            f"flight={self.flight_name!r}, "
            f"client={self.client_code!r}, "
            f"track={self.track_code!r}"
            f")>"
        )
