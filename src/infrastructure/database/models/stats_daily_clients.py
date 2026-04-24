"""Daily client statistics aggregation model."""
from sqlalchemy import Date, Integer, BigInteger, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base


class StatsDailyClients(Base):
    """
    Daily aggregated statistics for client registrations and approvals.
    
    Aggregated daily to enable fast queries for statistics dashboard.
    Data is idempotent - can be recalculated from source tables.
    """
    
    __tablename__ = "stats_daily_clients"
    
    # Date for which stats are aggregated (YYYY-MM-DD)
    stat_date: Mapped[str] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Date for which statistics are aggregated (YYYY-MM-DD)"
    )
    
    # Total new registrations on this date
    registrations_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of new client registrations"
    )
    
    # Total approvals on this date
    approvals_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of client approvals"
    )
    
    # Total logins on this date
    logins_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of client logins"
    )
    
    # Total active clients (with client_code) as of this date
    active_clients_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total number of active clients (with client_code) as of this date"
    )
    
    # Unique constraint: one row per date
    __table_args__ = (
        UniqueConstraint('stat_date', name='uq_stats_daily_clients_date'),
        Index('ix_stats_daily_clients_stat_date', 'stat_date'),
    )
    
    def __repr__(self) -> str:
        return f"<StatsDailyClients(date={self.stat_date}, registrations={self.registrations_count}, approvals={self.approvals_count})>"

