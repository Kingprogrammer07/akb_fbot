"""Verification router for client search and info endpoints."""
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_translator
from src.api.services.verification import VerificationService, CargoService
from src.infrastructure.services.client import ClientService

from src.api.schemas.verification import (
    ClientSearchResponse,
    ClientFullInfoResponse,
    UnpaidCargoListResponse,
    FlightListResponse,
    CargoListResponse,
    FlightPaymentSummary,
    SortOrder,
)
from src.infrastructure.database.dao import ClientTransactionDAO

router = APIRouter(prefix="/verification", tags=["Client Verification"])


# ============================================================================
# Permission Stub
# ============================================================================

async def require_admin():
    """
    Stub for admin permission check.

    Admin is identified by:
    1. clients.role in ['admin', 'super-admin'] in database
    2. telegram_id in config.telegram.admin_ids

    For WebApp: Can use Telegram initData validation.
    For now: stub that allows all requests.
    """
    # TODO: Implement actual admin authentication/authorization
    # This should verify JWT token/initData and check admin role
    pass


# ============================================================================
# Search Endpoints
# ============================================================================

@router.get(
    "/search",
    response_model=ClientSearchResponse,
    summary="Search client by code or phone",
    description="Search for a client by client code or phone number. Returns client profile, stats, and flight list."
)
async def search_client(
    q: str = Query(..., min_length=1, description="Client code or phone number (required)"),
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: None = Depends(require_admin)
) -> ClientSearchResponse:
    """
    Search for a client by code or phone number.

    - **q**: Client code (e.g., "SS123") or phone number (e.g., "+998901234567") - REQUIRED

    Returns client profile with:
    - Basic info (id, code, name, phone, role)
    - Stats (total payments, cargo taken count)
    - List of flights (from database + Google Sheets)
    """
    result = await VerificationService.search_client(q, session)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("admin-verification-client-not-found")
        )

    return ClientSearchResponse(client=result)


@router.get(
    "/{client_code}",
    response_model=ClientFullInfoResponse,
    summary="Get full client information",
    description="Get detailed client information including passport, referrals, and latest transaction."
)
async def get_client_info(
    client_code: str,
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: None = Depends(require_admin)
) -> ClientFullInfoResponse:
    """
    Get full client information by client code (e.g. SS9999).

    Returns:
    - Profile details (passport, PINFL, region, address)
    - role check status
    - Referral count
    - Extra passports count
    - Passport image file IDs
    - Transaction count and latest transaction
    """
    result = await VerificationService.get_client_full_info(client_code.upper(), session)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("client-not-found")
        )

    return ClientFullInfoResponse(client=result)


# ============================================================================
# Unpaid Cargo Endpoints
# ============================================================================

@router.get(
    "/{client_code}/cargo/unpaid",
    response_model=UnpaidCargoListResponse,
    summary="Get unpaid cargo items",
    description="Get list of unpaid cargo items for a client. ALL FILTER PARAMETERS ARE REQUIRED."
)
async def get_unpaid_cargo(
    client_code: str,
    filter_type: Literal["all", "pending"] = Query(
        ..., description="Filter type (required): 'all' or 'pending'"
    ),
    sort_order: SortOrder = Query(
        ..., description="Sort order (required): 'asc' or 'desc'"
    ),
    limit: int = Query(
        ..., ge=1, le=100, description="Items per page (required)"
    ),
    offset: int = Query(
        ..., ge=0, description="Offset for pagination (required)"
    ),
    flight_code: Optional[str] = Query(None, description="Filter by flight name (optional)"),
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: None = Depends(require_admin)
) -> UnpaidCargoListResponse:
    """
    Get paginated list of unpaid cargo for a client.

    **ALL FILTER PARAMETERS ARE REQUIRED** - no defaults allowed.

    **Business Rule (NEW - Source of Truth)**:
    An "UNPAID cargo" is defined as:
    - Any record in `flight_cargo` table where `is_sent = TRUE`
    - NO dependency on `client_transaction_data`
    - Payments are stored separately and should NOT be used to determine unpaid cargo

    Amount is calculated as: `weight_kg * price_per_kg * USD_rate + extra_charge`
    """
    # Resolve all active code aliases so cargo/transactions stored under any
    # variant (extra_code, client_code, legacy_code) are correctly included.
    client_service = ClientService()
    client = await client_service.get_client_by_code(client_code.upper(), session)
    active_codes = client.active_codes if client else [client_code.upper()]

    return await CargoService.get_unpaid_cargo_list(
        client_code=active_codes,
        session=session,
        filter_type=filter_type,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
        flight_filter=flight_code
    )


