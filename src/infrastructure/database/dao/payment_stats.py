"""
Payment Statistics DAO.

Optimized SQL queries for financial statistics from client_payment_events.
All queries use efficient GROUP BY and aggregation.

SOURCE OF TRUTH: client_payment_events table
TIMEZONE: All date ranges converted from Asia/Tashkent to UTC for queries

REVENUE DEFINITION (CRITICAL):
Revenue = payments for cargo that has NOT been taken away yet (is_taken_away=FALSE).
This represents money received but goods still in warehouse (liability/inventory).
Once cargo is taken away, it transitions from revenue to completed transaction.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from sqlalchemy import select, func, and_, text, case
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.client_payment_event import ClientPaymentEvent
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.tools.datetime_utils import (
    tashkent_date_to_utc_range,
    get_current_business_date,
    TASHKENT_TZ
)


class PaymentStatsDAO:
    """
    Data Access Object for payment statistics.

    All methods return raw data - business logic is in PaymentStatsService.
    All date parameters are in Asia/Tashkent calendar dates.
    """

    @staticmethod
    async def get_totals_by_provider(
        session: AsyncSession,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        include_taken_away: bool = False
    ) -> Dict[str, Any]:
        """
        Get payment totals grouped by provider.

        IMPORTANT: By default, only includes payments for cargo NOT taken away.
        This is the correct revenue calculation - money received but goods still in warehouse.

        Args:
            session: Database session
            start_date: Start date (Tashkent calendar), None = no limit
            end_date: End date (Tashkent calendar), None = no limit
            include_taken_away: If True, include all payments regardless of is_taken_away status.
                               If False (default), only count payments where is_taken_away=FALSE.

        Returns:
            Dict with provider totals:
            {
                'cash': {'amount': Decimal, 'count': int},
                'click': {'amount': Decimal, 'count': int},
                'payme': {'amount': Decimal, 'count': int},
            }
        """
        # Build WHERE conditions
        conditions = []

        if start_date:
            start_utc, _ = tashkent_date_to_utc_range(start_date)
            conditions.append(ClientPaymentEvent.created_at >= start_utc)

        if end_date:
            _, end_utc = tashkent_date_to_utc_range(end_date)
            conditions.append(ClientPaymentEvent.created_at <= end_utc)

        # CRITICAL: Filter by is_taken_away=FALSE for revenue calculation
        # Revenue = payments for cargo that has NOT been taken away yet
        if not include_taken_away:
            conditions.append(ClientTransaction.is_taken_away == False)

        # Filter out WALLET_ADJ pseudo-transactions
        conditions.append(~ClientTransaction.reys.like("WALLET_ADJ:%"))

        # Query with GROUP BY payment_provider
        # Join with client_transaction_data to check is_taken_away
        query = (
            select(
                ClientPaymentEvent.payment_provider,
                func.coalesce(func.sum(ClientPaymentEvent.amount), 0).label('total_amount'),
                func.count(ClientPaymentEvent.id).label('payment_count')
            )
            .join(
                ClientTransaction,
                ClientPaymentEvent.transaction_id == ClientTransaction.id
            )
            .group_by(ClientPaymentEvent.payment_provider)
        )

        if conditions:
            query = query.where(and_(*conditions))

        result = await session.execute(query)

        # Initialize with zeros
        totals = {
            'cash': {'amount': Decimal('0'), 'count': 0},
            'click': {'amount': Decimal('0'), 'count': 0},
            'payme': {'amount': Decimal('0'), 'count': 0},
        }

        for row in result:
            provider = row.payment_provider or 'cash'  # Handle legacy NULL
            if provider in totals:
                totals[provider]['amount'] = Decimal(str(row.total_amount or 0))
                totals[provider]['count'] = row.payment_count or 0

        return totals

    @staticmethod
    async def get_daily_totals_by_provider(
        session: AsyncSession,
        start_date: date,
        end_date: date,
        include_taken_away: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get daily payment totals grouped by date and provider.

        Uses date_trunc for efficient grouping.

        IMPORTANT: By default, only includes payments for cargo NOT taken away.

        Args:
            session: Database session
            start_date: Start date (Tashkent calendar)
            end_date: End date (Tashkent calendar)
            include_taken_away: If True, include all payments. If False (default), only is_taken_away=FALSE.

        Returns:
            List of dicts with daily totals per provider
        """
        start_utc, _ = tashkent_date_to_utc_range(start_date)
        _, end_utc = tashkent_date_to_utc_range(end_date)

        # Build is_taken_away condition
        taken_away_condition = "" if include_taken_away else "AND ctd.is_taken_away = FALSE"
        
        # Filter out WALLET_ADJ
        wallet_filter = "AND ctd.reys NOT LIKE 'WALLET_ADJ:%'"

        # Use timezone-aware date extraction
        # PostgreSQL: AT TIME ZONE converts to Tashkent before extracting date
        # CRITICAL: Join with client_transaction_data to filter by is_taken_away
        query = text(f"""
            SELECT
                DATE(cpe.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Tashkent') as stat_date,
                cpe.payment_provider,
                COALESCE(SUM(cpe.amount), 0) as total_amount,
                COUNT(cpe.id) as payment_count
            FROM client_payment_events cpe
            INNER JOIN client_transaction_data ctd ON cpe.transaction_id = ctd.id
            WHERE cpe.created_at >= :start_utc
              AND cpe.created_at <= :end_utc
              {taken_away_condition}
              {wallet_filter}
            GROUP BY stat_date, cpe.payment_provider
            ORDER BY stat_date ASC, cpe.payment_provider ASC
        """)

        result = await session.execute(
            query,
            {'start_utc': start_utc, 'end_utc': end_utc}
        )

        daily_data = []
        for row in result:
            daily_data.append({
                'date': row.stat_date,
                'provider': row.payment_provider or 'cash',
                'amount': Decimal(str(row.total_amount or 0)),
                'count': row.payment_count or 0
            })

        return daily_data

    @staticmethod
    async def get_weekly_totals_by_provider(
        session: AsyncSession,
        weeks: int = 12,
        include_taken_away: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get weekly payment totals for the last N weeks.

        Week starts on Monday (ISO standard).

        IMPORTANT: By default, only includes payments for cargo NOT taken away.

        Args:
            session: Database session
            weeks: Number of weeks to retrieve
            include_taken_away: If True, include all payments. If False (default), only is_taken_away=FALSE.

        Returns:
            List of weekly totals per provider
        """
        # Calculate date range
        today = get_current_business_date()
        # Go back N weeks
        from datetime import timedelta
        start_date = today - timedelta(weeks=weeks * 7)

        start_utc, _ = tashkent_date_to_utc_range(start_date)

        # Build is_taken_away condition
        taken_away_condition = "" if include_taken_away else "AND ctd.is_taken_away = FALSE"
        
        # Filter out WALLET_ADJ
        wallet_filter = "AND ctd.reys NOT LIKE 'WALLET_ADJ:%'"

        query = text(f"""
            SELECT
                DATE_TRUNC('week', cpe.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Tashkent')::date as week_start,
                cpe.payment_provider,
                COALESCE(SUM(cpe.amount), 0) as total_amount,
                COUNT(cpe.id) as payment_count
            FROM client_payment_events cpe
            INNER JOIN client_transaction_data ctd ON cpe.transaction_id = ctd.id
            WHERE cpe.created_at >= :start_utc
              {taken_away_condition}
              {wallet_filter}
            GROUP BY week_start, cpe.payment_provider
            ORDER BY week_start DESC, cpe.payment_provider ASC
        """)

        result = await session.execute(query, {'start_utc': start_utc})

        weekly_data = []
        for row in result:
            weekly_data.append({
                'week_start': row.week_start,
                'provider': row.payment_provider or 'cash',
                'amount': Decimal(str(row.total_amount or 0)),
                'count': row.payment_count or 0
            })

        return weekly_data

    @staticmethod
    async def get_monthly_totals_by_provider(
        session: AsyncSession,
        months: int = 12,
        include_taken_away: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get monthly payment totals for the last N months.

        IMPORTANT: By default, only includes payments for cargo NOT taken away.

        Args:
            session: Database session
            months: Number of months to retrieve
            include_taken_away: If True, include all payments. If False (default), only is_taken_away=FALSE.

        Returns:
            List of monthly totals per provider
        """
        # Calculate date range
        today = get_current_business_date()
        from datetime import timedelta
        # Approximate - go back N months
        start_date = today.replace(day=1)
        for _ in range(months):
            start_date = (start_date - timedelta(days=1)).replace(day=1)

        start_utc, _ = tashkent_date_to_utc_range(start_date)

        # Build is_taken_away condition
        taken_away_condition = "" if include_taken_away else "AND ctd.is_taken_away = FALSE"
        
        # Filter out WALLET_ADJ
        wallet_filter = "AND ctd.reys NOT LIKE 'WALLET_ADJ:%'"

        query = text(f"""
            SELECT
                DATE_TRUNC('month', cpe.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Tashkent')::date as month_start,
                cpe.payment_provider,
                COALESCE(SUM(cpe.amount), 0) as total_amount,
                COUNT(cpe.id) as payment_count
            FROM client_payment_events cpe
            INNER JOIN client_transaction_data ctd ON cpe.transaction_id = ctd.id
            WHERE cpe.created_at >= :start_utc
              {taken_away_condition}
              {wallet_filter}
            GROUP BY month_start, cpe.payment_provider
            ORDER BY month_start DESC, cpe.payment_provider ASC
        """)

        result = await session.execute(query, {'start_utc': start_utc})

        monthly_data = []
        for row in result:
            monthly_data.append({
                'month_start': row.month_start,
                'provider': row.payment_provider or 'cash',
                'amount': Decimal(str(row.total_amount or 0)),
                'count': row.payment_count or 0
            })

        return monthly_data

    @staticmethod
    async def get_payments_for_export(
        session: AsyncSession,
        start_date: date,
        end_date: date,
        provider: Optional[str] = None,
        include_taken_away: bool = False,
        limit: int = 100000
    ) -> List[Dict[str, Any]]:
        """
        Get payment events for CSV export.

        IMPORTANT: By default, only includes payments for cargo NOT taken away.

        Args:
            session: Database session
            start_date: Start date (Tashkent calendar)
            end_date: End date (Tashkent calendar)
            provider: Optional filter by provider
            include_taken_away: If True, include all payments. If False (default), only is_taken_away=FALSE.
            limit: Maximum rows

        Returns:
            List of payment event data for export
        """
        start_utc, _ = tashkent_date_to_utc_range(start_date)
        _, end_utc = tashkent_date_to_utc_range(end_date)

        conditions = [
            ClientPaymentEvent.created_at >= start_utc,
            ClientPaymentEvent.created_at <= end_utc
        ]

        if provider:
            conditions.append(ClientPaymentEvent.payment_provider == provider)

        # CRITICAL: Filter by is_taken_away=FALSE for revenue calculation
        if not include_taken_away:
            conditions.append(ClientTransaction.is_taken_away == False)

        # Filter out WALLET_ADJ pseudo-transactions
        conditions.append(~ClientTransaction.reys.like("WALLET_ADJ:%"))

        query = (
            select(
                ClientPaymentEvent.id,
                ClientPaymentEvent.transaction_id,
                ClientPaymentEvent.payment_provider,
                ClientPaymentEvent.amount,
                ClientPaymentEvent.approved_by_admin_id,
                ClientPaymentEvent.created_at,
                ClientTransaction.is_taken_away
            )
            .join(
                ClientTransaction,
                ClientPaymentEvent.transaction_id == ClientTransaction.id
            )
            .where(and_(*conditions))
            .order_by(ClientPaymentEvent.created_at.asc())
            .limit(limit)
        )

        result = await session.execute(query)

        export_data = []
        for row in result:
            export_data.append({
                'id': row.id,
                'transaction_id': row.transaction_id,
                'payment_provider': row.payment_provider or 'cash',
                'amount': float(row.amount),
                'admin_id': row.approved_by_admin_id,
                'created_at': row.created_at,
                'is_taken_away': row.is_taken_away
            })

        return export_data

    @staticmethod
    async def get_totals_by_client(
        session: AsyncSession,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        include_taken_away: bool = False,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get payment totals grouped by client.

        Joins with client_transaction_data to get client_code.

        IMPORTANT: By default, only includes payments for cargo NOT taken away.

        Args:
            session: Database session
            start_date: Start date (Tashkent calendar)
            end_date: End date (Tashkent calendar)
            include_taken_away: If True, include all payments. If False (default), only is_taken_away=FALSE.
            limit: Maximum clients to return

        Returns:
            List of client payment totals
        """
        conditions = []

        if start_date:
            start_utc, _ = tashkent_date_to_utc_range(start_date)
            conditions.append(ClientPaymentEvent.created_at >= start_utc)

        if end_date:
            _, end_utc = tashkent_date_to_utc_range(end_date)
            conditions.append(ClientPaymentEvent.created_at <= end_utc)

        # CRITICAL: Filter by is_taken_away=FALSE for revenue calculation
        if not include_taken_away:
            conditions.append(ClientTransaction.is_taken_away == False)

        # Filter out WALLET_ADJ pseudo-transactions
        conditions.append(~ClientTransaction.reys.like("WALLET_ADJ:%"))

        query = (
            select(
                ClientTransaction.client_code,
                ClientPaymentEvent.payment_provider,
                func.coalesce(func.sum(ClientPaymentEvent.amount), 0).label('total_amount'),
                func.count(ClientPaymentEvent.id).label('payment_count'),
                func.min(ClientPaymentEvent.created_at).label('first_payment'),
                func.max(ClientPaymentEvent.created_at).label('last_payment')
            )
            .join(
                ClientTransaction,
                ClientPaymentEvent.transaction_id == ClientTransaction.id
            )
            .group_by(ClientTransaction.client_code, ClientPaymentEvent.payment_provider)
            .order_by(func.sum(ClientPaymentEvent.amount).desc())
        )

        if conditions:
            query = query.where(and_(*conditions))

        # Note: We don't limit here because we need to aggregate per client
        result = await session.execute(query)

        # Aggregate by client
        client_data: Dict[str, Dict] = {}
        for row in result:
            client_code = row.client_code
            if client_code not in client_data:
                client_data[client_code] = {
                    'client_code': client_code,
                    'providers': {'cash': 0, 'click': 0, 'payme': 0, 'card': 0},
                    'counts': {'cash': 0, 'click': 0, 'payme': 0, 'card': 0},
                    'first_payment': row.first_payment,
                    'last_payment': row.last_payment,
                    'total_transactions': 0
                }

            provider = row.payment_provider or 'cash'
            if provider in client_data[client_code]['providers']:
                client_data[client_code]['providers'][provider] = float(row.total_amount or 0)
                client_data[client_code]['counts'][provider] = row.payment_count or 0
                client_data[client_code]['total_transactions'] += row.payment_count or 0

            # Update date ranges
            if row.first_payment < client_data[client_code]['first_payment']:
                client_data[client_code]['first_payment'] = row.first_payment
            if row.last_payment > client_data[client_code]['last_payment']:
                client_data[client_code]['last_payment'] = row.last_payment

        # Convert to list and sort by total
        clients = list(client_data.values())
        clients.sort(
            key=lambda x: sum(x['providers'].values()),
            reverse=True
        )

        return clients[:limit]

    @staticmethod
    async def get_totals_by_flight(
        session: AsyncSession,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        include_taken_away: bool = False,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get payment totals grouped by flight (reys).

        Joins with client_transaction_data to get reys (flight name).

        IMPORTANT: By default, only includes payments for cargo NOT taken away.

        Args:
            session: Database session
            start_date: Start date (Tashkent calendar)
            end_date: End date (Tashkent calendar)
            include_taken_away: If True, include all payments. If False (default), only is_taken_away=FALSE.
            limit: Maximum flights to return

        Returns:
            List of flight payment totals
        """
        conditions = [ClientTransaction.reys.isnot(None)]

        if start_date:
            start_utc, _ = tashkent_date_to_utc_range(start_date)
            conditions.append(ClientPaymentEvent.created_at >= start_utc)

        if end_date:
            _, end_utc = tashkent_date_to_utc_range(end_date)
            conditions.append(ClientPaymentEvent.created_at <= end_utc)

        # CRITICAL: Filter by is_taken_away=FALSE for revenue calculation
        if not include_taken_away:
            conditions.append(ClientTransaction.is_taken_away == False)
            
        # Filter out WALLET_ADJ pseudo-transactions
        conditions.append(~ClientTransaction.reys.like("WALLET_ADJ:%"))

        query = (
            select(
                ClientTransaction.reys.label('flight_name'),
                ClientPaymentEvent.payment_provider,
                func.coalesce(func.sum(ClientPaymentEvent.amount), 0).label('total_amount'),
                func.count(ClientPaymentEvent.id).label('payment_count'),
                func.count(func.distinct(ClientTransaction.client_code)).label('unique_clients')
            )
            .join(
                ClientTransaction,
                ClientPaymentEvent.transaction_id == ClientTransaction.id
            )
            .where(and_(*conditions))
            .group_by(ClientTransaction.reys, ClientPaymentEvent.payment_provider)
            .order_by(func.sum(ClientPaymentEvent.amount).desc())
        )

        result = await session.execute(query)

        # Aggregate by flight
        flight_data: Dict[str, Dict] = {}
        for row in result:
            flight_name = row.flight_name
            if flight_name not in flight_data:
                flight_data[flight_name] = {
                    'flight_name': flight_name,
                    'providers': {'cash': 0, 'click': 0, 'payme': 0, 'card': 0},
                    'counts': {'cash': 0, 'click': 0, 'payme': 0, 'card': 0},
                    'unique_clients': 0,
                    'total_transactions': 0
                }

            provider = row.payment_provider or 'cash'
            if provider in flight_data[flight_name]['providers']:
                flight_data[flight_name]['providers'][provider] = float(row.total_amount or 0)
                flight_data[flight_name]['counts'][provider] = row.payment_count or 0
                flight_data[flight_name]['total_transactions'] += row.payment_count or 0

            # Unique clients (approximate - may have some overlap across providers)
            flight_data[flight_name]['unique_clients'] = max(
                flight_data[flight_name]['unique_clients'],
                row.unique_clients or 0
            )

        # Convert to list and sort by total
        flights = list(flight_data.values())
        flights.sort(
            key=lambda x: sum(x['providers'].values()),
            reverse=True
        )

        return flights[:limit]

    @staticmethod
    async def count_payments_in_period(
        session: AsyncSession,
        start_date: date,
        end_date: date,
        include_taken_away: bool = False
    ) -> int:
        """
        Count total payment events in a period.

        IMPORTANT: By default, only counts payments for cargo NOT taken away.

        Args:
            session: Database session
            start_date: Start date (Tashkent calendar)
            end_date: End date (Tashkent calendar)
            include_taken_away: If True, include all payments. If False (default), only is_taken_away=FALSE.

        Returns:
            Number of payment events
        """
        start_utc, _ = tashkent_date_to_utc_range(start_date)
        _, end_utc = tashkent_date_to_utc_range(end_date)

        conditions = [
            ClientPaymentEvent.created_at >= start_utc,
            ClientPaymentEvent.created_at <= end_utc
        ]

        # CRITICAL: Filter by is_taken_away=FALSE for revenue calculation
        if not include_taken_away:
            conditions.append(ClientTransaction.is_taken_away == False)

        # Filter out WALLET_ADJ pseudo-transactions
        conditions.append(~ClientTransaction.reys.like("WALLET_ADJ:%"))

        result = await session.execute(
            select(func.count(ClientPaymentEvent.id))
            .join(
                ClientTransaction,
                ClientPaymentEvent.transaction_id == ClientTransaction.id
            )
            .where(and_(*conditions))
        )

        return result.scalar_one() or 0
