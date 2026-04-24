"""Statistics API schemas."""
from datetime import date
from typing import Optional, List
from pydantic import BaseModel, Field


class DailyClientStats(BaseModel):
    """Daily client statistics response."""
    stat_date: date
    registrations_count: int
    approvals_count: int
    logins_count: int
    active_clients_count: int


class DailyCargoStats(BaseModel):
    """Daily cargo statistics response."""
    stat_date: date
    flight_name: Optional[str] = None
    uploads_count: int
    unique_clients_count: int
    total_photos_count: int
    total_weight_kg: Optional[float] = None
    avg_weight_kg: Optional[float] = None


class DailyPaymentStats(BaseModel):
    """Daily payment statistics response."""
    stat_date: date
    payment_type: Optional[str] = None
    approvals_count: int
    total_amount: float
    full_payments_count: int
    partial_payments_count: int
    full_payments_amount: float
    partial_payments_amount: float
    avg_amount: Optional[float] = None


class StatsOverviewResponse(BaseModel):
    """Overview statistics response."""
    total_clients: int = Field(..., description="Total number of active clients")
    total_registrations: int = Field(..., description="Total registrations in date range")
    total_approvals: int = Field(..., description="Total approvals in date range")
    total_cargo_uploads: int = Field(..., description="Total cargo uploads in date range")
    total_payment_amount: float = Field(..., description="Total payment amount in date range")
    total_payments_count: int = Field(..., description="Total number of payments in date range")
    date_range_start: date
    date_range_end: date


class StatsClientsResponse(BaseModel):
    """Client statistics response."""
    stats: List[DailyClientStats]
    total: int
    start_date: date
    end_date: date


class StatsCargoResponse(BaseModel):
    """Cargo statistics response."""
    stats: List[DailyCargoStats]
    total: int
    start_date: date
    end_date: date
    flight_name: Optional[str] = Field(None, description="Filtered flight name (if specified)")


class StatsPaymentsResponse(BaseModel):
    """Payment statistics response."""
    stats: List[DailyPaymentStats]
    total: int
    start_date: date
    end_date: date
    payment_type: Optional[str] = Field(None, description="Filtered payment type (if specified)")


class SystemStatsResponse(BaseModel):
    """System statistics response."""
    total_api_requests: int = Field(..., description="Total API requests in date range")
    average_response_time_ms: float = Field(..., description="Average response time in milliseconds")
    error_rate: float = Field(..., description="Error rate (percentage)")
    total_errors: int = Field(..., description="Total number of errors")
    most_used_endpoints: List[dict] = Field(..., description="List of most used endpoints with counts")
    date_range_start: date
    date_range_end: date


# ============================================================================
# ENHANCED STATISTICS SCHEMAS - PERIOD COMPARISONS & TRENDS
# ============================================================================


class PeriodData(BaseModel):
    """Data for a specific time period."""
    count: int = Field(..., description="Count for this period")
    start_date: date = Field(..., description="Period start date")
    end_date: date = Field(..., description="Period end date")


class PeriodComparison(BaseModel):
    """Comparison between current and previous period."""
    current_period: PeriodData = Field(..., description="Current period data")
    previous_period: PeriodData = Field(..., description="Previous period data")
    delta_absolute: int = Field(..., description="Absolute difference (current - previous)")
    delta_percent: float = Field(..., description="Percentage change (rounded to 2 decimals)")


class TodayYesterdayComparison(BaseModel):
    """Today vs Yesterday comparison for any metric."""
    today_count: int = Field(..., description="Today's count")
    yesterday_count: int = Field(..., description="Yesterday's count")
    difference: int = Field(..., description="Absolute difference (today - yesterday)")
    percent_change: float = Field(..., description="Percentage change (rounded to 2 decimals)")
    is_growth: bool = Field(..., description="True if today > yesterday")
    today_date: date = Field(..., description="Today's date")
    yesterday_date: date = Field(..., description="Yesterday's date")


