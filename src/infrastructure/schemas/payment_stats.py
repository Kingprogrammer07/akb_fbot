"""
Payment Statistics API Schemas.

Enterprise-grade financial statistics schemas for payment provider analytics.
All monetary values use Decimal-compatible floats for accuracy.

SOURCE OF TRUTH: client_payment_events table
TIMEZONE: Asia/Tashkent for all business calculations
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field


# =============================================================================
# PROVIDER BREAKDOWN SCHEMAS
# =============================================================================


class ProviderTotals(BaseModel):
    """
    Payment totals broken down by provider.

    Providers:
    - cash: Physical cash payments
    - click: Click payment system
    - payme: Payme payment system
    - account: Combined click + payme (electronic/online)
    - total: All providers combined
    """
    cash: float = Field(0.0, description="Total cash payments (so'm)")
    click: float = Field(0.0, description="Total Click payments (so'm)")
    payme: float = Field(0.0, description="Total Payme payments (so'm)")
    account: float = Field(0.0, description="Total account payments (click + payme)")
    total: float = Field(0.0, description="Grand total all providers")

    # Payment counts
    cash_count: int = Field(0, description="Number of cash payments")
    click_count: int = Field(0, description="Number of Click payments")
    payme_count: int = Field(0, description="Number of Payme payments")
    account_count: int = Field(0, description="Number of account payments (click + payme)")
    total_count: int = Field(0, description="Total payment count")


class ProviderSharePercentages(BaseModel):
    """Provider market share percentages for pie charts."""
    cash_percent: float = Field(0.0, description="Cash share percentage")
    click_percent: float = Field(0.0, description="Click share percentage")
    payme_percent: float = Field(0.0, description="Payme share percentage")
    account_percent: float = Field(0.0, description="Account (click+payme) share percentage")


# =============================================================================
# PERIOD DATA SCHEMAS
# =============================================================================


class PaymentPeriodData(BaseModel):
    """Payment data for a specific time period with provider breakdown."""
    start_date: date
    end_date: date
    providers: ProviderTotals
    share_percentages: Optional[ProviderSharePercentages] = None


class GrowthMetrics(BaseModel):
    """
    Growth comparison metrics.

    If previous period = 0 and current > 0: is_new = True, percent = None
    """
    difference: float = Field(..., description="Absolute difference (current - previous)")
    percent: Optional[float] = Field(None, description="Percentage growth (null if is_new)")
    is_new: bool = Field(False, description="True if previous = 0 and current > 0")


class ProviderGrowthMetrics(BaseModel):
    """Growth metrics for each provider."""
    total: GrowthMetrics
    cash: GrowthMetrics
    click: GrowthMetrics
    payme: GrowthMetrics
    account: GrowthMetrics


class PeriodComparison(BaseModel):
    """Comparison between current and previous period."""
    current: PaymentPeriodData
    previous: PaymentPeriodData
    growth: ProviderGrowthMetrics


# =============================================================================
# MAIN RESPONSE SCHEMAS
# =============================================================================


class PaymentSummaryResponse(BaseModel):
    """
    GET /api/stats/payments/summary

    Comprehensive payment summary with all-time totals and provider breakdown.
    """
    # All-time totals by provider
    providers: ProviderTotals = Field(..., description="All-time payment totals by provider")

    # Provider share percentages
    share_percentages: ProviderSharePercentages = Field(
        ...,
        description="Provider market share for pie charts"
    )

    # Today's totals
    today: PaymentPeriodData

    # Yesterday's totals
    yesterday: PaymentPeriodData

    # This week (Mon-Sun, Asia/Tashkent)
    this_week: PaymentPeriodData

    # Previous week
    previous_week: PaymentPeriodData

    # This month (calendar)
    this_month: PaymentPeriodData

    # Previous month (calendar)
    previous_month: PaymentPeriodData

    # Last 7 days (rolling)
    last_7_days: PaymentPeriodData

    # Last 60 days
    last_60_days: PaymentPeriodData

    # Growth metrics
    growth: dict = Field(
        ...,
        description="Growth comparisons: daily (today vs yesterday), weekly (this vs prev), monthly (this vs prev)"
    )

    # Metadata
    calculated_at: datetime = Field(..., description="Calculation timestamp (Asia/Tashkent)")


class DailyPaymentStats(BaseModel):
    """Daily payment statistics with provider breakdown."""
    date: date
    providers: ProviderTotals


class PaymentDailyResponse(BaseModel):
    """
    GET /api/stats/payments/daily

    Daily payment statistics for a date range.
    """
    days: List[DailyPaymentStats]
    period_totals: ProviderTotals
    start_date: date
    end_date: date
    total_days: int


class WeeklyPaymentStats(BaseModel):
    """Weekly payment statistics."""
    week_start: date  # Monday
    week_end: date    # Sunday
    week_number: int
    year: int
    providers: ProviderTotals


class PaymentWeeklyResponse(BaseModel):
    """
    GET /api/stats/payments/weekly

    Weekly payment statistics.
    """
    weeks: List[WeeklyPaymentStats]
    period_totals: ProviderTotals
    total_weeks: int


class MonthlyPaymentStats(BaseModel):
    """Monthly payment statistics."""
    month: int  # 1-12
    year: int
    month_name: str  # "January", "February", etc.
    providers: ProviderTotals


class PaymentMonthlyResponse(BaseModel):
    """
    GET /api/stats/payments/monthly

    Monthly payment statistics.
    """
    months: List[MonthlyPaymentStats]
    period_totals: ProviderTotals
    total_months: int


class PaymentCompareResponse(BaseModel):
    """
    GET /api/stats/payments/compare

    Period comparison with growth calculations.
    """
    daily: PeriodComparison = Field(..., description="Today vs Yesterday")
    weekly: PeriodComparison = Field(..., description="This week vs Previous week")
    monthly: PeriodComparison = Field(..., description="This month vs Previous month")

    calculated_at: datetime


# =============================================================================
# EXPORT SCHEMAS
# =============================================================================


class PaymentExportRow(BaseModel):
    """Single row for CSV export."""
    date: date
    payment_provider: str
    amount: float
    transaction_id: Optional[int] = None
    admin_id: Optional[int] = None
    created_at: datetime


class PaymentExportResponse(BaseModel):
    """Export metadata response."""
    filename: str
    total_rows: int
    period_start: date
    period_end: date
    format: str  # "csv" or "json"


# =============================================================================
# CLIENT-SPECIFIC STATS (BONUS)
# =============================================================================


class ClientPaymentStats(BaseModel):
    """Payment statistics for a specific client."""
    client_code: str
    providers: ProviderTotals
    first_payment_date: Optional[date] = None
    last_payment_date: Optional[date] = None
    total_transactions: int = 0


class ClientPaymentStatsResponse(BaseModel):
    """
    GET /api/stats/payments/by-client

    Payment statistics grouped by client.
    """
    clients: List[ClientPaymentStats]
    total_clients: int
    period_start: Optional[date] = None
    period_end: Optional[date] = None


# =============================================================================
# FLIGHT-SPECIFIC STATS (BONUS)
# =============================================================================


class FlightPaymentStats(BaseModel):
    """Payment statistics for a specific flight."""
    flight_name: str
    providers: ProviderTotals
    unique_clients: int = 0
    total_transactions: int = 0


class FlightPaymentStatsResponse(BaseModel):
    """
    GET /api/stats/payments/by-flight

    Payment statistics grouped by flight.
    """
    flights: List[FlightPaymentStats]
    total_flights: int
    period_start: Optional[date] = None
    period_end: Optional[date] = None
