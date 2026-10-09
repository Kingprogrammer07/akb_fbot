"""Payment History Service.

Service layer for building client transaction history responses.
Uses DAO layer for all database access — no external API calls.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.client_payment_event import ClientPaymentEventDAO
from src.infrastructure.database.models.client_transaction import NON_FLIGHT_REYS_PREFIXES
from src.infrastructure.services.flight_display import (
    FLIGHT_PLACEHOLDER,
    FlightDisplay,
)
from src.api.schemas.payment import (
    PaymentBreakdownSchema,
    TransactionHistoryItemSchema,
    TransactionHistoryResponse,
)

logger = logging.getLogger(__name__)


async def get_client_transaction_history(
    session: AsyncSession,
    client_code: str | list[str],
    limit: int,
    offset: int,
) -> TransactionHistoryResponse:
    """
    Build paginated transaction history for a client.

    Args:
        session: Async database session.
        client_code: The authenticated client's code.
        limit: Page size.
        offset: Number of records to skip.

    Returns:
        TransactionHistoryResponse with items, total_count, limit, offset.
    """
    # Fetch paginated transactions.  ``get_filtered_transactions`` defaults to
    # ``include_hidden=True``, so UZPOST / WALLET_ADJ / SYS_ADJ rows are listed
    # as well, although the count below excludes them.
    transactions = await ClientTransactionDAO.get_filtered_transactions(
        session=session,
        client_code=client_code,
        filter_type="all",
        sort_order="desc",
        limit=limit,
        offset=offset,
    )

    total_count = await ClientTransactionDAO.count_filtered_transactions_by_client_code(
        session=session,
        client_code=client_code,
        filter_type="all",
    )

    # Every code is tried, not just the first: a client may hold a
    # pre-conversion alias alongside its current code.  The flights come from
    # the client's own transactions, so a missing alias is minted.
    display = await FlightDisplay.for_client(session, client_code, mint_missing=True)

    items: list[TransactionHistoryItemSchema] = []
    for tx in transactions:
        # Build payment breakdown for paid / partial transactions
        breakdown = PaymentBreakdownSchema()
        if tx.payment_status in ("paid", "partial"):
            raw = await ClientPaymentEventDAO.get_payment_breakdown_by_transaction_id(
                session, tx.id
            )
            breakdown = PaymentBreakdownSchema(
                click=float(raw.get("click", 0) or 0),
                payme=float(raw.get("payme", 0) or 0),
                cash=float(raw.get("cash", 0) or 0),
                card=float(raw.get("card", 0) or 0),
            )

        # The real flight name never reaches the user; a bookkeeping row names
        # no flight and keeps the placeholder.
        if tx.reys.startswith(NON_FLIGHT_REYS_PREFIXES):
            display_flight = FLIGHT_PLACEHOLDER
        else:
            display_flight = await display.label(session, tx.reys)

        items.append(
            TransactionHistoryItemSchema(
                id=tx.id,
                flight_name=display_flight,
                total_amount=float(tx.total_amount) if tx.total_amount is not None else 0.0,
                paid_amount=float(tx.paid_amount) if tx.paid_amount is not None else 0.0,
                remaining_amount=float(tx.remaining_amount) if tx.remaining_amount is not None else 0.0,
                payment_status=tx.payment_status or "pending",
                payment_type=tx.payment_type or "online",
                is_taken_away=bool(tx.is_taken_away),
                created_at=tx.created_at,
                breakdown=breakdown,
            )
        )

    return TransactionHistoryResponse(
        items=items,
        total_count=total_count,
        limit=limit,
        offset=offset,
    )