class RegistrationStatsResponse(BaseModel):
    """
    User registration statistics with period comparisons.

    Provides registration counts for multiple time ranges with
    comparison to previous equivalent period.
    """
    # TODAY VS YESTERDAY - clear daily comparison
    today_vs_yesterday: TodayYesterdayComparison = Field(
        ...,
        description="Today vs Yesterday registrations comparison"
    )

    # Daily registrations (last 24 hours vs previous 24 hours)
    daily: PeriodComparison = Field(..., description="Daily registrations comparison")

    # Weekly registrations (last 7 days vs previous 7 days)
    weekly: PeriodComparison = Field(..., description="Weekly registrations comparison")

    # Monthly registrations (last 30 days vs previous 30 days)
    monthly: PeriodComparison = Field(..., description="Monthly registrations comparison")

    # Current calendar month vs previous calendar month
    current_month_vs_previous: PeriodComparison = Field(
        ...,
        description="Current calendar month vs previous calendar month"
    )

    # Total lifetime registrations (all time)
    total_lifetime: int = Field(..., description="Total registrations since bot launch")


class ActivityMetrics(BaseModel):
    """Client activity metrics for a period."""
    active_clients: int = Field(
        ...,
        description="Clients who performed at least 1 action (cargo upload or payment) in period"
    )
    passive_clients: int = Field(
        ...,
        description="Clients registered but no actions in period"
    )
    total_registered: int = Field(
        ...,
        description="Total registered clients as of period end"
    )
    activity_rate: float = Field(
        ...,
        description="Percentage of registered clients who are active (rounded to 2 decimals)"
    )


class TodayYesterdayActivityComparison(BaseModel):
    """Today vs Yesterday comparison for client activity."""
    today_active: int = Field(..., description="Active clients today")
    yesterday_active: int = Field(..., description="Active clients yesterday")
    difference: int = Field(..., description="Absolute difference")
    percent_change: float = Field(..., description="Percentage change")
    is_growth: bool = Field(..., description="True if today > yesterday")
    today_date: date
    yesterday_date: date


class ClientActivityStatsResponse(BaseModel):
    """
    Client activity statistics.

    Defines 'active' as: performed at least 1 cargo upload OR payment in the period.
    Defines 'passive' as: registered but no cargo/payment activity in the period.
    """
    # TODAY VS YESTERDAY
    today_vs_yesterday: Optional[TodayYesterdayActivityComparison] = Field(
        None,
        description="Today vs Yesterday active clients comparison"
    )

    # Last 7 days activity
    last_7_days: ActivityMetrics = Field(..., description="Activity metrics for last 7 days")

    # Last 30 days activity
    last_30_days: ActivityMetrics = Field(..., description="Activity metrics for last 30 days")

    # Last 60 days activity
    last_60_days: ActivityMetrics = Field(..., description="Activity metrics for last 60 days")

    # Metadata
    calculated_at: date = Field(..., description="Date when statistics were calculated")


class CargoTrendData(BaseModel):
    """Cargo statistics for a specific period."""
    cargo_count: int = Field(..., description="Number of cargo uploads")
    unique_clients: int = Field(..., description="Number of unique clients who uploaded cargo")
    total_weight_kg: Optional[float] = Field(None, description="Total weight in kilograms")
    avg_weight_kg: Optional[float] = Field(None, description="Average weight per cargo")
    start_date: date = Field(..., description="Period start date")
    end_date: date = Field(..., description="Period end date")


class CargoStatsResponse(BaseModel):
    """
    Cargo/Order statistics with trends.

    Provides cargo upload counts with period comparisons.
    """
    # TODAY VS YESTERDAY
    today_vs_yesterday: Optional[TodayYesterdayComparison] = Field(
        None,
        description="Today vs Yesterday cargo uploads comparison"
    )

    # Weekly cargo (last 7 days vs previous 7 days)
    weekly_comparison: PeriodComparison = Field(..., description="Weekly cargo comparison")
    weekly_details: CargoTrendData = Field(..., description="Detailed stats for last 7 days")

    # Monthly cargo (last 30 days vs previous 30 days)
    monthly_comparison: PeriodComparison = Field(..., description="Monthly cargo comparison")
    monthly_details: CargoTrendData = Field(..., description="Detailed stats for last 30 days")

    # Current month vs previous month
    current_month_vs_previous: PeriodComparison = Field(
        ...,
        description="Current calendar month vs previous calendar month"
    )

    # Total lifetime cargo
    total_lifetime: int = Field(..., description="Total cargo uploads since bot launch")


class RevenueData(BaseModel):
    """Revenue data for a specific period."""
    total_revenue: float = Field(..., description="Total revenue in this period")
    payment_count: int = Field(..., description="Number of payment events")
    avg_payment: float = Field(..., description="Average payment amount")
    full_payments_count: int = Field(..., description="Number of full payments")
    partial_payments_count: int = Field(..., description="Number of partial payments")
    start_date: date
    end_date: date


