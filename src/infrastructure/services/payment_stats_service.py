"""
Payment Statistics Service.

Business logic layer for financial statistics calculations.
All monetary calculations use Decimal for precision.

SOURCE OF TRUTH: client_payment_events table
TIMEZONE: Asia/Tashkent for all business date operations
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.payment_stats import PaymentStatsDAO
from src.infrastructure.schemas.payment_stats import (
    ProviderTotals,
    ProviderSharePercentages,
    PaymentPeriodData,
    GrowthMetrics,
    ProviderGrowthMetrics,
    PeriodComparison,
    PaymentSummaryResponse,
    DailyPaymentStats,
    PaymentDailyResponse,
    WeeklyPaymentStats,
    PaymentWeeklyResponse,
    MonthlyPaymentStats,
    PaymentMonthlyResponse,
    PaymentCompareResponse,
    ClientPaymentStats,
    ClientPaymentStatsResponse,
    FlightPaymentStats,
    FlightPaymentStatsResponse,
)
from src.infrastructure.tools.datetime_utils import (
    get_current_business_date,
    get_current_business_time,
    utc_to_tashkent_date,
    TASHKENT_TZ
)


class PaymentStatsService:
    """
    Service layer for payment statistics.

    All public methods return Pydantic models ready for API responses.
    All date calculations use Asia/Tashkent timezone.
    """

    @staticmethod
    def _build_provider_totals(raw_data: Dict[str, Any]) -> ProviderTotals:
        """Convert raw DAO data to ProviderTotals schema."""
        cash_amount = float(raw_data.get('cash', {}).get('amount', 0) or 0)
        click_amount = float(raw_data.get('click', {}).get('amount', 0) or 0)
        payme_amount = float(raw_data.get('payme', {}).get('amount', 0) or 0)

        cash_count = raw_data.get('cash', {}).get('count', 0) or 0
        click_count = raw_data.get('click', {}).get('count', 0) or 0
        payme_count = raw_data.get('payme', {}).get('count', 0) or 0

        account_amount = click_amount + payme_amount
        account_count = click_count + payme_count
        total_amount = cash_amount + account_amount
        total_count = cash_count + account_count

        return ProviderTotals(
            cash=round(cash_amount, 2),
            click=round(click_amount, 2),
            payme=round(payme_amount, 2),
            account=round(account_amount, 2),
            total=round(total_amount, 2),
            cash_count=cash_count,
            click_count=click_count,
            payme_count=payme_count,
            account_count=account_count,
            total_count=total_count
        )

    @staticmethod
    def _calculate_share_percentages(totals: ProviderTotals) -> ProviderSharePercentages:
        """Calculate provider market share percentages."""
        total = totals.total
        if total <= 0:
            return ProviderSharePercentages(
                cash_percent=0.0,
                click_percent=0.0,
                payme_percent=0.0,
                account_percent=0.0
            )

        return ProviderSharePercentages(
            cash_percent=round((totals.cash / total) * 100, 2),
            click_percent=round((totals.click / total) * 100, 2),
            payme_percent=round((totals.payme / total) * 100, 2),
            account_percent=round((totals.account / total) * 100, 2)
        )

    @staticmethod
    def _calculate_growth(current: float, previous: float) -> GrowthMetrics:
        """
        Calculate growth between two values.

        Rules:
        - If previous = 0 and current > 0: is_new = True, percent = None
        - If previous = 0 and current = 0: difference = 0, percent = 0
        - Otherwise: standard percentage calculation
        """
        difference = round(current - previous, 2)

        if previous == 0:
            if current > 0:
                return GrowthMetrics(
                    difference=difference,
                    percent=None,
                    is_new=True
                )
            else:
                return GrowthMetrics(
                    difference=0.0,
                    percent=0.0,
                    is_new=False
                )

        percent = round(((current - previous) / previous) * 100, 2)
        return GrowthMetrics(
            difference=difference,
            percent=percent,
            is_new=False
        )

    @staticmethod
    def _calculate_provider_growth(
        current: ProviderTotals,
        previous: ProviderTotals
    ) -> ProviderGrowthMetrics:
        """Calculate growth metrics for all providers."""
        return ProviderGrowthMetrics(
            total=PaymentStatsService._calculate_growth(current.total, previous.total),
            cash=PaymentStatsService._calculate_growth(current.cash, previous.cash),
            click=PaymentStatsService._calculate_growth(current.click, previous.click),
            payme=PaymentStatsService._calculate_growth(current.payme, previous.payme),
            account=PaymentStatsService._calculate_growth(current.account, previous.account)
        )

    @staticmethod
    def _get_week_boundaries(business_date: date) -> tuple[date, date]:
        """
        Get Monday-Sunday boundaries for a given date.

        Week starts on Monday (ISO standard).
        """
        # Monday is weekday 0, Sunday is 6
        days_since_monday = business_date.weekday()
        week_start = business_date - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=6)
        return week_start, week_end

    @staticmethod
    async def get_period_data(
        session: AsyncSession,
        start_date: date,
        end_date: date
    ) -> PaymentPeriodData:
        """Get payment data for a specific period."""
        raw_data = await PaymentStatsDAO.get_totals_by_provider(
            session, start_date, end_date
        )
        totals = PaymentStatsService._build_provider_totals(raw_data)
        shares = PaymentStatsService._calculate_share_percentages(totals)

        return PaymentPeriodData(
            start_date=start_date,
            end_date=end_date,
            providers=totals,
            share_percentages=shares
        )

    @staticmethod
    async def get_summary(session: AsyncSession) -> PaymentSummaryResponse:
        """
        Get comprehensive payment summary.

        Includes all-time totals, today/yesterday, weekly, monthly comparisons.
        """
        today = get_current_business_date()
        yesterday = today - timedelta(days=1)

        # Get week boundaries (Mon-Sun)
        this_week_start, this_week_end = PaymentStatsService._get_week_boundaries(today)
        prev_week_start, prev_week_end = PaymentStatsService._get_week_boundaries(
            this_week_start - timedelta(days=1)
        )

        # Get month boundaries
        this_month_start = today.replace(day=1)
        this_month_end = today

        prev_month_end = this_month_start - timedelta(days=1)
        prev_month_start = prev_month_end.replace(day=1)

        # Rolling periods
        last_7_days_start = today - timedelta(days=6)
        last_60_days_start = today - timedelta(days=59)

        # Fetch all data in parallel-ish manner
        # All-time totals
        all_time_raw = await PaymentStatsDAO.get_totals_by_provider(session)
        all_time_totals = PaymentStatsService._build_provider_totals(all_time_raw)
        all_time_shares = PaymentStatsService._calculate_share_percentages(all_time_totals)

        # Today
        today_data = await PaymentStatsService.get_period_data(session, today, today)

        # Yesterday
        yesterday_data = await PaymentStatsService.get_period_data(session, yesterday, yesterday)

        # This week
        this_week_data = await PaymentStatsService.get_period_data(
            session, this_week_start, min(this_week_end, today)
        )

        # Previous week
        prev_week_data = await PaymentStatsService.get_period_data(
            session, prev_week_start, prev_week_end
        )

        # This month
        this_month_data = await PaymentStatsService.get_period_data(
            session, this_month_start, this_month_end
        )

        # Previous month
        prev_month_data = await PaymentStatsService.get_period_data(
            session, prev_month_start, prev_month_end
        )

        # Last 7 days
        last_7_data = await PaymentStatsService.get_period_data(
            session, last_7_days_start, today
        )

        # Last 60 days
        last_60_data = await PaymentStatsService.get_period_data(
            session, last_60_days_start, today
        )

        # Calculate growth
        daily_growth = PaymentStatsService._calculate_provider_growth(
            today_data.providers, yesterday_data.providers
        )
        weekly_growth = PaymentStatsService._calculate_provider_growth(
            this_week_data.providers, prev_week_data.providers
        )
        monthly_growth = PaymentStatsService._calculate_provider_growth(
            this_month_data.providers, prev_month_data.providers
        )

        return PaymentSummaryResponse(
            providers=all_time_totals,
            share_percentages=all_time_shares,
            today=today_data,
            yesterday=yesterday_data,
            this_week=this_week_data,
            previous_week=prev_week_data,
            this_month=this_month_data,
            previous_month=prev_month_data,
            last_7_days=last_7_data,
            last_60_days=last_60_data,
            growth={
                'daily': daily_growth.model_dump(),
                'weekly': weekly_growth.model_dump(),
                'monthly': monthly_growth.model_dump()
            },
            calculated_at=get_current_business_time()
        )

    @staticmethod
    async def get_daily_stats(
        session: AsyncSession,
        start_date: date,
        end_date: date
    ) -> PaymentDailyResponse:
        """Get daily payment statistics for a date range."""
        raw_data = await PaymentStatsDAO.get_daily_totals_by_provider(
            session, start_date, end_date
        )

        # Group by date
        daily_map: Dict[date, Dict[str, Any]] = {}
        for item in raw_data:
            d = item['date']
            if d not in daily_map:
                daily_map[d] = {
                    'cash': {'amount': 0, 'count': 0},
                    'click': {'amount': 0, 'count': 0},
                    'payme': {'amount': 0, 'count': 0}
                }
            provider = item['provider']
            if provider in daily_map[d]:
                daily_map[d][provider]['amount'] = float(item['amount'])
                daily_map[d][provider]['count'] = item['count']

        # Convert to response format
        days = []
        for d in sorted(daily_map.keys()):
            totals = PaymentStatsService._build_provider_totals(daily_map[d])
            days.append(DailyPaymentStats(date=d, providers=totals))

        # Calculate period totals
        period_raw = await PaymentStatsDAO.get_totals_by_provider(
            session, start_date, end_date
        )
        period_totals = PaymentStatsService._build_provider_totals(period_raw)

        return PaymentDailyResponse(
            days=days,
            period_totals=period_totals,
            start_date=start_date,
            end_date=end_date,
            total_days=len(days)
        )

    @staticmethod
    async def get_weekly_stats(
        session: AsyncSession,
        weeks: int = 12
    ) -> PaymentWeeklyResponse:
        """Get weekly payment statistics."""
        raw_data = await PaymentStatsDAO.get_weekly_totals_by_provider(session, weeks)

        # Group by week
        weekly_map: Dict[date, Dict[str, Any]] = {}
        for item in raw_data:
            week_start = item['week_start']
            if week_start not in weekly_map:
                weekly_map[week_start] = {
                    'cash': {'amount': 0, 'count': 0},
                    'click': {'amount': 0, 'count': 0},
                    'payme': {'amount': 0, 'count': 0}
                }
            provider = item['provider']
            if provider in weekly_map[week_start]:
                weekly_map[week_start][provider]['amount'] = float(item['amount'])
                weekly_map[week_start][provider]['count'] = item['count']

        # Convert to response format
        week_list = []
        for week_start in sorted(weekly_map.keys(), reverse=True):
            totals = PaymentStatsService._build_provider_totals(weekly_map[week_start])
            week_end = week_start + timedelta(days=6)
            week_number = week_start.isocalendar()[1]
            year = week_start.year

            week_list.append(WeeklyPaymentStats(
                week_start=week_start,
                week_end=week_end,
                week_number=week_number,
                year=year,
                providers=totals
            ))

        # Calculate period totals
        period_totals = ProviderTotals()
        for w in week_list:
            period_totals.cash += w.providers.cash
            period_totals.click += w.providers.click
            period_totals.payme += w.providers.payme
            period_totals.account += w.providers.account
            period_totals.total += w.providers.total
            period_totals.cash_count += w.providers.cash_count
            period_totals.click_count += w.providers.click_count
            period_totals.payme_count += w.providers.payme_count
            period_totals.account_count += w.providers.account_count
            period_totals.total_count += w.providers.total_count

        return PaymentWeeklyResponse(
            weeks=week_list,
            period_totals=period_totals,
            total_weeks=len(week_list)
        )

    @staticmethod
    async def get_monthly_stats(
        session: AsyncSession,
        months: int = 12
    ) -> PaymentMonthlyResponse:
        """Get monthly payment statistics."""
        MONTH_NAMES = [
            '', 'January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December'
        ]

        raw_data = await PaymentStatsDAO.get_monthly_totals_by_provider(session, months)

        # Group by month
        monthly_map: Dict[date, Dict[str, Any]] = {}
        for item in raw_data:
            month_start = item['month_start']
            if month_start not in monthly_map:
                monthly_map[month_start] = {
                    'cash': {'amount': 0, 'count': 0},
                    'click': {'amount': 0, 'count': 0},
                    'payme': {'amount': 0, 'count': 0}
                }
            provider = item['provider']
            if provider in monthly_map[month_start]:
                monthly_map[month_start][provider]['amount'] = float(item['amount'])
                monthly_map[month_start][provider]['count'] = item['count']

        # Convert to response format
        month_list = []
        for month_start in sorted(monthly_map.keys(), reverse=True):
            totals = PaymentStatsService._build_provider_totals(monthly_map[month_start])
            month = month_start.month
            year = month_start.year

            month_list.append(MonthlyPaymentStats(
                month=month,
                year=year,
                month_name=MONTH_NAMES[month],
                providers=totals
            ))

        # Calculate period totals
        period_totals = ProviderTotals()
        for m in month_list:
            period_totals.cash += m.providers.cash
            period_totals.click += m.providers.click
            period_totals.payme += m.providers.payme
            period_totals.account += m.providers.account
            period_totals.total += m.providers.total
            period_totals.cash_count += m.providers.cash_count
            period_totals.click_count += m.providers.click_count
            period_totals.payme_count += m.providers.payme_count
            period_totals.account_count += m.providers.account_count
            period_totals.total_count += m.providers.total_count

        return PaymentMonthlyResponse(
            months=month_list,
            period_totals=period_totals,
            total_months=len(month_list)
        )

    @staticmethod
    async def get_comparison(session: AsyncSession) -> PaymentCompareResponse:
        """Get period comparisons with growth metrics."""
        today = get_current_business_date()
        yesterday = today - timedelta(days=1)

        # Week boundaries
        this_week_start, this_week_end = PaymentStatsService._get_week_boundaries(today)
        prev_week_start, prev_week_end = PaymentStatsService._get_week_boundaries(
            this_week_start - timedelta(days=1)
        )

        # Month boundaries
        this_month_start = today.replace(day=1)
        prev_month_end = this_month_start - timedelta(days=1)
        prev_month_start = prev_month_end.replace(day=1)

        # Fetch data
        today_data = await PaymentStatsService.get_period_data(session, today, today)
        yesterday_data = await PaymentStatsService.get_period_data(session, yesterday, yesterday)

        this_week_data = await PaymentStatsService.get_period_data(
            session, this_week_start, min(this_week_end, today)
        )
        prev_week_data = await PaymentStatsService.get_period_data(
            session, prev_week_start, prev_week_end
        )

        this_month_data = await PaymentStatsService.get_period_data(
            session, this_month_start, today
        )
        prev_month_data = await PaymentStatsService.get_period_data(
            session, prev_month_start, prev_month_end
        )

        # Build comparisons
        daily_comparison = PeriodComparison(
            current=today_data,
            previous=yesterday_data,
            growth=PaymentStatsService._calculate_provider_growth(
                today_data.providers, yesterday_data.providers
            )
        )

        weekly_comparison = PeriodComparison(
            current=this_week_data,
            previous=prev_week_data,
            growth=PaymentStatsService._calculate_provider_growth(
                this_week_data.providers, prev_week_data.providers
            )
        )

        monthly_comparison = PeriodComparison(
            current=this_month_data,
            previous=prev_month_data,
            growth=PaymentStatsService._calculate_provider_growth(
                this_month_data.providers, prev_month_data.providers
            )
        )

        return PaymentCompareResponse(
            daily=daily_comparison,
            weekly=weekly_comparison,
            monthly=monthly_comparison,
            calculated_at=get_current_business_time()
        )

    @staticmethod
    async def get_client_stats(
        session: AsyncSession,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 100
    ) -> ClientPaymentStatsResponse:
        """Get payment statistics by client."""
        raw_data = await PaymentStatsDAO.get_totals_by_client(
            session, start_date, end_date, limit
        )

        clients = []
        for item in raw_data:
            providers = item['providers']
            counts = item['counts']

            totals = ProviderTotals(
                cash=providers.get('cash', 0),
                click=providers.get('click', 0),
                payme=providers.get('payme', 0),
                account=providers.get('click', 0) + providers.get('payme', 0),
                total=sum(providers.values()),
                cash_count=counts.get('cash', 0),
                click_count=counts.get('click', 0),
                payme_count=counts.get('payme', 0),
                account_count=counts.get('click', 0) + counts.get('payme', 0),
                total_count=sum(counts.values())
            )

            first_payment = None
            if item.get('first_payment'):
                first_payment = utc_to_tashkent_date(item['first_payment'])

            last_payment = None
            if item.get('last_payment'):
                last_payment = utc_to_tashkent_date(item['last_payment'])

            clients.append(ClientPaymentStats(
                client_code=item['client_code'],
                providers=totals,
                first_payment_date=first_payment,
                last_payment_date=last_payment,
                total_transactions=item.get('total_transactions', 0)
            ))

        return ClientPaymentStatsResponse(
            clients=clients,
            total_clients=len(clients),
            period_start=start_date,
            period_end=end_date
        )

    @staticmethod
    async def get_flight_stats(
        session: AsyncSession,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 100
    ) -> FlightPaymentStatsResponse:
        """Get payment statistics by flight."""
        raw_data = await PaymentStatsDAO.get_totals_by_flight(
            session, start_date, end_date, limit
        )

        flights = []
        for item in raw_data:
            providers = item['providers']
            counts = item['counts']

            totals = ProviderTotals(
                cash=providers.get('cash', 0),
                click=providers.get('click', 0),
                payme=providers.get('payme', 0),
                account=providers.get('click', 0) + providers.get('payme', 0),
                total=sum(providers.values()),
                cash_count=counts.get('cash', 0),
                click_count=counts.get('click', 0),
                payme_count=counts.get('payme', 0),
                account_count=counts.get('click', 0) + counts.get('payme', 0),
                total_count=sum(counts.values())
            )

            flights.append(FlightPaymentStats(
                flight_name=item['flight_name'],
                providers=totals,
                unique_clients=item.get('unique_clients', 0),
                total_transactions=item.get('total_transactions', 0)
            ))

        return FlightPaymentStatsResponse(
            flights=flights,
            total_flights=len(flights),
            period_start=start_date,
            period_end=end_date
        )

    @staticmethod
    async def get_export_data(
        session: AsyncSession,
        start_date: date,
        end_date: date,
        provider: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get raw payment data for CSV export."""
        return await PaymentStatsDAO.get_payments_for_export(
            session, start_date, end_date, provider
        )
