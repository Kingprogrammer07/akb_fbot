"""Daily payment statistics aggregation model."""
from sqlalchemy import Date, Integer, Numeric, String, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base


class StatsDailyPayments(Base):
    """
    Daily aggregated statistics for payments.
    
    Aggregated daily to enable fast queries for statistics dashboard.
    Data is idempotent - can be recalculated from source tables.
    """
    
    __tablename__ = "stats_daily_payments"
    
    # Date for which stats are aggregated (YYYY-MM-DD)
    stat_date: Mapped[str] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Date for which statistics are aggregated (YYYY-MM-DD)"
    )
    
    # Payment type (nullable for overall daily stats, or specific type stats)
    payment_type: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        index=True,
        comment="Payment type: 'online' or 'cash' (null for overall stats)"
    )
    
    # Total payment approvals on this date
    approvals_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of payment approvals"
    )
    
    # Total amount approved (in UZS)
    total_amount: Mapped[float] = mapped_column(
        Numeric(precision=15, scale=2),
        nullable=False,
        default=0,
        comment="Total amount of payments approved in UZS"
    )
    
    # Number of full payments
    full_payments_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of full payment approvals"
    )
    
    # Number of partial payments
    partial_payments_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of partial payment approvals"
    )
    
    # Total amount from full payments
    full_payments_amount: Mapped[float] = mapped_column(
        Numeric(precision=15, scale=2),
        nullable=False,
        default=0,
        comment="Total amount from full payments in UZS"
    )
    
    # Total amount from partial payments
    partial_payments_amount: Mapped[float] = mapped_column(
        Numeric(precision=15, scale=2),
        nullable=False,
        default=0,
        comment="Total amount from partial payments in UZS"
    )
    
    # Average payment amount
    avg_amount: Mapped[float | None] = mapped_column(
        Numeric(precision=15, scale=2),
        nullable=True,
        comment="Average payment amount in UZS"
    )
    
    # Unique constraint: one row per date + payment_type combination
    __table_args__ = (
        UniqueConstraint('stat_date', 'payment_type', name='uq_stats_daily_payments_date_type'),
        Index('ix_stats_daily_payments_stat_date_type', 'stat_date', 'payment_type'),
    )
    
    def __repr__(self) -> str:
        return f"<StatsDailyPayments(date={self.stat_date}, type={self.payment_type}, count={self.approvals_count}, total={self.total_amount})>"

