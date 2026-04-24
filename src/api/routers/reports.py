"""Reports API router - Web report history endpoints."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user, get_translator
from src.api.schemas.cargo import ReportResponse
from src.api.services.report_service import ReportService
from src.infrastructure.database.models.client import Client

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/flights/{client_code}",
    response_model=list[str],
    summary="Get web-sent flight names",
    description="Returns distinct flight names where is_sent_web=True for the given client."
)
async def get_web_flights(
    client_code: str,
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Page size"),
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator)
):
    """
    Get paginated list of flight names sent via web for a client.

    - Filters: is_sent_web=True
    - Supports pagination via page/size query params
    """
    clean_client = client_code.strip().upper()
    service = ReportService()
    return await service.get_client_flights(session, clean_client, page, size)


@router.get(
    "/history/{client_code}",
    response_model=list[ReportResponse],
    summary="Get web report history",
    description="Returns cargo report history with enriched track codes for the given client."
)
async def get_web_history(
    client_code: str,
    flight_name: str | None = Query(None, description="Filter by specific flight name"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Page size"),
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator)
):
    """
    Get paginated web report history for a client.

    - Filters: is_sent_web=True
    - Optional flight_name filter
    - Track codes resolved from Google Sheets (primary) with DB fallback
    - Returns weight, price, photos, date, and track codes
    """
    clean_client = client_code.strip().upper()
    clean_flight = flight_name.strip().upper() if flight_name else None
    service = ReportService()
    return await service.get_client_history(session, clean_client, page, clean_flight, size)