class RevenuePeriodComparison(BaseModel):
    """Revenue comparison between periods."""
    current_period: RevenueData
    previous_period: RevenueData
    delta_absolute: float = Field(..., description="Absolute revenue difference")
    delta_percent: float = Field(..., description="Percentage revenue change (rounded to 2 decimals)")


class TodayYesterdayRevenueComparison(BaseModel):
    """Today vs Yesterday revenue comparison."""
    today_revenue: float = Field(..., description="Today's revenue")
    yesterday_revenue: float = Field(..., description="Yesterday's revenue")
    today_count: int = Field(..., description="Today's payment count")
    yesterday_count: int = Field(..., description="Yesterday's payment count")
    difference: float = Field(..., description="Revenue difference")
    percent_change: float = Field(..., description="Percentage change")
    is_growth: bool = Field(..., description="True if today > yesterday")
    today_date: date
    yesterday_date: date


class RevenueStatsResponse(BaseModel):
    """
    Revenue statistics with period comparisons.

    Calculates revenue from client_payment_events table (source of truth).
    IMPORTANT: Only includes revenue for cargo NOT taken away (is_taken_away=FALSE).
    """
    # TODAY VS YESTERDAY
    today_vs_yesterday: Optional[TodayYesterdayRevenueComparison] = Field(
        None,
        description="Today vs Yesterday revenue comparison"
    )

    # Weekly revenue (last 7 days vs previous 7 days)
    weekly: RevenuePeriodComparison = Field(..., description="Weekly revenue comparison")

    # Monthly revenue (last 30 days vs previous 30 days)
    monthly: RevenuePeriodComparison = Field(..., description="Monthly revenue comparison")

    # Current month vs previous month
    current_month_vs_previous: RevenuePeriodComparison = Field(
        ...,
        description="Current calendar month vs previous calendar month"
    )

    # Total lifetime revenue
    total_lifetime_revenue: float = Field(..., description="Total revenue since bot launch")
    total_lifetime_payments: int = Field(..., description="Total payment events since bot launch")
    avg_lifetime_payment: float = Field(..., description="Average payment amount (all time)")


class BotLifecycleStatsResponse(BaseModel):
    """
    Bot lifecycle statistics.

    Provides metrics from bot launch date to present.
    """
    # Bot launch information
    bot_launch_date: date = Field(
        ...,
        description="Date of first recorded event (earliest record in analytics_events or clients table)"
    )
    days_since_launch: int = Field(..., description="Number of days since bot launch")

    # Lifetime totals (all calculations from bot_launch_date onward)
    total_users: int = Field(..., description="Total registered users since launch")
    total_approved_clients: int = Field(..., description="Total approved clients (with client_code)")
    total_cargo_uploads: int = Field(..., description="Total cargo uploads since launch")
    total_payments: int = Field(..., description="Total payment events since launch")
    total_revenue: float = Field(..., description="Total revenue since launch")

    # Averages
    avg_users_per_day: float = Field(..., description="Average new registrations per day")
    avg_cargo_per_day: float = Field(..., description="Average cargo uploads per day")
    avg_revenue_per_day: float = Field(..., description="Average revenue per day")

    # Current state
    calculated_at: date = Field(..., description="Date when statistics were calculated")


# ============================================================================
# DOMAIN-SPECIFIC STATISTICS SCHEMAS - BUSINESS TERMINOLOGY
# ============================================================================


class CargoItemWarehouseStats(BaseModel):
    """
    Cargo item statistics for a specific warehouse.

    Business Context:
    - "Xitoy baza" (China warehouse) = checkin_status='pre'
    - "O'zbek baza" (Uzbekistan warehouse) = checkin_status='post'
    """
    warehouse_name: str = Field(..., description="Warehouse name: 'Xitoy baza' or 'O'zbek baza'")
    checkin_status: str = Field(..., description="Database status: 'pre' or 'post'")
    total_items: int = Field(..., description="Total cargo items in this warehouse")
    used_items: int = Field(..., description="Items marked as used")
    unused_items: int = Field(..., description="Items not yet used")
    total_weight_kg: Optional[float] = Field(None, description="Total weight in kg (nullable)")
    avg_weight_kg: Optional[float] = Field(None, description="Average weight per item in kg")
    total_declared_value: Optional[float] = Field(None, description="Total declared payment value")
    avg_declared_value: Optional[float] = Field(None, description="Average declared value per item")


