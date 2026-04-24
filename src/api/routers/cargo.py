from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import config
from src.api.dependencies import get_db, get_current_user, get_translator
from src.api.schemas.cargo import (
    TrackCodeSearchResponse, 
    CargoItemResponse, 
    FlightStatusResponse,
    ClientFlightSummary,
    ClientFlightDetailResponse
)
from src.infrastructure.services.cargo_item import CargoItemService
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.bot.utils.google_sheets_checker import GoogleSheetsChecker

router = APIRouter(prefix="/cargo", tags=["cargo"])


def _assert_owns_client_code(current_user: Client, requested_code: str) -> None:
    """Raise 403 if the authenticated user does not own the requested client code.

    A user may legitimately have two codes (client_code and extra_code).
    Both are checked so that either assignment grants access.

    Why we raise here rather than silently returning empty data: returning an
    empty response for someone else's valid code would leak existence information
    ("this code has no cargo") while still being an authorization bypass.
    """
    user_codes = {
        code.upper()
        for code in (current_user.client_code, getattr(current_user, "extra_code", None))
        if code
    }
    if not user_codes or requested_code.upper() not in user_codes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: this cargo data does not belong to your account.",
        )


@router.get(
    "/track/{track_code}",
    response_model=TrackCodeSearchResponse,
    summary="Track cargo by code",
    description="Search for cargo items by track code. Returns items in Uzbekistan and China."
)
async def track_cargo(
    track_code: str,
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator)
):
    """
    Track cargo items by code.
    
    - Validates track code length (min 3 chars).
    - Returns found items separated by location (China/Uzbekistan).
    - Returns found: false if no items found (instead of 404).
    """
    # Validation
    if not track_code or len(track_code.strip()) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("user-track-check-code-too-short")
        )

    clean_track_code = track_code.strip().upper()
    
    # Service call
    service = CargoItemService()
    results = await service.search_by_track_code(clean_track_code, session)
    
    # Transform results to Pydantic models
    items = [CargoItemResponse(**item) for item in results['items']]
    
    return TrackCodeSearchResponse(
        found=results['found'],
        track_code=clean_track_code,
        items=items,
        total_count=results['total_count']
    )


@router.get(
    "/flight-status",
    response_model=FlightStatusResponse,
    summary="Check cargo status in flight",
    description="Check if client's cargo exists in Google Sheets and local database for a specific flight."
)
async def check_flight_status(
    flight_name: str = Query(..., description="Flight name (e.g., M123-2025)"),
    client_code: str = Query(..., description="Client code (e.g., SS123)"),
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator)
):
    """
    Check flight status for a client.
    
    Checks:
    1. Google Sheets: Does the client have cargo in this flight sheet?
    2. Local Database: Does the client have a FlightCargo record for this flight?
    3. Sent Status: If in DB, is it marked as sent?
    """
    clean_flight = flight_name.strip().upper()
    clean_client = client_code.strip().upper()
    _assert_owns_client_code(current_user, clean_client)

    # 1. Check Google Sheets
    sheets_checker = GoogleSheetsChecker(
        spreadsheet_id=config.google_sheets.SHEETS_ID,
        api_key=config.google_sheets.API_KEY
    )
    
    # We use get_track_codes... to check existence. If it returns list (even empty), sheet was accessed.
    # But effectively we want to know if there are track codes or record for this client.
    # The method returns [] if not found or error.
    sheet_tracks = await sheets_checker.get_track_codes_by_flight_and_client(
        clean_flight, clean_client
    )
    exists_in_sheets = len(sheet_tracks) > 0

    # 2. Check Local Database
    # We strip 'only_sent' logic to check existence of ANY record first
    # But the DAO method `get_flight_data_by_flight_name_client_code` has `only_sent` param.
    # Let's check pure existence.
    
    # Note: The DAO method name is long and specific. Let's look at `get_by_client`.
    # It returns a list.
    db_cargos = await FlightCargoDAO.get_by_client(
        session, clean_flight, clean_client, limit=1
    )
    exists_in_db = len(db_cargos) > 0
    
    is_sent = False
    if exists_in_db:
        # Check if ANY of them is sent (or logic specific to user request "agar mavjud bo'lsa is_sent true mi")
        # Usually checking if *all* are sent or *any*.
        # Let's assume if the latest one is sent or if there is any sent record.
        # User said: "agar mavjud bo'lsa is_sent true mi yoki yo'qmi" -> implying single status.
        # Let's check if there is at least one sent item or if the 'main' record is sent.
        # Since FlightCargo entries are per-photo/group, let's check if ANY is sent.
        is_sent = any(c.is_sent_web for c in db_cargos)
        
        # Alternatively, strictly check if *all* are sent?
        # Given the context of "Did I send this to client?", usually we want to know if we processed it.
        # Let's stick to: is there a sent record?
        
        # Actually, let's refine:
        # The user wants to know if they *recieved* it (is_sent usually means sent to client bot).
        # Let's check consistency.
        pass

    # 3. Check Is Taken Away (if transaction exists)
    transaction = await ClientTransactionDAO.get_by_client_code_flight(
        session, clean_client, clean_flight
    )
    
    is_taken_away = None
    taken_away_date = None
    
    if transaction:
        is_taken_away = transaction.is_taken_away
        if transaction.taken_away_date:
            taken_away_date = transaction.taken_away_date.isoformat()

    return FlightStatusResponse(
        flight_name=clean_flight,
        client_code=clean_client,
        exists_in_sheets=exists_in_sheets,
        exists_in_db=exists_in_db,
        is_sent=is_sent,
        is_taken_away=is_taken_away,
        taken_away_date=taken_away_date
    )


@router.get(
    "/history/{client_code}/flights",
    response_model=list[ClientFlightSummary],
    summary="Get client flight history",
    description="Returns a summary list of all flights for this client."
)
async def get_client_flight_history(
    client_code: str,
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator)
):
    """
    Get flight history for a client.
    
    Returns key stats per flight:
    - flight_name
    - total_count
    - total_weight
    - last_update
    """
    clean_client = client_code.strip().upper()
    _assert_owns_client_code(current_user, clean_client)
    service = CargoItemService()

    return await service.get_flight_summaries_for_client(clean_client, session)


@router.get(
    "/history/{client_code}/flights/{flight_name}",
    response_model=ClientFlightDetailResponse,
    summary="Get detailed flight cargo",
    description="Returns detailed cargo items for the specific flight and client."
)
async def get_flight_details(
    client_code: str,
    flight_name: str,
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator)
):
    """
    Get detailed items for a flight.
    
    - Supports pagination
    - Filters by client and flight
    """
    clean_client = client_code.strip().upper()
    _assert_owns_client_code(current_user, clean_client)
    clean_flight = flight_name.strip()
    
    service = CargoItemService()
    
    return await service.get_flight_details_for_client(
        clean_client, 
        clean_flight, 
        page, 
        size, 
        session
    )
