from datetime import datetime
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_admin_from_jwt
from src.api.schemas.statistics.financial_stats import FinancialStatsResponse
from src.api.services.statistics.financial_stats_service import FinancialStatsService

router = APIRouter(prefix="/statistics/financial", tags=["Financial Statistics"])


@router.get("", response_model=FinancialStatsResponse)
async def get_financial_stats(
    start_date: datetime | None = Query(None, description="Boshlanish sanasi"),
    end_date: datetime | None = Query(None, description="Tugash sanasi"),
    base_cost_usd: float = Query(
        8.0, description="1 kg yuk uchun asosiy xarajat (USD, foyda hisoblash uchun)"
    ),
    session: AsyncSession = Depends(get_db),
    # admin=Depends(get_admin_from_jwt),
):
    """
    Get financial statistics.
    Requires Admin JWT.
    """
    return await FinancialStatsService.get_summary(
        session, start_date, end_date, base_cost_usd
    )


@router.get("/export")
async def export_financial_stats(
    start_date: datetime | None = Query(None, description="Boshlanish sanasi"),
    end_date: datetime | None = Query(None, description="Tugash sanasi"),
    base_cost_usd: float = Query(
        8.0, description="1 kg yuk uchun asosiy xarajat (USD, foyda hisoblash uchun)"
    ),
    session: AsyncSession = Depends(get_db),
    # admin=Depends(get_admin_from_jwt),
):
    """
    Export financial statistics to Excel.
    Requires Admin JWT.
    """
    excel_stream = await FinancialStatsService.generate_excel(
        session, start_date, end_date, base_cost_usd
    )
    return StreamingResponse(
        excel_stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Moliyaviy_Statistika.xlsx"},
    )