class CargoItemsStatsResponse(BaseModel):
    """
    Comprehensive cargo items statistics with warehouse breakdown.

    Separates statistics between:
    - Xitoy baza (China warehouse, checkin_status='pre')
    - O'zbek baza (Uzbekistan warehouse, checkin_status='post')
    """
    xitoy_baza: CargoItemWarehouseStats = Field(..., description="China warehouse statistics")
    uzbek_baza: CargoItemWarehouseStats = Field(..., description="Uzbekistan warehouse statistics")
    combined_total: int = Field(..., description="Total items across both warehouses")
    calculated_at: date = Field(..., description="Calculation date")


class CargoItemsTrendData(BaseModel):
    """Cargo items trend data for a time period."""
    period_start: date
    period_end: date
    xitoy_count: int = Field(..., description="Items in China warehouse")
    uzbek_count: int = Field(..., description="Items in Uzbekistan warehouse")
    total_count: int = Field(..., description="Combined total")


class CargoItemsTrendsResponse(BaseModel):
    """
    Cargo items trends with period comparisons.

    Provides weekly and monthly trends separated by warehouse.
    """
    weekly_current: CargoItemsTrendData
    weekly_previous: CargoItemsTrendData
    weekly_delta_percent: float = Field(..., description="Percentage change week-over-week")

    monthly_current: CargoItemsTrendData
    monthly_previous: CargoItemsTrendData
    monthly_delta_percent: float = Field(..., description="Percentage change month-over-month")

    lifetime_stats: CargoItemsStatsResponse = Field(..., description="All-time statistics")


class FotoHisobotFlightStats(BaseModel):
    """Statistics for a specific flight in Foto Hisobot system."""
    flight_name: str = Field(..., description="Flight/batch name")
    total_uploads: int = Field(..., description="Total photo uploads for this flight")
    unique_clients: int = Field(..., description="Number of unique clients")
    total_photos: int = Field(..., description="Total number of photos (parsed from JSON)")
    total_weight_kg: Optional[float] = Field(None, description="Total cargo weight")
    avg_weight_kg: Optional[float] = Field(None, description="Average weight per upload")
    sent_count: int = Field(..., description="Number of reports sent to clients")
    unsent_count: int = Field(..., description="Number of reports not yet sent")


class FotoHisobotStatsResponse(BaseModel):
    """
    Foto Hisobot (flight_cargos) comprehensive statistics.

    Business Name: "Foto Hisobot" = Photo Report System
    Admin uploads cargo photos for clients.
    """
    total_uploads: int = Field(..., description="Total photo reports uploaded")
    total_photos: int = Field(..., description="Total photos across all uploads")
    unique_clients: int = Field(..., description="Number of unique clients with uploads")
    unique_flights: int = Field(..., description="Number of unique flights/batches")
    total_weight_kg: Optional[float] = Field(None, description="Total cargo weight")
    sent_count: int = Field(..., description="Reports sent to clients")
    unsent_count: int = Field(..., description="Reports not yet sent")

    # Top flights
    top_flights: List[FotoHisobotFlightStats] = Field(
        ...,
        description="Top 10 flights by upload count"
    )

    calculated_at: date


class FotoHisobotTrendsResponse(BaseModel):
    """
    Foto Hisobot trends with period comparisons.
    """
    daily_comparison: PeriodComparison
    weekly_comparison: PeriodComparison
    monthly_comparison: PeriodComparison
    current_month_vs_previous: PeriodComparison
    lifetime_total: int = Field(..., description="Total uploads since bot launch")


class DeliveryServiceStats(BaseModel):
    """Statistics for a specific delivery service."""
    delivery_type: str = Field(..., description="Delivery service name")
    total_requests: int = Field(..., description="Total requests")
    pending: int = Field(..., description="Pending requests")
    approved: int = Field(..., description="Approved requests")
    rejected: int = Field(..., description="Rejected requests")
    approval_rate: float = Field(..., description="Approval rate percentage")


class DeliveryRequestsStatsResponse(BaseModel):
    """
    Delivery requests statistics by service type.

    Service Types: uzpost, yandex, akb, bts
    """
    total_requests: int
    by_service: List[DeliveryServiceStats] = Field(..., description="Stats per service type")
    overall_approval_rate: float = Field(..., description="Overall approval rate percentage")
    calculated_at: date


