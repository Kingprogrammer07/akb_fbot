"""
Payment Statistics API Router.

Enterprise-grade financial statistics API for payment provider analytics.
All endpoints use Asia/Tashkent timezone for business calculations.

SOURCE OF TRUTH: client_payment_events table

Endpoints:
- GET /api/v1/stats/payments/summary - Comprehensive summary with all periods
- GET /api/v1/stats/payments/daily - Daily breakdown
- GET /api/v1/stats/payments/weekly - Weekly breakdown
- GET /api/v1/stats/payments/monthly - Monthly breakdown
- GET /api/v1/stats/payments/compare - Period comparisons with growth
- GET /api/v1/stats/payments/by-client - Per-client breakdown
- GET /api/v1/stats/payments/by-flight - Per-flight breakdown
- GET /api/v1/stats/payments/export - CSV export
"""
import io
import csv
from datetime import date, datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.infrastructure.services.payment_stats_service import PaymentStatsService
from src.infrastructure.schemas.payment_stats import (
    PaymentSummaryResponse,
    PaymentDailyResponse,
    PaymentWeeklyResponse,
    PaymentMonthlyResponse,
    PaymentCompareResponse,
    ClientPaymentStatsResponse,
    FlightPaymentStatsResponse,
    PaymentExportResponse,
)
from src.infrastructure.tools.datetime_utils import get_current_business_date, TASHKENT_TZ


router = APIRouter(prefix="/stats/payments", tags=["payment-statistics"])


# =============================================================================
# MAIN STATISTICS ENDPOINTS
# =============================================================================


@router.get("/summary", response_model=PaymentSummaryResponse)
async def get_payment_summary(
    session: AsyncSession = Depends(get_db)
) -> PaymentSummaryResponse:
    """
    Get comprehensive payment summary with provider breakdown.

    Returns all-time totals plus period comparisons:
    - Today vs Yesterday
    - This week vs Previous week (Mon-Sun)
    - This month vs Previous month
    - Last 7 days (rolling)
    - Last 60 days

    Growth metrics calculated for total and each provider.

    Response JSON structure:
    ```json
    {
      "providers": {
        "cash": 12000000,
        "click": 8500000,
        "payme": 4300000,
        "account": 12800000,
        "total": 24800000,
        "cash_count": 150,
        "click_count": 200,
        "payme_count": 80,
        "account_count": 280,
        "total_count": 430
      },
      "share_percentages": {
        "cash_percent": 48.39,
        "click_percent": 34.27,
        "payme_percent": 17.34,
        "account_percent": 51.61
      },
      "today": {...},
      "yesterday": {...},
      "this_week": {...},
      "previous_week": {...},
      "this_month": {...},
      "previous_month": {...},
      "last_7_days": {...},
      "last_60_days": {...},
      "growth": {
        "daily": {
          "total": {"difference": 1200000, "percent": 14.3, "is_new": false},
          "cash": {...},
          "click": {...},
          "payme": {...},
          "account": {...}
        },
        "weekly": {...},
        "monthly": {...}
      },
      "calculated_at": "2024-01-15T14:30:00+05:00"
    }
    ```
    """
    try:
        return await PaymentStatsService.get_summary(session)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get payment summary: {str(e)}"
        )


@router.get("/daily", response_model=PaymentDailyResponse)
async def get_daily_payments(
    start_date: Optional[date] = Query(
        None,
        description="Start date (YYYY-MM-DD). Default: 30 days ago"
    ),
    end_date: Optional[date] = Query(
        None,
        description="End date (YYYY-MM-DD). Default: today"
    ),
    session: AsyncSession = Depends(get_db)
) -> PaymentDailyResponse:
    """
    Get daily payment statistics with provider breakdown.

    Returns payment totals for each day in the date range,
    broken down by provider (cash, click, payme).

    Use for daily trend charts and detailed analysis.
    """
    today = get_current_business_date()

    if end_date is None:
        end_date = today
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be before or equal to end_date"
        )

    try:
        return await PaymentStatsService.get_daily_stats(session, start_date, end_date)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get daily payments: {str(e)}"
        )


