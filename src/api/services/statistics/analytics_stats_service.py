import math
from datetime import date
from typing import Optional

from src.infrastructure.database.dao.statistics.analytics_stats import AnalyticsStatsDAO
from src.api.schemas.statistics.analytics_stats import (
    AnalyticsEventItem,
    AnalyticsEventPage,
    AnalyticsDailyTrendItem,
    AnalyticsEventTypeSummary,
    AnalyticsStatsResponse,
)


class AnalyticsStatsService:
    def __init__(self, dao: AnalyticsStatsDAO):
        self.dao = dao

    async def get_events_page(
        self,
        event_type: Optional[str],
        start_date: Optional[date],
        end_date: Optional[date],
        page: int,
        page_size: int,
    ) -> AnalyticsEventPage:
        items_raw, total = await self.dao.get_events_page(
            event_type, start_date, end_date, page, page_size
        )
        items = [AnalyticsEventItem(**row) for row in items_raw]
        total_pages = math.ceil(total / page_size) if page_size else 1
        return AnalyticsEventPage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    async def get_stats(
        self,
        event_type: Optional[str],
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> AnalyticsStatsResponse:
        summary_raw = await self.dao.get_summary(start_date, end_date)
        trends_raw = await self.dao.get_daily_trends(event_type, start_date, end_date)

        summary = [AnalyticsEventTypeSummary(**row) for row in summary_raw]
        daily_trends = [
            AnalyticsDailyTrendItem(date=row["date"], count=row["count"])
            for row in trends_raw
        ]
        return AnalyticsStatsResponse(summary=summary, daily_trends=daily_trends)