# ============================================================================
# Flight Endpoints
# ============================================================================

@router.get(
    "/{client_code}/flights",
    response_model=FlightListResponse,
    summary="Get client flights",
    description="Get all flights associated with a client. FILTER PARAMETERS ARE REQUIRED."
)
async def get_client_flights(
    client_code: str,
    include_sheets: bool = Query(
        ..., description="Include flights from Google Sheets (required)"
    ),
    include_database: bool = Query(
        ..., description="Include flights from database (required)"
    ),
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: None = Depends(require_admin)
) -> FlightListResponse:
    """
    Get all flights for a client.

    **FILTER PARAMETERS ARE REQUIRED** - must explicitly specify sources.

    Combines flights from:
    - Database transactions (paid cargo) - if include_database=true
    - Database flight_cargo (sent cargo) - if include_database=true
    - Google Sheets - if include_sheets=true
    """
    return await VerificationService.get_client_flights(
        client_code=client_code.upper(),
        session=session,
        include_sheets=include_sheets,
        include_database=include_database
    )


@router.get(
    "/{client_code}/cargo/unpaid/flights",
    response_model=FlightListResponse,
    summary="Get flights with unpaid cargo",
    description="Get list of flights that have unpaid cargo for a client."
)
async def get_unpaid_cargo_flights(
    client_code: str,
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: None = Depends(require_admin)
) -> FlightListResponse:
    """
    Get flights that have unpaid (sent but not paid) cargo for a client.

    Source is always database (flight_cargo table).
    """
    client_service = ClientService()
    client = await client_service.get_client_by_code(client_code.upper(), session)
    active_codes = client.active_codes if client else [client_code.upper()]

    all_flights = await CargoService.get_unpaid_flights(
        client_code=active_codes,
        session=session
    )

    # Filter out flights that already have transactions (paid flights),
    # checking against all code aliases.
    unpaid_flights = []
    for flight_name in all_flights:
        existing_tx = await ClientTransactionDAO.get_by_client_code_and_flight(
            session, active_codes, flight_name
        )
        # Only include flights that have NO transactions (truly unpaid)
        if not existing_tx:
            unpaid_flights.append(flight_name)

    return FlightListResponse(
        flights=unpaid_flights,
        source="database"
    )


# ============================================================================
# Flight Payment Summary Endpoint
# ============================================================================

@router.get(
    "/{client_code}/flights/{flight_name}/payment-summary",
    response_model=FlightPaymentSummary,
    summary="Get flight payment summary",
    description="Calculate payment summary for all cargos of a client in a specific flight."
)
async def get_flight_payment_summary(
    client_code: str,
    flight_name: str,
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: None = Depends(require_admin)
) -> FlightPaymentSummary:
    """
    Calculate payment summary for ALL cargos of a specific client in a specific flight.

    Only cargos with is_sent=True are included.

    Returns:
    - total_weight
    - price_per_kg_usd
    - price_per_kg_uzs
    - extra_charge
    - total_payment
    - track_codes
    """
    client_service = ClientService()
    client = await client_service.get_client_by_code(client_code.upper(), session)
    active_codes = client.active_codes if client else [client_code.upper()]

    result = await CargoService.calculate_flight_payment(
        client_code=active_codes,
        flight_name=flight_name,
        session=session
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No sent cargos found for this client and flight"
        )

    return result
