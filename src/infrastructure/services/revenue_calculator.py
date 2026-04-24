"""
Revenue calculation service.

Business Rule (SOURCE OF TRUTH):
Revenue = SUM(total_amount or summa) FROM client_transaction_data
WHERE is_taken_away = false AND remaining_amount = 0 (fully paid, not yet taken)

This represents:
- Fully paid cargo (remaining_amount = 0)
- Still in warehouse (is_taken_away = false)

Recommended DB Index:
CREATE INDEX idx_revenue_calc ON client_transaction_data(is_taken_away, remaining_amount);
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, case

from src.infrastructure.database.models.client_transaction import ClientTransaction


class RevenueCalculator:
    """
    Centralized revenue calculation service.

    Uses client_transaction_data as the source of truth for revenue metrics.
    Revenue = fully paid cargo not yet taken away.
    """

    @staticmethod
    async def get_current_revenue(
        session: AsyncSession,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> float:
        """
        Get current revenue (fully paid, not taken away).

        Args:
            session: Database session
            start_date: Optional start date filter (inclusive)
            end_date: Optional end date filter (inclusive)

        Returns:
            Total revenue amount
        """
        conditions = [
            ClientTransaction.is_taken_away == False,
            ClientTransaction.remaining_amount == 0
        ]

        if start_date:
            conditions.append(ClientTransaction.created_at >= start_date)
        if end_date:
            conditions.append(ClientTransaction.created_at <= end_date)

        result = await session.execute(
            select(
                func.sum(
                    func.coalesce(ClientTransaction.total_amount, ClientTransaction.summa)
                )
            ).where(and_(*conditions))
        )

        return float(result.scalar_one() or 0.0)

    @staticmethod
    async def get_revenue_metrics(
        session: AsyncSession,
        current_month_start: datetime,
        current_month_end: datetime,
        previous_month_start: datetime,
        previous_month_end: datetime
    ) -> dict:
        """
        Get comprehensive revenue metrics for dashboard.

        Uses single optimized query to get:
        - Lifetime revenue
        - Current month revenue
        - Previous month revenue

        Args:
            session: Database session
            current_month_start: Start of current month
            current_month_end: End of current month
            previous_month_start: Start of previous month
            previous_month_end: End of previous month

        Returns:
            Dict with lifetime_revenue, revenue_this_month, revenue_last_month, growth_percent
        """
        # Base conditions: fully paid, not taken away
        base_conditions = and_(
            ClientTransaction.is_taken_away == False,
            ClientTransaction.remaining_amount == 0
        )

        # Use COALESCE to prefer total_amount, fall back to summa
        amount_expr = func.coalesce(ClientTransaction.total_amount, ClientTransaction.summa)

        result = await session.execute(
            select(
                # Lifetime revenue (all matching records)
                func.sum(
                    case(
                        (base_conditions, amount_expr),
                        else_=0
                    )
                ).label('lifetime_revenue'),
                # Current month revenue
                func.sum(
                    case(
                        (
                            and_(
                                base_conditions,
                                ClientTransaction.created_at >= current_month_start,
                                ClientTransaction.created_at <= current_month_end
                            ),
                            amount_expr
                        ),
                        else_=0
                    )
                ).label('revenue_this_month'),
                # Previous month revenue
                func.sum(
                    case(
                        (
                            and_(
                                base_conditions,
                                ClientTransaction.created_at >= previous_month_start,
                                ClientTransaction.created_at <= previous_month_end
                            ),
                            amount_expr
                        ),
                        else_=0
                    )
                ).label('revenue_last_month')
            )
        )

        row = result.one()

        lifetime_revenue = float(row.lifetime_revenue) if row.lifetime_revenue else 0.0
        revenue_this_month = float(row.revenue_this_month) if row.revenue_this_month else 0.0
        revenue_last_month = float(row.revenue_last_month) if row.revenue_last_month else 0.0

        # Calculate growth percentage
        if revenue_last_month > 0:
            growth_percent = round(
                ((revenue_this_month - revenue_last_month) / revenue_last_month) * 100, 2
            )
        elif revenue_this_month > 0:
            growth_percent = 100.0
        else:
            growth_percent = 0.0

        return {
            "lifetime_revenue": lifetime_revenue,
            "revenue_this_month": revenue_this_month,
            "revenue_last_month": revenue_last_month,
            "growth_percent": growth_percent
        }

    @staticmethod
    async def get_daily_revenue(
        session: AsyncSession,
        target_date: date
    ) -> float:
        """
        Get revenue for a specific day.

        Args:
            session: Database session
            target_date: The date to calculate revenue for

        Returns:
            Revenue for that day
        """
        start_dt = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(target_date, datetime.max.time()).replace(tzinfo=timezone.utc)

        return await RevenueCalculator.get_current_revenue(session, start_dt, end_dt)

    @staticmethod
    async def get_weekly_revenue(
        session: AsyncSession,
        end_date: date
    ) -> float:
        """
        Get revenue for the last 7 days.

        Args:
            session: Database session
            end_date: The end date (inclusive)

        Returns:
            Revenue for last 7 days
        """
        start_date = end_date - timedelta(days=6)
        start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)

        return await RevenueCalculator.get_current_revenue(session, start_dt, end_dt)

    @staticmethod
    async def get_monthly_revenue(
        session: AsyncSession,
        year: int,
        month: int
    ) -> float:
        """
        Get revenue for a specific month.

        Args:
            session: Database session
            year: Year
            month: Month (1-12)

        Returns:
            Revenue for that month
        """
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)

        return await RevenueCalculator.get_current_revenue(session, start_dt, end_dt)
