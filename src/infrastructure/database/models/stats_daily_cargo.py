"""Daily cargo statistics aggregation model."""
from sqlalchemy import Date, Integer, Numeric, String, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base


class StatsDailyCargo(Base):
    """
    Daily aggregated statistics for cargo uploads.
    
    Aggregated daily to enable fast queries for statistics dashboard.
    Data is idempotent - can be recalculated from source tables.
    """
    
    __tablename__ = "stats_daily_cargo"
    
    # Date for which stats are aggregated (YYYY-MM-DD)
    stat_date: Mapped[str] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Date for which statistics are aggregated (YYYY-MM-DD)"
    )
    
    # Flight name (nullable for overall daily stats, or specific flight stats)
    flight_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Flight name (null for overall daily stats, or specific flight)"
    )
    
    # Total cargo uploads on this date
    uploads_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of cargo photo uploads"
    )
    
    # Total unique clients who uploaded cargo
    unique_clients_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of unique clients who uploaded cargo"
    )
    
    # Total photos uploaded
    total_photos_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total number of photos uploaded"
    )
    
    # Total weight in kg
    total_weight_kg: Mapped[float | None] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=True,
        comment="Total weight of all cargo in kilograms"
    )
    
    # Average weight per cargo item
    avg_weight_kg: Mapped[float | None] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=True,
        comment="Average weight per cargo item in kilograms"
    )
    
    # Unique constraint: one row per date + flight_name combination
    __table_args__ = (
        UniqueConstraint('stat_date', 'flight_name', name='uq_stats_daily_cargo_date_flight'),
        Index('ix_stats_daily_cargo_stat_date_flight', 'stat_date', 'flight_name'),
    )
    
    def __repr__(self) -> str:
        return f"<StatsDailyCargo(date={self.stat_date}, flight={self.flight_name}, uploads={self.uploads_count})>"

