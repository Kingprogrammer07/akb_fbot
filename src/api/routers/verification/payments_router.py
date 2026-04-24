"""Payments router for processing new payments."""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_translator
from src.api.services.verification import PaymentService
from src.api.services.verification.payment_service import PaymentServiceError
from src.infrastructure.database.dao.payment_card import PaymentCardDAO

from src.api.schemas.payment import (
    ProcessPaymentRequest,
    ProcessExistingTransactionPaymentRequest,
    ProcessPaymentResponse,
    PaymentErrorResponse,
    ActiveCardResponse,
)

router = APIRouter(prefix="/payments", tags=["Payments"])


class CardWithBalanceItem(BaseModel):
    id: int
    card_number: str
    full_name: str
    is_active: bool
    created_at: datetime
    total_collected: float
    payment_count: int


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
# Payment Processing Endpoints
# ============================================================================

@router.post(
    "/process",
    response_model=ProcessPaymentResponse,
    responses={
        400: {"model": PaymentErrorResponse, "description": "Validation error or invalid paid_amount"},
        404: {"model": PaymentErrorResponse, "description": "Client or cargo not found"},
        409: {"model": PaymentErrorResponse, "description": "Payment already exists"},
        500: {"model": PaymentErrorResponse, "description": "Processing error"},
    },
    summary="Process payment for unpaid cargo",
    description="Process a new payment (cash or online) for unpaid cargo. PAID_AMOUNT IS REQUIRED."
)
async def process_payment(
    request: ProcessPaymentRequest,
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: None = Depends(require_admin)
) -> ProcessPaymentResponse:
    """
    Process payment for unpaid cargo.

    **REQUIRED FIELDS**:
    - `client_code`: Client code
    - `cargo_id`: FlightCargo.id
    - `flight`: Flight name
    - `payment_type`: 'cash', 'click', or 'payme'
    - `paid_amount`: Actual amount paid by client (REQUIRED, in UZS)
    - `admin_id`: Admin's Telegram ID

    **Payment types**:
    - `cash`: Cash payment - cargo is automatically marked as taken
    - `click`: Click online payment - cargo remains not taken
    - `payme`: Payme online payment - cargo remains not taken

    **Response includes**:
    - `expected_amount`: Calculated expected payment (weight * price * rate + extra_charge)
    - `paid_amount`: Actual amount paid by client
    - `payment_balance_difference`: paid - expected (negative=debt, positive=overpaid)

    **Side effects**:
    - Creates new `ClientTransaction` record with `summa = expected_amount`
    - Creates `ClientPaymentEvent` audit record with `amount = paid_amount`
    - Sets `payment_balance_difference` on transaction
    - Sends notification to user (for cash payments)
    - Sends notification to payment channel

    **Validation rules**:
    - paid_amount must be > 0
    - paid_amount cannot exceed expected_amount * 2 (anti-error guard)
    """
    try:
        return await PaymentService.process_unpaid_cargo_payment(
            request=request,
            session=session,
            translator=_
        )

    except PaymentServiceError as e:
        error_code_to_status = {
            "CLIENT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
            "CARGO_NOT_FOUND": status.HTTP_404_NOT_FOUND,
            "CARGO_VALIDATION_FAILED": status.HTTP_400_BAD_REQUEST,
            "INVALID_PAID_AMOUNT": status.HTTP_400_BAD_REQUEST,
            "PAYMENT_EXISTS": status.HTTP_409_CONFLICT,
            "PROCESSING_FAILED": status.HTTP_500_INTERNAL_SERVER_ERROR,
        }

        http_status = error_code_to_status.get(
            e.error_code, status.HTTP_500_INTERNAL_SERVER_ERROR
        )

        raise HTTPException(
            status_code=http_status,
            detail={
                "error": e.message,
                "error_code": e.error_code,
                "details": e.details
            }
        )