class BroadcastStatsResponse(BaseModel):
    """
    Broadcast message statistics (admin messaging system).
    """
    total_broadcasts: int = Field(..., description="Total broadcast campaigns")
    completed_broadcasts: int = Field(..., description="Completed campaigns")
    total_messages_sent: int = Field(..., description="Total messages sent")
    total_failed: int = Field(..., description="Total failed sends")
    total_blocked: int = Field(..., description="Users who blocked bot")
    success_rate: float = Field(..., description="Success rate percentage")
    calculated_at: date


class ProviderBreakdown(BaseModel):
    """Payment provider breakdown for financial statistics."""
    cash: float = Field(0.0, description="Cash payment amount")
    click: float = Field(0.0, description="Click payment amount")
    payme: float = Field(0.0, description="Payme payment amount")
    account: float = Field(0.0, description="Account payments (click + payme)")
    total: float = Field(0.0, description="Total all providers")

    # Payment counts
    cash_count: int = Field(0, description="Number of cash payments")
    click_count: int = Field(0, description="Number of Click payments")
    payme_count: int = Field(0, description="Number of Payme payments")
    account_count: int = Field(0, description="Number of account payments")
    total_count: int = Field(0, description="Total payment count")


class ProviderSharePercent(BaseModel):
    """Provider market share percentages."""
    cash_percent: float = Field(0.0, description="Cash share %")
    click_percent: float = Field(0.0, description="Click share %")
    payme_percent: float = Field(0.0, description="Payme share %")
    account_percent: float = Field(0.0, description="Account share %")


class GrowthMetric(BaseModel):
    """Growth metric with is_new flag for division-by-zero safety."""
    difference: float = Field(..., description="Absolute difference")
    percent: Optional[float] = Field(None, description="Percentage change (null if is_new)")
    is_new: bool = Field(False, description="True if previous=0 and current>0")


class DailyComparisonStats(BaseModel):
    """Today vs Yesterday comparison with provider breakdown."""
    today: ProviderBreakdown
    yesterday: ProviderBreakdown
    growth: GrowthMetric


class GlobalDashboardStats(BaseModel):
    """
    Global aggregated statistics for main dashboard.

    Combines all core business metrics in one response.
    """
    # Client metrics
    total_registered_clients: int
    total_approved_clients: int
    active_clients_30_days: int

    # Revenue metrics
    total_lifetime_revenue: float
    revenue_this_month: float
    revenue_last_month: float
    revenue_growth_percent: float

    # Foto Hisobot metrics
    total_foto_hisobot_uploads: int
    foto_hisobot_this_month: int

    # Cargo items metrics
    total_cargo_items: int
    cargo_items_xitoy: int
    cargo_items_uzbek: int

    # Payment metrics
    total_payments: int
    payments_this_month: int

    # System metrics
    total_api_requests: int
    api_error_rate: float

    # Bot lifecycle
    bot_launch_date: date
    days_since_launch: int

    calculated_at: date

    # === NEW FIELDS (backward compatible) ===

    # Provider breakdown - all time
    provider_totals: Optional[ProviderBreakdown] = Field(
        None,
        description="Payment totals by provider (cash/click/payme)"
    )

    # Provider share percentages
    provider_share: Optional[ProviderSharePercent] = Field(
        None,
        description="Provider market share percentages"
    )

    # Today vs Yesterday comparison
    daily_comparison: Optional[DailyComparisonStats] = Field(
        None,
        description="Today vs Yesterday with growth metrics"
    )

    # This week provider breakdown
    this_week_providers: Optional[ProviderBreakdown] = Field(
        None,
        description="This week totals by provider"
    )

    # This month provider breakdown
    this_month_providers: Optional[ProviderBreakdown] = Field(
        None,
        description="This month totals by provider"
    )

    # Weekly growth
    weekly_growth: Optional[GrowthMetric] = Field(
        None,
        description="This week vs previous week growth"
    )

    # Monthly growth
    monthly_growth: Optional[GrowthMetric] = Field(
        None,
        description="This month vs previous month growth"
    )


class ChartDataPoint(BaseModel):
    """Single data point for chart visualization."""
    date: date
    value: float
    label: Optional[str] = None


class ChartDataSeries(BaseModel):
    """Chart data series with multiple points."""
    series_name: str
    data_points: List[ChartDataPoint]


class TimeSeriesChartResponse(BaseModel):
    """
    Chart-ready time series data.

    Format optimized for frontend chart libraries (Chart.js, Recharts, etc.)
    """
    chart_title: str
    series: List[ChartDataSeries]
    x_axis_label: str = "Date"
    y_axis_label: str
    period_start: date
    period_end: date