@router.get("/weekly", response_model=PaymentWeeklyResponse)
async def get_weekly_payments(
    weeks: int = Query(
        12,
        ge=1,
        le=52,
        description="Number of weeks to retrieve (default: 12)"
    ),
    session: AsyncSession = Depends(get_db)
) -> PaymentWeeklyResponse:
    """
    Get weekly payment statistics with provider breakdown.

    Week starts on Monday (ISO standard).

    Returns payment totals for each week, broken down by provider.
    Use for weekly trend charts.
    """
    try:
        return await PaymentStatsService.get_weekly_stats(session, weeks)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get weekly payments: {str(e)}"
        )


@router.get("/monthly", response_model=PaymentMonthlyResponse)
async def get_monthly_payments(
    months: int = Query(
        12,
        ge=1,
        le=36,
        description="Number of months to retrieve (default: 12)"
    ),
    session: AsyncSession = Depends(get_db)
) -> PaymentMonthlyResponse:
    """
    Get monthly payment statistics with provider breakdown.

    Returns payment totals for each month, broken down by provider.
    Use for monthly trend charts and long-term analysis.
    """
    try:
        return await PaymentStatsService.get_monthly_stats(session, months)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get monthly payments: {str(e)}"
        )


@router.get("/compare", response_model=PaymentCompareResponse)
async def get_payment_comparisons(
    session: AsyncSession = Depends(get_db)
) -> PaymentCompareResponse:
    """
    Get period comparisons with growth metrics.

    Returns detailed comparisons:
    - Daily: Today vs Yesterday
    - Weekly: This week vs Previous week (Mon-Sun)
    - Monthly: This month vs Previous month

    Each comparison includes:
    - Current period data with provider breakdown
    - Previous period data with provider breakdown
    - Growth metrics (difference, percent, is_new flag)

    Growth calculation rules:
    - If previous = 0 and current > 0: is_new = true, percent = null
    - If previous = 0 and current = 0: difference = 0, percent = 0
    - Otherwise: percent = ((current - previous) / previous) * 100
    """
    try:
        return await PaymentStatsService.get_comparison(session)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get payment comparisons: {str(e)}"
        )


# =============================================================================
# BONUS ENDPOINTS - PER CLIENT / PER FLIGHT
# =============================================================================


@router.get("/by-client", response_model=ClientPaymentStatsResponse)
async def get_payments_by_client(
    start_date: Optional[date] = Query(
        None,
        description="Start date filter (YYYY-MM-DD)"
    ),
    end_date: Optional[date] = Query(
        None,
        description="End date filter (YYYY-MM-DD)"
    ),
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="Maximum number of clients to return"
    ),
    session: AsyncSession = Depends(get_db)
) -> ClientPaymentStatsResponse:
    """
    Get payment statistics grouped by client.

    Returns top clients by payment amount with provider breakdown.
    Useful for client ranking and analysis.

    Includes:
    - Payment totals per provider
    - First and last payment dates
    - Total transaction count
    """
    try:
        return await PaymentStatsService.get_client_stats(
            session, start_date, end_date, limit
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get client payments: {str(e)}"
        )


@router.get("/by-flight", response_model=FlightPaymentStatsResponse)
async def get_payments_by_flight(
    start_date: Optional[date] = Query(
        None,
        description="Start date filter (YYYY-MM-DD)"
    ),
    end_date: Optional[date] = Query(
        None,
        description="End date filter (YYYY-MM-DD)"
    ),
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="Maximum number of flights to return"
    ),
    session: AsyncSession = Depends(get_db)
) -> FlightPaymentStatsResponse:
    """
    Get payment statistics grouped by flight (reys).

    Returns top flights by payment amount with provider breakdown.
    Useful for flight-level financial analysis.

    Includes:
    - Payment totals per provider
    - Unique client count
    - Total transaction count
    """
    try:
        return await PaymentStatsService.get_flight_stats(
            session, start_date, end_date, limit
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get flight payments: {str(e)}"
        )


