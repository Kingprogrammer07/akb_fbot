from datetime import date
from typing import Annotated
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.routers.admin_auth import get_admin_from_jwt
from src.api.schemas.statistics.client_stats import ClientStatsResponse
from src.api.services.statistics.client_stats_service import ClientStatsService

router = APIRouter(prefix="/statistics/clients", tags=["Statistics: Clients"])


@router.get(
    "",
    response_model=ClientStatsResponse,
    summary="Mijozlar statistikasini olish",
    description="Vaqt oralig'i (start_date, end_date) bo'yicha mijozlarning umumiy ro'yxati, retention, hududlar va yetkazib berish usullari statistikasini qaytaradi.",
)
async def get_client_stats(
    start_date: date | None = Query(None, description="Boshlanish sanasi (Y-M-D)"),
    end_date: date | None = Query(None, description="Tugash sanasi (Y-M-D)"),
    session: AsyncSession = Depends(get_db),
    # admin=Depends(get_admin_from_jwt),
):
    service = ClientStatsService(session)
    return await service.get_stats(start_date, end_date)


@router.get(
    "/export",
    summary="Mijozlar statistikasini Excel ga yuklab olish",
    description="Hozirgi vaqt oraliq filtrlariga ko'ra olingan mijozlar statistikasini .xlsx (Excel) formatida yuklab beradi.",
)
async def export_client_stats_excel(
    start_date: date | None = Query(None, description="Boshlanish sanasi (Y-M-D)"),
    end_date: date | None = Query(None, description="Tugash sanasi (Y-M-D)"),
    session: AsyncSession = Depends(get_db),
    # admin=Depends(get_admin_from_jwt),
):
    service = ClientStatsService(session)
    excel_stream = await service.get_stats_excel(start_date, end_date)

    file_name = "mijozlar_statistikasi"
    if start_date or end_date:
        sd = start_date.strftime("%Y-%m-%d") if start_date else "boshidan"
        ed = end_date.strftime("%Y-%m-%d") if end_date else "hozirgacha"
        file_name += f"_{sd}_{ed}"

    return StreamingResponse(
        excel_stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={file_name}.xlsx"},
    )


def _excel_response(stream, file_name: str) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={file_name}.xlsx"},
    )


@router.get(
    "/export/zombie",
    summary="Zombi mijozlar ro'yxatini Excel yuklab olish",
    description="Hech qachon yuk buyurtma qilmagan mijozlar. Filtr: ro'yxatdan o'tgan sana bo'yicha.",
)
async def export_zombie_clients_excel(
    start_date: date | None = Query(None, description="Boshlanish sanasi (Y-M-D)"),
    end_date: date | None = Query(None, description="Tugash sanasi (Y-M-D)"),
    session: AsyncSession = Depends(get_db),
    # admin=Depends(get_admin_from_jwt),
):
    service = ClientStatsService(session)
    sd = start_date.strftime("%Y-%m-%d") if start_date else "boshidan"
    ed = end_date.strftime("%Y-%m-%d") if end_date else "hozirgacha"
    return _excel_response(
        await service.get_zombie_excel(start_date, end_date),
        f"zombie_mijozlar_{sd}_{ed}",
    )


@router.get(
    "/export/passive",
    summary="Passiv mijozlar ro'yxatini Excel yuklab olish",
    description="Kamida 1 yuk buyurtma qilgan, lekin 60+ kun ichida yuk olmagan mijozlar.",
)
async def export_passive_clients_excel(
    start_date: date | None = Query(None, description="Boshlanish sanasi (Y-M-D)"),
    end_date: date | None = Query(None, description="Tugash sanasi (Y-M-D)"),
    session: AsyncSession = Depends(get_db),
    # admin=Depends(get_admin_from_jwt),
):
    service = ClientStatsService(session)
    sd = start_date.strftime("%Y-%m-%d") if start_date else "boshidan"
    ed = end_date.strftime("%Y-%m-%d") if end_date else "hozirgacha"
    return _excel_response(
        await service.get_passive_excel(start_date, end_date),
        f"passiv_mijozlar_{sd}_{ed}",
    )


@router.get(
    "/export/frequent",
    summary="Eng faol mijozlar ro'yxatini Excel yuklab olish",
    description="5 va undan ortiq reysda yuklari bo'lgan mijozlar. min_flights parametri bilan o'zgartirsa bo'ladi.",
)
async def export_frequent_clients_excel(
    min_flights: int = Query(5, ge=1, description="Minimal reys soni (default: 5)"),
    session: AsyncSession = Depends(get_db),
    # admin=Depends(get_admin_from_jwt),
):
    service = ClientStatsService(session)
    return _excel_response(
        await service.get_frequent_excel(min_flights),
        f"faol_mijozlar_{min_flights}plus_reys",
    )