@router.post(
    "/process-existing",
    response_model=ProcessPaymentResponse,
    responses={
        400: {"model": PaymentErrorResponse, "description": "Validation error or invalid paid_amount"},
        404: {"model": PaymentErrorResponse, "description": "Transaction not found"},
        409: {"model": PaymentErrorResponse, "description": "Cargo already taken"},
        500: {"model": PaymentErrorResponse, "description": "Processing error"},
    },
    summary="Process payment for existing transaction",
    description="Process additional payment for existing transaction (partial payments). PAID_AMOUNT IS REQUIRED."
)
async def process_existing_payment(
    request: ProcessExistingTransactionPaymentRequest,
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: None = Depends(require_admin)
) -> ProcessPaymentResponse:
    """
    Process payment for existing transaction (partial payments).

    **REQUIRED FIELDS**:
    - `transaction_id`: Existing transaction ID
    - `payment_type`: 'cash', 'click', or 'payme'
    - `paid_amount`: Actual amount paid by client (REQUIRED, in UZS)
    - `admin_id`: Admin's Telegram ID

    Use this endpoint when:
    - A transaction exists but is only partially paid
    - Need to add additional payment to existing transaction

    **Response includes**:
    - `expected_amount`: Original expected payment from transaction
    - `paid_amount`: Amount paid in this event
    - `payment_balance_difference`: total_paid - expected (negative=debt, positive=overpaid)

    **Business rules**:
    - Transaction must exist
    - Cargo must not already be taken
    - Multiple payment events from different providers are allowed (partial payments)

    **Validation rules**:
    - paid_amount must be > 0
    - paid_amount cannot exceed expected_amount * 2 (anti-error guard)
    """
    try:
        return await PaymentService.process_existing_transaction_payment(
            request=request,
            session=session,
            translator=_
        )

    except PaymentServiceError as e:
        error_code_to_status = {
            "TRANSACTION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
            "CLIENT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
            "CARGO_ALREADY_TAKEN": status.HTTP_409_CONFLICT,
            "INVALID_PAID_AMOUNT": status.HTTP_400_BAD_REQUEST,
            "PROCESSING_FAILED": status.HTTP_500_INTERNAL_SERVER_ERROR,
        }

        http_status = error_code_to_status.get(
            e.error_code, status.HTTP_500_INTERNAL_SERVER_ERROR
        )

        raise HTTPException(
            status_code=http_status,
            detail={
                "error": e.message,
                "error_code": e.error_code,
                "details": e.details
            }
        )


# ============================================================================
# Cards Endpoints
# ============================================================================


@router.get(
    "/cards",
    response_model=list[CardWithBalanceItem],
    summary="List all payment cards with collected balance",
    description="Returns all company payment cards (active and inactive) with their total collected amount.",
)
async def get_cards_with_balance(
    session: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin),
) -> list[CardWithBalanceItem]:
    """List all payment cards with SUM(payment_events.amount) as balance."""
    rows = await PaymentCardDAO.get_all_with_balance(session)
    return [CardWithBalanceItem(**row) for row in rows]


# ============================================================================
# Active Cards Endpoint
# ============================================================================

@router.get(
    "/active-cards/random",
    response_model=ActiveCardResponse,
    responses={
        404: {"model": PaymentErrorResponse, "description": "No active cards found"},
    },
    summary="Get random active payment card",
    description="Returns a random active payment card for card payments."
)
async def get_random_active_card(
    session: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin)
) -> ActiveCardResponse:
    """
    Get a random active payment card.

    Returns a card from `payment_cards` table where `is_active = true`.
    Used by frontend/WebApp to display card details for card payments.
    """
    card = await PaymentCardDAO.get_random_active(session)

    if not card:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "No active payment cards found",
                "error_code": "NO_ACTIVE_CARDS",
                "details": None
            }
        )

    return ActiveCardResponse(
        card_number=card.card_number,
        holder_name=card.full_name,
        bank_name=None
    )