# =============================================================================
# EXPORT ENDPOINTS
# =============================================================================


@router.get("/export")
async def export_payments(
    start_date: Optional[date] = Query(
        None,
        description="Start date (YYYY-MM-DD). Default: 30 days ago"
    ),
    end_date: Optional[date] = Query(
        None,
        description="End date (YYYY-MM-DD). Default: today"
    ),
    provider: Optional[str] = Query(
        None,
        description="Filter by provider: cash, click, payme"
    ),
    format: str = Query(
        "csv",
        description="Export format: csv or json"
    ),
    session: AsyncSession = Depends(get_db)
):
    """
    Export payment events to CSV or JSON.

    CSV columns:
    - date (YYYY-MM-DD, Asia/Tashkent)
    - payment_provider
    - amount
    - transaction_id
    - admin_id
    - created_at (ISO format)

    CSV requirements:
    - UTF-8 encoding
    - Comma separated
    - Downloadable with Content-Disposition header
    - Timezone normalized to Asia/Tashkent
    """
    today = get_current_business_date()

    if end_date is None:
        end_date = today
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be before or equal to end_date"
        )

    if provider and provider not in ['cash', 'click', 'payme', 'card']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider must be 'cash', 'click', 'payme', or 'card'"
        )

    if format not in ['csv', 'json']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="format must be 'csv' or 'json'"
        )

    try:
        data = await PaymentStatsService.get_export_data(
            session, start_date, end_date, provider
        )

        if format == 'json':
            # Return JSON directly
            return JSONResponse(content={
                'payments': data,
                'total_rows': len(data),
                'period_start': str(start_date),
                'period_end': str(end_date),
                'provider_filter': provider
            })

        # CSV export
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)

        # Header row
        writer.writerow([
            'date',
            'payment_provider',
            'amount',
            'transaction_id',
            'admin_id',
            'created_at'
        ])

        # Data rows
        for row in data:
            # Convert created_at to Tashkent timezone
            created_at = row['created_at']
            if created_at.tzinfo is None:
                import pytz
                created_at = pytz.UTC.localize(created_at)
            tashkent_dt = created_at.astimezone(TASHKENT_TZ)

            writer.writerow([
                tashkent_dt.date().isoformat(),
                row['payment_provider'],
                row['amount'],
                row['transaction_id'],
                row['admin_id'] or '',
                tashkent_dt.isoformat()
            ])

        csv_content = csv_buffer.getvalue()
        csv_buffer.close()

        # Build filename
        provider_suffix = f"_{provider}" if provider else ""
        filename = f"payments{provider_suffix}_{start_date}_{end_date}.csv"

        return StreamingResponse(
            io.BytesIO(csv_content.encode('utf-8')),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "text/csv; charset=utf-8"
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export payments: {str(e)}"
        )


