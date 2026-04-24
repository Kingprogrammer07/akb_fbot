"""Payment History API Router.

GET /api/v1/payments/history — paginated transaction history for the
authenticated client, sourced strictly from the database.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user
from src.api.schemas.payment import TransactionHistoryResponse
from src.api.services.payment_history_service import get_client_transaction_history
from src.infrastructure.database.models.client import Client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["Payment History"])


@router.get(
    "/history",
    response_model=TransactionHistoryResponse,
    summary="Get paginated payment / transaction history",
    description=(
        "Returns the authenticated client's transaction history "
        "(To'lovlar tarixi) with payment breakdowns. "
        "Excludes internal WALLET_ADJ pseudo-transactions."
    ),
)
async def get_payment_history(
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    current_user: Client = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> TransactionHistoryResponse:
    """Get paginated transaction and payment history for the authenticated client."""
    if not current_user.client_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client code not set for this user",
        )

    return await get_client_transaction_history(
        session=session,
        client_code=current_user.active_codes,
        limit=limit,
        offset=offset,
    )
