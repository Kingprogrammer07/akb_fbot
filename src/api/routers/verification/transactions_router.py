"""Transactions router for payment history and mark-as-taken endpoints."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import (
    AdminJWTPayload,
    get_db,
    get_translator,
    require_permission,
)
from src.api.schemas.payment import PaymentEventListResponse
from src.api.schemas.verification import (
    CargoListResponse,
    FilterType,
    MarkTakenRequest,
    MarkTakenResponse,
    SortOrder,
    TransactionCargoImagesResponse,
    TransactionDetail,
    TransactionListResponse,
)
from src.api.services.verification import CargoService, PaymentService
from src.api.services.verification.payment_service import PaymentServiceError
from src.api.services.verification.transaction_view_service import TransactionViewService
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.services.client import ClientService

router = APIRouter(prefix="/transactions", tags=["Transactions"])


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
    pass


# ============================================================================
# Transaction List Endpoints
# ============================================================================

@router.get(
    "",
    response_model=TransactionListResponse,
    summary="Get transaction list for client",
    description="Get paginated, filtered list of transactions for a client. ALL FILTER PARAMETERS ARE REQUIRED.",
)
async def get_transactions(
    client_code: str = Query(..., min_length=1, description="Client code (required)"),
    filter_type: FilterType = Query(
        ...,
        description="Filter type (required): 'all', 'taken', 'not_taken', 'partial'",
    ),
    sort_order: SortOrder = Query(
        ...,
        description="Sort order (required): 'asc' or 'desc'",
    ),
    limit: int = Query(..., ge=1, le=100, description="Items per page (required)"),
    offset: int = Query(..., ge=0, description="Offset for pagination (required)"),
    flight_code: Optional[str] = Query(None, description="Filter by flight name (optional)"),
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: None = Depends(require_admin),
) -> TransactionListResponse:
    """
    Get paginated list of transactions for a client.

    **ALL FILTER PARAMETERS ARE REQUIRED** - no defaults allowed.

    **Filter types**:
    - `all`: All transactions
    - `taken`: Cargo marked as taken
    - `not_taken`: Cargo not yet taken
    - `partial`: Partially paid transactions

    **Sort order**:
    - `desc`: Newest first
    - `asc`: Oldest first
    """
    client_service = ClientService()
    client = await client_service.get_client_by_code(client_code.upper(), session)
    active_codes = client.active_codes if client else [client_code.upper()]

    transactions = await ClientTransactionDAO.get_filtered_transactions(
        session,
        active_codes,
        filter_type,
        sort_order,
        limit,
        offset,
        flight_code,
        include_hidden=True,
    )

    total_count = await ClientTransactionDAO.count_filtered_transactions_by_client_code(
        session,
        active_codes,
        filter_type,
        flight_code,
        include_hidden=True,
    )

    total_pages = max(1, (total_count + limit - 1) // limit)
    status_map = await TransactionViewService.get_status_map(
        session,
        transactions,
        active_codes_by_transaction={tx.id: active_codes for tx in transactions},
    )
    items = [
        TransactionViewService.build_transaction_summary(
            tx,
            status_map.get(tx.id),
        )
        for tx in transactions
    ]

    return TransactionListResponse(
        transactions=items,
        total_count=total_count,
        limit=limit,
        offset=offset,
        total_pages=total_pages,
        filter_type=filter_type,
        sort_order=sort_order,
        flight_filter=flight_code,
    )


@router.get(
    "/{transaction_id}",
    response_model=TransactionDetail,
    summary="Get transaction details",
    description="Get detailed information about a specific transaction.",
)
async def get_transaction_detail(
    transaction_id: int = Path(..., gt=0),
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: None = Depends(require_admin),
) -> TransactionDetail:
    """
    Get detailed information about a specific transaction.

    Includes payment_balance_difference showing debt/overpayment status.
    """
    tx = await ClientTransactionDAO.get_by_id(session, transaction_id)
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("admin-account-payment-transaction-not-found"),
        )

    client = await ClientService().get_client_by_code(tx.client_code, session)
    active_codes = client.active_codes if client and client.active_codes else [tx.client_code]
    status_context = await TransactionViewService.get_status_context(
        session,
        tx,
        active_codes,
    )
    return TransactionViewService.build_transaction_detail(tx, status_context)


# ============================================================================
# Mark as Taken Endpoint
# ============================================================================

@router.patch(
    "/{transaction_id}/status",
    response_model=MarkTakenResponse,
    summary="Mark transaction as cargo taken",
    description=(
        "Mark a transaction's cargo as taken by the client. "
        "Works regardless of payment status - admins may release cargo even "
        "for pending or partially-paid transactions. "
        "Every call is recorded in the admin audit log. "
        "Requires `cargo:update` permission."
    ),
)
async def mark_transaction_taken(
    transaction_id: int = Path(..., gt=0),
    request: MarkTakenRequest = None,
    admin: AdminJWTPayload = Depends(require_permission("cargo", "update")),
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
) -> MarkTakenResponse:
    """
    Mark a transaction's cargo as taken.

    **Requirements**:
    - Transaction must exist.
    - Cargo must not already be marked as taken.

    **Payment status**:
    - `paid`    - marked taken directly.
    - `partial` - workflow is force-closed (remaining_amount zeroed, debt preserved).
    - `pending` - allowed as-is; admin's explicit override.

    Every successful call writes an immutable `MARK_CARGO_TAKEN` entry to the
    admin audit log, recording which admin released the cargo and what the
    payment status was at that moment.
    """
    try:
        result = await PaymentService.mark_transaction_taken(
            transaction_id=transaction_id,
            admin_id=admin.admin_id,
            role_snapshot=admin.role_name,
            session=session,
        )

        return MarkTakenResponse(
            success=result["success"],
            transaction_id=result["transaction_id"],
            is_taken_away=result["is_taken_away"],
            taken_away_date=result.get("taken_away_date"),
            message=_("admin-verification-marked-as-taken"),
        )

    except PaymentServiceError as e:
        if e.error_code == "TRANSACTION_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_("admin-account-payment-transaction-not-found"),
            )
        if e.error_code == "ALREADY_TAKEN":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_("admin-verification-marked-as-taken"),
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=e.message,
        )


# ============================================================================
# Payment Events Endpoint
# ============================================================================

@router.get(
    "/{transaction_id}/events",
    response_model=PaymentEventListResponse,
    summary="Get payment events for transaction",
    description="Get all payment events (audit log) for a transaction.",
)
async def get_transaction_events(
    transaction_id: int = Path(..., gt=0),
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: None = Depends(require_admin),
) -> PaymentEventListResponse:
    """
    Get all payment events for a transaction.

    Payment events form an immutable audit log of all payments made.
    Each event records:
    - Amount paid (actual amount paid by client)
    - Payment provider (cash, click, payme)
    - Admin who approved
    - Timestamp

    A single transaction may have multiple payment events from different providers
    (partial payments are supported).
    """
    tx = await ClientTransactionDAO.get_by_id(session, transaction_id)
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("admin-account-payment-transaction-not-found"),
        )

    return await PaymentService.get_payment_events(transaction_id, session)


# ============================================================================
# Transaction Cargo Endpoint
# ============================================================================

@router.get(
    "/{transaction_id}/cargos",
    response_model=CargoListResponse,
    summary="Get cargos for transaction",
    description="Get cargo items (with photos) associated with a transaction.",
)
async def get_transaction_cargos(
    transaction_id: int = Path(..., gt=0),
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: None = Depends(require_admin),
) -> CargoListResponse:
    """
    Get cargo items associated with a transaction.

    Returns cargo details including:
    - Weight and price per kg
    - Photo file IDs (Telegram file_ids)
    - Comments
    - Sent status
    """
    return await CargoService.get_transaction_cargos(transaction_id, session)


# ============================================================================
# Cargo Images Endpoint
# ============================================================================

@router.get(
    "/{transaction_id}/cargo-images",
    response_model=TransactionCargoImagesResponse,
    summary="Get cargo images with Telegram URLs",
    description="Get cargo images for a transaction with resolved Telegram download URLs.",
)
async def get_transaction_cargo_images(
    transaction_id: int = Path(..., gt=0),
    type: Optional[Literal["unpaid"]] = Query(None),
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: None = Depends(require_admin),
) -> TransactionCargoImagesResponse:
    """
    Get cargo images with resolved Telegram URLs.

    This endpoint:
    1. Finds the transaction by ID
    2. Locates the related FlightCargo record
    3. Parses the photo_file_ids JSON (list of Telegram file_ids)
    4. Resolves each file_id to a Telegram download URL

    **Response includes**:
    - `transaction_id`: The transaction ID
    - `flight`: Flight name
    - `cargo_id`: FlightCargo ID (if found)
    - `images`: List of images with file_id and telegram_url
    - `total_count`: Number of images

    **Note**: If Telegram API fails to resolve a file_id, the telegram_url
    will be null but file_id will still be returned.
    """
    if type == "unpaid":
        return await CargoService.get_cargo_images_by_transaction_id(
            transaction_id,
            session,
            cargo_type="unpaid",
        )

    tx = await ClientTransactionDAO.get_by_id(session, transaction_id)
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("admin-account-payment-transaction-not-found"),
        )

    return await CargoService.get_cargo_images_by_transaction_id(transaction_id, session)