@router.get("/export/summary")
async def export_summary_csv(
    session: AsyncSession = Depends(get_db)
):
    """
    Export payment summary to CSV.

    Includes:
    - All-time totals by provider
    - Period totals (today, yesterday, this week, etc.)
    - Growth metrics

    Useful for management reporting and accounting.
    """
    try:
        summary = await PaymentStatsService.get_summary(session)

        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)

        # Section 1: All-time totals
        writer.writerow(['=== ALL-TIME TOTALS ==='])
        writer.writerow(['Provider', 'Amount (so\'m)', 'Count'])
        writer.writerow(['Cash', summary.providers.cash, summary.providers.cash_count])
        writer.writerow(['Click', summary.providers.click, summary.providers.click_count])
        writer.writerow(['Payme', summary.providers.payme, summary.providers.payme_count])
        writer.writerow(['Account (Click+Payme)', summary.providers.account, summary.providers.account_count])
        writer.writerow(['TOTAL', summary.providers.total, summary.providers.total_count])
        writer.writerow([])

        # Section 2: Market share
        writer.writerow(['=== MARKET SHARE ==='])
        writer.writerow(['Provider', 'Percentage'])
        writer.writerow(['Cash', f"{summary.share_percentages.cash_percent}%"])
        writer.writerow(['Click', f"{summary.share_percentages.click_percent}%"])
        writer.writerow(['Payme', f"{summary.share_percentages.payme_percent}%"])
        writer.writerow(['Account', f"{summary.share_percentages.account_percent}%"])
        writer.writerow([])

        # Section 3: Period totals
        writer.writerow(['=== PERIOD TOTALS ==='])
        writer.writerow(['Period', 'Start Date', 'End Date', 'Total Amount', 'Total Count'])
        writer.writerow([
            'Today',
            summary.today.start_date,
            summary.today.end_date,
            summary.today.providers.total,
            summary.today.providers.total_count
        ])
        writer.writerow([
            'Yesterday',
            summary.yesterday.start_date,
            summary.yesterday.end_date,
            summary.yesterday.providers.total,
            summary.yesterday.providers.total_count
        ])
        writer.writerow([
            'This Week',
            summary.this_week.start_date,
            summary.this_week.end_date,
            summary.this_week.providers.total,
            summary.this_week.providers.total_count
        ])
        writer.writerow([
            'Previous Week',
            summary.previous_week.start_date,
            summary.previous_week.end_date,
            summary.previous_week.providers.total,
            summary.previous_week.providers.total_count
        ])
        writer.writerow([
            'This Month',
            summary.this_month.start_date,
            summary.this_month.end_date,
            summary.this_month.providers.total,
            summary.this_month.providers.total_count
        ])
        writer.writerow([
            'Previous Month',
            summary.previous_month.start_date,
            summary.previous_month.end_date,
            summary.previous_month.providers.total,
            summary.previous_month.providers.total_count
        ])
        writer.writerow([
            'Last 7 Days',
            summary.last_7_days.start_date,
            summary.last_7_days.end_date,
            summary.last_7_days.providers.total,
            summary.last_7_days.providers.total_count
        ])
        writer.writerow([
            'Last 60 Days',
            summary.last_60_days.start_date,
            summary.last_60_days.end_date,
            summary.last_60_days.providers.total,
            summary.last_60_days.providers.total_count
        ])
        writer.writerow([])

        # Section 4: Growth
        writer.writerow(['=== GROWTH METRICS ==='])
        daily_growth = summary.growth.get('daily', {}).get('total', {})
        weekly_growth = summary.growth.get('weekly', {}).get('total', {})
        monthly_growth = summary.growth.get('monthly', {}).get('total', {})

        writer.writerow(['Period', 'Difference', 'Percent', 'Is New'])
        writer.writerow([
            'Daily (Today vs Yesterday)',
            daily_growth.get('difference', 0),
            f"{daily_growth.get('percent', 0)}%" if daily_growth.get('percent') is not None else 'N/A',
            daily_growth.get('is_new', False)
        ])
        writer.writerow([
            'Weekly (This vs Prev)',
            weekly_growth.get('difference', 0),
            f"{weekly_growth.get('percent', 0)}%" if weekly_growth.get('percent') is not None else 'N/A',
            weekly_growth.get('is_new', False)
        ])
        writer.writerow([
            'Monthly (This vs Prev)',
            monthly_growth.get('difference', 0),
            f"{monthly_growth.get('percent', 0)}%" if monthly_growth.get('percent') is not None else 'N/A',
            monthly_growth.get('is_new', False)
        ])

        csv_content = csv_buffer.getvalue()
        csv_buffer.close()

        today = get_current_business_date()
        filename = f"payment_summary_{today}.csv"

        return StreamingResponse(
            io.BytesIO(csv_content.encode('utf-8')),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "text/csv; charset=utf-8"
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export summary: {str(e)}"
        )
