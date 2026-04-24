"""Stats Daily Cargo DAO."""
from datetime import date
from typing import Optional
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.stats_daily_cargo import StatsDailyCargo


class StatsDailyCargoDAO:
    """Data Access Object for StatsDailyCargo operations."""

    @staticmethod
    async def get_by_date_and_flight(
        session: AsyncSession,
        stat_date: date,
        flight_name: Optional[str] = None
    ) -> Optional[StatsDailyCargo]:
        """Get statistics for a specific date and flight (or overall if flight_name is None)."""
        conditions = [StatsDailyCargo.stat_date == stat_date]
        if flight_name is None:
            conditions.append(StatsDailyCargo.flight_name.is_(None))
        else:
            conditions.append(StatsDailyCargo.flight_name == flight_name)
        
        result = await session.execute(
            select(StatsDailyCargo).where(and_(*conditions))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(
        session: AsyncSession,
        stat_date: date,
        uploads_count: int = 0,
        unique_clients_count: int = 0,
        total_photos_count: int = 0,
        total_weight_kg: Optional[float] = None,
        avg_weight_kg: Optional[float] = None,
        flight_name: Optional[str] = None
    ) -> StatsDailyCargo:
        """
        Insert or update statistics for a date and flight (idempotent).
        
        If record exists, updates it. Otherwise creates new one.
        """
        existing = await StatsDailyCargoDAO.get_by_date_and_flight(session, stat_date, flight_name)
        
        if existing:
            existing.uploads_count = uploads_count
            existing.unique_clients_count = unique_clients_count
            existing.total_photos_count = total_photos_count
            existing.total_weight_kg = total_weight_kg
            existing.avg_weight_kg = avg_weight_kg
            await session.flush()
            await session.refresh(existing)
            return existing
        else:
            new_stat = StatsDailyCargo(
                stat_date=stat_date,
                flight_name=flight_name,
                uploads_count=uploads_count,
                unique_clients_count=unique_clients_count,
                total_photos_count=total_photos_count,
                total_weight_kg=total_weight_kg,
                avg_weight_kg=avg_weight_kg
            )
            session.add(new_stat)
            await session.flush()
            await session.refresh(new_stat)
            return new_stat

    @staticmethod
    async def get_date_range(
        session: AsyncSession,
        start_date: date,
        end_date: date,
        flight_name: Optional[str] = None,
        limit: int = 365,
        offset: int = 0
    ) -> list[StatsDailyCargo]:
        """Get statistics within a date range, optionally filtered by flight."""
        conditions = [
            StatsDailyCargo.stat_date >= start_date,
            StatsDailyCargo.stat_date <= end_date
        ]
        
        if flight_name is None:
            # Get overall stats (where flight_name is NULL)
            conditions.append(StatsDailyCargo.flight_name.is_(None))
        else:
            conditions.append(StatsDailyCargo.flight_name == flight_name)
        
        result = await session.execute(
            select(StatsDailyCargo)
            .where(and_(*conditions))
            .order_by(desc(StatsDailyCargo.stat_date))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_total_uploads(
        session: AsyncSession,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        flight_name: Optional[str] = None
    ) -> int:
        """Get total uploads within date range."""
        conditions = []
        if start_date:
            conditions.append(StatsDailyCargo.stat_date >= start_date)
        if end_date:
            conditions.append(StatsDailyCargo.stat_date <= end_date)
        if flight_name:
            conditions.append(StatsDailyCargo.flight_name == flight_name)
        elif flight_name is None:
            # Overall stats only
            conditions.append(StatsDailyCargo.flight_name.is_(None))
        
        result = await session.execute(
            select(func.sum(StatsDailyCargo.uploads_count))
            .where(and_(*conditions) if conditions else True)
        )
        total = result.scalar_one()
        return int(total) if total else 0

