"""
Payment State Calculator Service

This module provides a SINGLE SOURCE OF TRUTH for calculating transaction payment state
from payment events. All handlers MUST use this service to ensure consistency.

CRITICAL: This service is the authoritative source for payment calculations.
Never duplicate this logic elsewhere.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.dao.client_payment_event import ClientPaymentEventDAO
from src.infrastructure.tools.datetime_utils import get_current_time


class PaymentStateCalculator:
    """
    Service for calculating and updating transaction payment state.

    This service ensures:
    - Single source of truth for payment calculations
    - Atomic updates with row locking
    - Correct status derivation from events
    - Prevention of race conditions
    """

    @staticmethod
    async def recalculate_transaction_payment_state(
        session: AsyncSession,
        transaction_id: int,
        lock_row: bool = True
    ) -> ClientTransaction:
        """
        Recalculate and update transaction payment state from events.

        This is the ONLY function that should update payment_status, paid_amount,
        and remaining_amount fields.

        Args:
            session: Database session
            transaction_id: Transaction ID to recalculate
            lock_row: If True, use SELECT FOR UPDATE (default=True for safety)

        Returns:
            Updated ClientTransaction

        Process:
        1. Lock transaction row (if lock_row=True)
        2. Sum all payment events
        3. Calculate new state
        4. Update transaction fields
        5. Derive payment_type from events

        Formula:
            paid_amount = SUM(events.amount)
            remaining_amount = total_amount - paid_amount
            payment_status = 'pending' | 'partial' | 'paid'
            payment_type = derived from unique providers
        """
        from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO

        # Step 1: Lock transaction row to prevent race conditions
        if lock_row:
            query = select(ClientTransaction).where(
                ClientTransaction.id == transaction_id
            ).with_for_update()
        else:
            query = select(ClientTransaction).where(
                ClientTransaction.id == transaction_id
            )

        result = await session.execute(query)
        transaction = result.scalar_one_or_none()

        if not transaction:
            raise ValueError(f"Transaction {transaction_id} not found")

        # Step 2: Sum all payment events
        total_paid = await ClientPaymentEventDAO.get_total_paid_by_transaction_id(
            session, transaction_id
        )

        # Step 3: Get payment breakdown by provider
        breakdown = await ClientPaymentEventDAO.get_payment_breakdown_by_transaction_id(
            session, transaction_id
        )

        # Step 4: Calculate new state
        transaction.paid_amount = total_paid

        if transaction.total_amount and transaction.total_amount > 0:
            transaction.remaining_amount = float(transaction.total_amount) - total_paid
        else:
            # If total_amount not set, use summa as fallback
            total = float(transaction.summa or 0)
            transaction.remaining_amount = total - total_paid

        # Ensure remaining_amount never goes negative
        if transaction.remaining_amount < 0:
            transaction.remaining_amount = 0.0

        # Step 5: Determine payment status
        if total_paid == 0:
            transaction.payment_status = "pending"
        elif transaction.remaining_amount <= 0.01:  # Allow 1 kopek tolerance
            transaction.payment_status = "paid"
            transaction.remaining_amount = 0.0
            if not transaction.fully_paid_date:
                transaction.fully_paid_date = get_current_time()
        else:
            transaction.payment_status = "partial"

        # Step 6: Derive payment_type from events
        # Count unique non-zero providers
        active_providers = [
            provider for provider, amount in breakdown.items()
            if amount > 0
        ]

        if len(active_providers) == 0:
            # No payments yet
            transaction.payment_type = "online"  # Default
        elif len(active_providers) == 1:
            # Single provider
            provider = active_providers[0]
            if provider == "cash":
                transaction.payment_type = "cash"
            else:
                transaction.payment_type = "online"  # Click/Payme = online
        else:
            # Mixed providers
            transaction.payment_type = "mixed"

        # Step 7: Flush changes (caller must commit)
        await session.flush()
        await session.refresh(transaction)

        return transaction

    @staticmethod
    async def can_accept_payment(
        session: AsyncSession,
        transaction_id: int,
        amount: float
    ) -> tuple[bool, str]:
        """
        Check if transaction can accept a payment of given amount.

        Args:
            session: Database session
            transaction_id: Transaction ID
            amount: Payment amount to check

        Returns:
            (can_accept, reason) where:
            - can_accept: True if payment can be accepted
            - reason: Error message if cannot accept, empty if OK

        Validation Rules:
        1. Transaction must exist
        2. Transaction must not be fully paid
        3. Transaction must not be taken away
        4. Amount must be positive
        5. Amount must not exceed remaining amount (with 0.01 tolerance)
        """
        from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO

        # Get transaction
        transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)
        if not transaction:
            return False, "Transaction not found"

        # Check if already taken
        if transaction.is_taken_away:
            return False, "Transaction already marked as taken"

        # Check if already fully paid
        if transaction.payment_status == "paid":
            return False, "Transaction already fully paid"

        # Check amount is positive
        if amount <= 0:
            return False, "Payment amount must be positive"

        # Check amount doesn't exceed remaining
        remaining = transaction.remaining_amount or 0.0
        if amount > remaining + 0.01:  # Allow 1 kopek tolerance
            return False, f"Payment amount {amount:.2f} exceeds remaining {remaining:.2f}"

        return True, ""

    @staticmethod
    async def get_payment_summary(
        session: AsyncSession,
        transaction_id: int
    ) -> dict:
        """
        Get comprehensive payment summary for a transaction.

        Returns:
            {
                'total_amount': float,
                'paid_amount': float,
                'remaining_amount': float,
                'payment_status': str,
                'payment_type': str,
                'breakdown': {'cash': float, 'click': float, 'payme': float},
                'event_count': int,
                'is_taken_away': bool
            }
        """
        from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO

        transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)
        if not transaction:
            raise ValueError(f"Transaction {transaction_id} not found")

        breakdown = await ClientPaymentEventDAO.get_payment_breakdown_by_transaction_id(
            session, transaction_id
        )

        event_count = await ClientPaymentEventDAO.count_by_transaction_id(
            session, transaction_id
        )

        return {
            'total_amount': float(transaction.total_amount or transaction.summa or 0),
            'paid_amount': float(transaction.paid_amount or 0),
            'remaining_amount': float(transaction.remaining_amount or 0),
            'payment_status': transaction.payment_status,
            'payment_type': transaction.payment_type,
            'breakdown': breakdown,
            'event_count': event_count,
            'is_taken_away': transaction.is_taken_away,
            'flight': transaction.reys,
            'client_code': transaction.client_code
        }
