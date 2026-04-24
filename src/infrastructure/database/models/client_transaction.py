"""Client transaction model."""

from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import BigInteger, String, Numeric, Integer, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models.base import Base

if TYPE_CHECKING:
    from src.infrastructure.database.models.client_payment_event import (
        ClientPaymentEvent,
    )


class ClientTransaction(Base):
    """Client transaction for tracking payments."""

    __tablename__ = "client_transaction_data"

    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    client_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    qator_raqami: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Row number in Google Sheets"
    )
    reys: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Worksheet/flight name"
    )
    summa: Mapped[float] = mapped_column(
        Numeric(precision=12, scale=2), nullable=False, comment="Payment amount"
    )
    vazn: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Weight from row_data[2]"
    )

    # Payment receipt (check) file_id from Telegram
    payment_receipt_file_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Telegram file_id of payment receipt (photo or PDF)",
    )

    # Payment type
    payment_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default="online",
        comment="Payment type: 'online', 'cash', or 'card'",
    )

    # Payment status for partial payments
    payment_status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default="paid",
        comment="Payment status: 'pending', 'partial', or 'paid'",
    )

    fully_paid_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Date/time when transaction became fully paid",
    )

    # Partial payment fields
    paid_amount: Mapped[float] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=False,
        server_default="0",
        comment="Amount already paid (for partial payments)",
    )

    total_amount: Mapped[Optional[float]] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=True,
        comment="Total amount required (snapshot at first payment)",
    )

    remaining_amount: Mapped[float] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=False,
        server_default="0",
        comment="Remaining amount to be paid",
    )

    payment_deadline: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Payment deadline (15 days from first payment, nullable)",
    )

    # Payment balance difference (debt/overpayment tracking)
    payment_balance_difference: Mapped[float] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=False,
        server_default="0",
        comment="Difference between paid_amount and expected_amount (negative=debt, positive=overpaid)",
    )

    # Cargo taken away status
    is_taken_away: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether cargo has been taken away by client",
    )
    taken_away_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Date when cargo was taken away"
    )

    # Relationship to payment events
    # Note: Ordering is handled in DAO/service layer to avoid mapper initialization issues
    payment_events: Mapped[list["ClientPaymentEvent"]] = relationship(
        "ClientPaymentEvent", back_populates="transaction", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ClientTransaction(id={self.id}, client_code={self.client_code}, reys={self.reys}, summa={self.summa})>"
