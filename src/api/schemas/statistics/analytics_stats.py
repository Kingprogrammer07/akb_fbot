from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AnalyticsEventItem(BaseModel):
    id: int
    event_type: str
    user_id: int | None
    event_data: dict[str, Any] | None
    created_at: datetime

    class Config:
        from_attributes = True


class AnalyticsEventPage(BaseModel):
    items: list[AnalyticsEventItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class AnalyticsDailyTrendItem(BaseModel):
    date: str = Field(..., description="Sana (YYYY-MM-DD)")
    count: int = Field(..., description="Shu kunda sodir bo'lgan eventlar soni")


class AnalyticsEventTypeSummary(BaseModel):
    event_type: str
    total_count: int
    unique_users: int
    last_occurrence: datetime | None


class AnalyticsStatsResponse(BaseModel):
    summary: list[AnalyticsEventTypeSummary] = Field(
        ..., description="Har bir event_type bo'yicha umumiy statistika"
    )
    daily_trends: list[AnalyticsDailyTrendItem] = Field(
        ..., description="Kunlik eventlar soni (grafik uchun)"
    )
