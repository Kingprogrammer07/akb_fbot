"""Stats Daily Payments DAO."""
from datetime import date
from typing import Optional
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.stats_daily_payments import StatsDailyPayments


class StatsDailyPaymentsDAO:
    """Data Access Object for StatsDailyPayments operations."""

    @staticmethod
    async def get_by_date_and_type(
        session: AsyncSession,
        stat_date: date,
        payment_type: Optional[str] = None
    ) -> Optional[StatsDailyPayments]:
        """Get statistics for a specific date and payment type (or overall if type is None)."""
        conditions = [StatsDailyPayments.stat_date == stat_date]
        if payment_type is None:
            conditions.append(StatsDailyPayments.payment_type.is_(None))
        else:
            conditions.append(StatsDailyPayments.payment_type == payment_type)
        
        result = await session.execute(
            select(StatsDailyPayments).where(and_(*conditions))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(
        session: AsyncSession,
        stat_date: date,
        approvals_count: int = 0,
        total_amount: float = 0,
        full_payments_count: int = 0,
        partial_payments_count: int = 0,
        full_payments_amount: float = 0,
        partial_payments_amount: float = 0,
        avg_amount: Optional[float] = None,
        payment_type: Optional[str] = None
    ) -> StatsDailyPayments:
        """
        Insert or update statistics for a date and payment type (idempotent).
        
        If record exists, updates it. Otherwise creates new one.
        """
        existing = await StatsDailyPaymentsDAO.get_by_date_and_type(session, stat_date, payment_type)
        
        if existing:
            existing.approvals_count = approvals_count
            existing.total_amount = total_amount
            existing.full_payments_count = full_payments_count
            existing.partial_payments_count = partial_payments_count
            existing.full_payments_amount = full_payments_amount
            existing.partial_payments_amount = partial_payments_amount
            existing.avg_amount = avg_amount
            await session.flush()
            await session.refresh(existing)
            return existing
        else:
            new_stat = StatsDailyPayments(
                stat_date=stat_date,
                payment_type=payment_type,
                approvals_count=approvals_count,
                total_amount=total_amount,
                full_payments_count=full_payments_count,
                partial_payments_count=partial_payments_count,
                full_payments_amount=full_payments_amount,
                partial_payments_amount=partial_payments_amount,
                avg_amount=avg_amount
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
        payment_type: Optional[str] = None,
        limit: int = 365,
        offset: int = 0
    ) -> list[StatsDailyPayments]:
        """Get statistics within a date range, optionally filtered by payment type."""
        conditions = [
            StatsDailyPayments.stat_date >= start_date,
            StatsDailyPayments.stat_date <= end_date
        ]
        
        if payment_type is None:
            # Get overall stats (where payment_type is NULL)
            conditions.append(StatsDailyPayments.payment_type.is_(None))
        else:
            conditions.append(StatsDailyPayments.payment_type == payment_type)
        
        result = await session.execute(
            select(StatsDailyPayments)
            .where(and_(*conditions))
            .order_by(desc(StatsDailyPayments.stat_date))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_total_amount(
        session: AsyncSession,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        payment_type: Optional[str] = None
    ) -> float:
        """Get total payment amount within date range."""
        conditions = []
        if start_date:
            conditions.append(StatsDailyPayments.stat_date >= start_date)
        if end_date:
            conditions.append(StatsDailyPayments.stat_date <= end_date)
        if payment_type:
            conditions.append(StatsDailyPayments.payment_type == payment_type)
        elif payment_type is None:
            # Overall stats only
            conditions.append(StatsDailyPayments.payment_type.is_(None))
        
        result = await session.execute(
            select(func.sum(StatsDailyPayments.total_amount))
            .where(and_(*conditions) if conditions else True)
        )
        total = result.scalar_one()
        return float(total) if total else 0.0

