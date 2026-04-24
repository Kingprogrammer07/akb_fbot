from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.schemas.statistics.analytics_stats import (
    AnalyticsEventPage,
    AnalyticsStatsResponse,
)
from src.infrastructure.database.dao.statistics.analytics_stats import AnalyticsStatsDAO
from src.api.services.statistics.analytics_stats_service import AnalyticsStatsService

router = APIRouter(prefix="/statistics/analytics", tags=["Statistics: Analytics"])


@router.get(
    "",
    response_model=AnalyticsStatsResponse,
    summary="Analytics eventlar umumiy statistikasi",
    description="Har bir event_type bo'yicha umumiy statistika va kunlik trend grafigi.",
)
async def get_analytics_stats(
    event_type: Optional[str] = Query(None, description="Filtrlash uchun event_type (masalan: track_code_search)"),
    start_date: Optional[date] = Query(None, description="Boshlanish sanasi (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="Tugash sanasi (YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_db),
):
    dao = AnalyticsStatsDAO(session)
    service = AnalyticsStatsService(dao)
    return await service.get_stats(event_type, start_date, end_date)


@router.get(
    "/events",
    response_model=AnalyticsEventPage,
    summary="Analytics eventlar ro'yxati (pagination bilan)",
    description="Barcha analytics eventlarni pagination va filtrlar bilan qaytaradi.",
)
async def get_analytics_events(
    event_type: Optional[str] = Query(None, description="Filtrlash uchun event_type"),
    start_date: Optional[date] = Query(None, description="Boshlanish sanasi (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="Tugash sanasi (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Sahifa raqami"),
    page_size: int = Query(50, ge=1, le=500, description="Sahifadagi elementlar soni"),
    session: AsyncSession = Depends(get_db),
):
    dao = AnalyticsStatsDAO(session)
    service = AnalyticsStatsService(dao)
    return await service.get_events_page(event_type, start_date, end_date, page, page_size)
