from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_admin_from_jwt

from src.api.schemas.statistics.operational_stats import OperationalStatsResponse
from src.api.services.statistics.operational_stats_service import (
    OperationalStatsService,
)

router = APIRouter(prefix="/operational", tags=["Statistics - Operational"])


@router.get("/summary", response_model=OperationalStatsResponse)
async def get_operational_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    session: AsyncSession = Depends(get_db),
    # admin=Depends(get_admin_from_jwt),
):
    """
    Get operational statistics summary (bottlenecks, stage times).
    """
    return await OperationalStatsService.get_summary(session, start_date, end_date)


@router.get("/export")
async def export_operational_stats(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    session: AsyncSession = Depends(get_db),
    # admin=Depends(get_admin_from_jwt),
):
    """
    Export operational stats to Excel.
    """
    file_bytes = await OperationalStatsService.export_to_excel(
        session, start_date, end_date
    )
    return StreamingResponse(
        iter([file_bytes.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=operatsion_stat_{start_date or 'all'}_to_{end_date or 'all'}.xlsx"
        },
    )
