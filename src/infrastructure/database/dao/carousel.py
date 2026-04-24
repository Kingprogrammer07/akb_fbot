"""DAO for Carousel item and stats management."""
import logging
from datetime import date

from sqlalchemy import select, func, update as sa_update, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.carousel_item import CarouselItem
from src.infrastructure.database.models.carousel_stat import CarouselStat
from src.infrastructure.tools.datetime_utils import get_current_time

logger = logging.getLogger(__name__)


class CarouselDAO:
    """Data Access Object for carousel items and statistics."""

    @staticmethod
    async def create(session: AsyncSession, data: dict) -> CarouselItem:
        """Create a new carousel item."""
        item = CarouselItem(**data)
        session.add(item)
        await session.flush()
        await session.refresh(item)
        logger.info(f"Created CarouselItem id={item.id}, type={item.type}")
        return item

    @staticmethod
    async def get_by_id(session: AsyncSession, item_id: int) -> CarouselItem | None:
        """Get a carousel item by ID."""
        result = await session.execute(
            select(CarouselItem).where(CarouselItem.id == item_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update(session: AsyncSession, item: CarouselItem, data: dict) -> CarouselItem:
        """Update an existing carousel item."""
        for key, value in data.items():
            if hasattr(item, key):
                setattr(item, key, value)
        await session.flush()
        await session.refresh(item)
        logger.info(f"Updated CarouselItem id={item.id}")
        return item

    @staticmethod
    async def delete(session: AsyncSession, item_id: int) -> bool:
        """Hard delete a carousel item by ID."""
        result = await session.execute(
            delete(CarouselItem).where(CarouselItem.id == item_id)
        )
        await session.flush()
        deleted = result.rowcount > 0
        if deleted:
            logger.info(f"Deleted CarouselItem id={item_id}")
        return deleted

    @staticmethod
    async def get_all(session: AsyncSession) -> list[CarouselItem]:
        """Get all carousel items (including inactive), ordered by order asc."""
        result = await session.execute(
            select(CarouselItem).order_by(CarouselItem.order.asc(), CarouselItem.id.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_all_active(session: AsyncSession) -> list[CarouselItem]:
        """Get all active carousel items, ordered by order asc."""
        result = await session.execute(
            select(CarouselItem)
            .where(CarouselItem.is_active == True)
            .order_by(CarouselItem.order.asc(), CarouselItem.id.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def increment_view(session: AsyncSession, item_id: int) -> None:
        """
        Increment daily view count for a carousel item.
        
        Uses PostgreSQL upsert (INSERT ... ON CONFLICT DO UPDATE)
        to atomically create or increment the daily stat row.
        """
        today = get_current_time().date()

        stmt = pg_insert(CarouselStat).values(
            carousel_item_id=item_id,
            date=today,
            views=1,
            clicks=0,
        )
        stmt = stmt.on_conflict_do_update(
            constraint='uq_carousel_stats_item_date',
            set_={'views': CarouselStat.views + 1}
        )
        await session.execute(stmt)
        await session.flush()

    @staticmethod
    async def increment_click(session: AsyncSession, item_id: int) -> None:
        """
        Increment daily click count for a carousel item.
        
        Uses PostgreSQL upsert (INSERT ... ON CONFLICT DO UPDATE)
        to atomically create or increment the daily stat row.
        """
        today = get_current_time().date()

        stmt = pg_insert(CarouselStat).values(
            carousel_item_id=item_id,
            date=today,
            views=0,
            clicks=1,
        )
        stmt = stmt.on_conflict_do_update(
            constraint='uq_carousel_stats_item_date',
            set_={'clicks': CarouselStat.clicks + 1}
        )
        await session.execute(stmt)
        await session.flush()

    @staticmethod
    async def get_stats(session: AsyncSession) -> list[dict]:
        """
        Get all carousel items with their aggregated total views and clicks.
        
        Returns list of dicts: {item: CarouselItem, total_views: int, total_clicks: int}
        """
        # Subquery for aggregated stats
        stats_subq = (
            select(
                CarouselStat.carousel_item_id,
                func.coalesce(func.sum(CarouselStat.views), 0).label('total_views'),
                func.coalesce(func.sum(CarouselStat.clicks), 0).label('total_clicks'),
            )
            .group_by(CarouselStat.carousel_item_id)
            .subquery()
        )

        # Join items with stats
        query = (
            select(
                CarouselItem,
                func.coalesce(stats_subq.c.total_views, 0).label('total_views'),
                func.coalesce(stats_subq.c.total_clicks, 0).label('total_clicks'),
            )
            .outerjoin(stats_subq, CarouselItem.id == stats_subq.c.carousel_item_id)
            .order_by(CarouselItem.order.asc(), CarouselItem.id.desc())
        )

        result = await session.execute(query)
        rows = result.all()

        return [
            {
                'item': row[0],
                'total_views': int(row[1]),
                'total_clicks': int(row[2]),
            }
            for row in rows
        ]
