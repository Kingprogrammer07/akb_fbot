"""Stats Daily Clients DAO."""
from datetime import date
from typing import Optional
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.stats_daily_clients import StatsDailyClients


class StatsDailyClientsDAO:
    """Data Access Object for StatsDailyClients operations."""

    @staticmethod
    async def get_by_date(
        session: AsyncSession,
        stat_date: date
    ) -> Optional[StatsDailyClients]:
        """Get statistics for a specific date."""
        result = await session.execute(
            select(StatsDailyClients).where(StatsDailyClients.stat_date == stat_date)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(
        session: AsyncSession,
        stat_date: date,
        registrations_count: int = 0,
        approvals_count: int = 0,
        logins_count: int = 0,
        active_clients_count: int = 0
    ) -> StatsDailyClients:
        """
        Insert or update statistics for a date (idempotent).
        
        If record exists, updates it. Otherwise creates new one.
        """
        existing = await StatsDailyClientsDAO.get_by_date(session, stat_date)
        
        if existing:
            existing.registrations_count = registrations_count
            existing.approvals_count = approvals_count
            existing.logins_count = logins_count
            existing.active_clients_count = active_clients_count
            await session.flush()
            await session.refresh(existing)
            return existing
        else:
            new_stat = StatsDailyClients(
                stat_date=stat_date,
                registrations_count=registrations_count,
                approvals_count=approvals_count,
                logins_count=logins_count,
                active_clients_count=active_clients_count
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
        limit: int = 365,
        offset: int = 0
    ) -> list[StatsDailyClients]:
        """Get statistics within a date range, ordered by date descending."""
        result = await session.execute(
            select(StatsDailyClients)
            .where(
                and_(
                    StatsDailyClients.stat_date >= start_date,
                    StatsDailyClients.stat_date <= end_date
                )
            )
            .order_by(desc(StatsDailyClients.stat_date))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_total_registrations(
        session: AsyncSession,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> int:
        """Get total registrations within date range."""
        conditions = []
        if start_date:
            conditions.append(StatsDailyClients.stat_date >= start_date)
        if end_date:
            conditions.append(StatsDailyClients.stat_date <= end_date)
        
        result = await session.execute(
            select(func.sum(StatsDailyClients.registrations_count))
            .where(and_(*conditions) if conditions else True)
        )
        total = result.scalar_one()
        return int(total) if total else 0

