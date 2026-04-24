"""Carousel statistics model for daily analytics tracking."""
from datetime import date

from sqlalchemy import Date, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base


class CarouselStat(Base):
    """
    Daily aggregated statistics for carousel items.
    
    Tracks views and clicks per carousel item per day.
    Uses upsert logic to increment counters.
    """
    
    __tablename__ = "carousel_stats"

    carousel_item_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("carousel_items.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK to carousel_items.id"
    )
    views: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Number of views on this date"
    )
    clicks: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Number of clicks on this date"
    )
    date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="Date of aggregation (YYYY-MM-DD)"
    )

    __table_args__ = (
        UniqueConstraint(
            'carousel_item_id', 'date',
            name='uq_carousel_stats_item_date'
        ),
        Index(
            'ix_carousel_stats_item_date',
            'carousel_item_id', 'date'
        ),
    )

    def __repr__(self) -> str:
        return f"<CarouselStat(item_id={self.carousel_item_id}, date={self.date}, views={self.views}, clicks={self.clicks})>"
