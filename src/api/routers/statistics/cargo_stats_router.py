from datetime import date
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.routers.admin_auth import get_admin_from_jwt
from src.api.schemas.statistics.cargo_stats import CargoStatsResponse
from src.infrastructure.database.dao.statistics.cargo_stats import CargoStatsDAO
from src.api.services.statistics.cargo_stats_service import CargoStatsService

router = APIRouter(prefix="/statistics/cargo", tags=["Statistics: Cargo"])


@router.get(
    "",
    response_model=CargoStatsResponse,
    summary="Yuklar statistikasini olish",
    description="Asosiy yuk hajmlari, muammoli nuqtalar, aylanma tezlik, eng katta hajmli reyslar va yuk kelish dinamikasini qaytaradi.",
)
async def get_cargo_stats(
    start_date: date | None = Query(None, description="Boshlanish sanasi (Y-M-D)"),
    end_date: date | None = Query(None, description="Tugash sanasi (Y-M-D)"),
    session: AsyncSession = Depends(get_db),
    # admin=Depends(get_admin_from_jwt),
):
    dao = CargoStatsDAO(session)
    service = CargoStatsService(dao)
    return await service.get_stats(start_date, end_date)


@router.get(
    "/export",
    summary="Yuklar statistikasini Excel ga yuklab olish",
    description="Hozirgi vaqt oraliq filtrlariga ko'ra olingan yuklar statistikasini .xlsx (Excel) formatida yuklab beradi.",
)
async def export_cargo_stats_excel(
    start_date: date | None = Query(None, description="Boshlanish sanasi (Y-M-D)"),
    end_date: date | None = Query(None, description="Tugash sanasi (Y-M-D)"),
    session: AsyncSession = Depends(get_db),
    # admin=Depends(get_admin_from_jwt),
):
    dao = CargoStatsDAO(session)
    service = CargoStatsService(dao)
    excel_stream = await service.export_stats_excel(start_date, end_date)

    file_name = "yuklar_statistikasi"
    if start_date or end_date:
        sd = start_date.strftime("%Y-%m-%d") if start_date else "boshidan"
        ed = end_date.strftime("%Y-%m-%d") if end_date else "hozirgacha"
        file_name += f"_{sd}_{ed}"

    return StreamingResponse(
        excel_stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={file_name}.xlsx"},
    )