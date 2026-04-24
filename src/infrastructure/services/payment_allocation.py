"""Payment Allocation Service - FIFO debt distribution."""

from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.tools.datetime_utils import get_current_time


@dataclass
class DebtAllocationItem:
    """Represents a single debt allocation."""

    transaction_id: int
    flight_name: str
    row_number: int
    previous_debt: float
    allocated_amount: float
    remaining_debt: float
    is_fully_paid: bool
    track_codes: list[str] = field(default_factory=list)


@dataclass
class PaymentAllocationResult:
    """Result of payment allocation."""

    total_allocated: float
    remaining_credit: float  # Amount left after all debts paid (becomes user credit)
    allocations: list[DebtAllocationItem]
    fully_paid_transactions: list[int]  # IDs of transactions that became fully paid
    new_balance: float  # New total balance after allocation

    @property
    def has_fully_paid_debts(self) -> bool:
        """Check if any debts were fully paid."""
        return len(self.fully_paid_transactions) > 0


class PaymentAllocationService:
    """
    Service for FIFO debt allocation.

    When a payment is received, it is applied to the oldest unpaid
    transactions first (FIFO - First In First Out).

    Business Rules:
    - payment_balance_difference < 0 means debt (client owes money)
    - payment_balance_difference > 0 means credit (client overpaid)
    - payment_balance_difference = 0 means balanced

    The service:
    1. Loads all unpaid transactions (negative payment_balance_difference) ordered by created_at ASC
    2. Distributes payment to oldest debts first
    3. Marks transactions as fully paid when debt reaches 0
    4. Returns allocation report for notifications
    """

    @staticmethod
    async def get_unpaid_transactions(
        session: AsyncSession, client_code: str
    ) -> list[ClientTransaction]:
        """
        Get all transactions with negative payment_balance_difference (debts).

        Ordered by created_at ASC (oldest first - FIFO).
        Uses SELECT FOR UPDATE to prevent race conditions.
        """
        result = await session.execute(
            select(ClientTransaction)
            .where(
                ClientTransaction.client_code == client_code,
                ClientTransaction.payment_balance_difference < 0,
                ~ClientTransaction.reys.like("WALLET_ADJ:%"),
            )
            .order_by(ClientTransaction.created_at.asc())
            .with_for_update()  # Lock rows to prevent race conditions
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_client_balance(session: AsyncSession, client_code: str) -> float:
        """
        Get total payment_balance_difference for a client.

        This is the single source of truth for wallet balance.
        """
        return await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
            session, client_code
        )

    @staticmethod
    async def apply_payment(
        session: AsyncSession,
        client_code: str,
        amount: float,
        admin_id: Optional[int] = None,
        track_codes_getter: Optional[callable] = None,
    ) -> PaymentAllocationResult:
        """
        Apply a payment using FIFO debt distribution.

        Args:
            session: Database session
            client_code: Client code
            amount: Payment amount (positive value)
            admin_id: Admin who approved the payment (optional)
            track_codes_getter: Optional async function to get track codes for a transaction
                                Signature: async (flight_name: str, client_code: str) -> list[str]

        Returns:
            PaymentAllocationResult with allocation details

        Algorithm:
        1. Load all unpaid transactions ordered by created_at ASC
        2. For each transaction:
           - Calculate remaining debt = abs(payment_balance_difference)
           - If payment >= debt: mark as paid, payment -= debt
           - If payment < debt: reduce debt by payment, payment = 0
        3. If payment still > 0: create credit transaction
        4. Return allocation report
        """
        if amount <= 0:
            raise ValueError("Payment amount must be positive")

        remaining_payment = amount
        allocations: list[DebtAllocationItem] = []
        fully_paid_ids: list[int] = []

        # Step 1: Get all unpaid transactions (oldest first)
        unpaid_transactions = await PaymentAllocationService.get_unpaid_transactions(
            session, client_code
        )

        # Step 2: Distribute payment (FIFO)
        for tx in unpaid_transactions:
            if remaining_payment <= 0:
                break

            # Calculate debt for this transaction
            debt = abs(float(tx.payment_balance_difference))
            previous_debt = debt

            # Get track codes if getter provided
            track_codes = []
            if track_codes_getter and tx.reys:
                try:
                    track_codes = await track_codes_getter(tx.reys, client_code)
                except Exception:
                    track_codes = []

            if remaining_payment >= debt:
                # Fully pay this debt
                allocated = debt
                tx.payment_balance_difference = 0
                tx.payment_status = "paid"
                if not getattr(tx, "fully_paid_date", None):
                    tx.fully_paid_date = get_current_time()
                remaining_payment -= debt

                fully_paid_ids.append(tx.id)
                is_fully_paid = True
            else:
                # Partially pay this debt
                allocated = remaining_payment
                tx.payment_balance_difference = (
                    float(tx.payment_balance_difference) + remaining_payment
                )
                remaining_payment = 0
                is_fully_paid = False

            allocations.append(
                DebtAllocationItem(
                    transaction_id=tx.id,
                    flight_name=tx.reys,
                    row_number=tx.qator_raqami,
                    previous_debt=previous_debt,
                    allocated_amount=allocated,
                    remaining_debt=abs(float(tx.payment_balance_difference)),
                    is_fully_paid=is_fully_paid,
                    track_codes=track_codes,
                )
            )

        # Step 3: If payment still remaining, it becomes user credit
        credit_amount = remaining_payment
        total_allocated = amount - remaining_payment

        # If there's remaining credit after paying all debts, add it to the
        # last allocated transaction's pbd (making it positive = credit).
        # No WALLET_ADJ pseudo-transactions needed.
        if credit_amount > 0 and allocations:
            # Add credit to the last transaction that was allocated
            last_alloc = allocations[-1]
            last_tx = None
            for tx in unpaid_transactions:
                if tx.id == last_alloc.transaction_id:
                    last_tx = tx
                    break
            if last_tx:
                last_tx.payment_balance_difference = (
                    float(last_tx.payment_balance_difference) + credit_amount
                )

        # Flush changes
        await session.flush()

        # Step 4: Calculate new balance
        new_balance = await PaymentAllocationService.get_client_balance(
            session, client_code
        )

        return PaymentAllocationResult(
            total_allocated=total_allocated,
            remaining_credit=credit_amount,
            allocations=allocations,
            fully_paid_transactions=fully_paid_ids,
            new_balance=new_balance,
        )

    @staticmethod
    async def create_debt_transaction(
        session: AsyncSession,
        client_code: str,
        telegram_id: int,
        flight_name: str,
        row_number: int,
        total_amount: float,
        weight: str,
        payment_type: str = "online",
    ) -> ClientTransaction:
        """
        Create a new transaction with debt (negative payment_balance_difference).

        This is called when cargo is sent to client but not yet paid.
        The debt = -total_amount (negative because client owes money).
        """

        data = {
            "telegram_id": telegram_id,
            "client_code": client_code,
            "qator_raqami": 0,  # Always 0, ignoring input row_number
            "reys": flight_name,
            "summa": total_amount,
            "vazn": weight,
            "payment_type": payment_type,
            "payment_status": "pending",
            "paid_amount": 0,
            "total_amount": total_amount,
            "remaining_amount": total_amount,
            "payment_balance_difference": -total_amount,  # Negative = debt
            "is_taken_away": False,
        }

        return await ClientTransactionDAO.create(session, data)

    @staticmethod
    async def apply_payment_to_specific_transaction(
        session: AsyncSession,
        transaction_id: int,
        amount: float,
        admin_id: Optional[int] = None,
    ) -> tuple[ClientTransaction, bool]:
        """
        Apply payment to a specific transaction (not FIFO).

        Used when admin wants to pay for a specific cargo/flight.
        Returns the transaction and whether it became fully paid.

        This method updates the transaction's payment_balance_difference
        and marks it as paid if the debt is cleared.
        """
        tx = await session.get(ClientTransaction, transaction_id)
        if not tx:
            raise ValueError(f"Transaction {transaction_id} not found")

        current_balance = float(tx.payment_balance_difference)

        # If balance is already >= 0, this is a credit/overpayment transaction
        if current_balance >= 0:
            # Add to existing credit
            tx.payment_balance_difference = current_balance + amount
            await session.flush()
            return tx, True

        # Calculate new balance
        new_balance = current_balance + amount
        tx.payment_balance_difference = new_balance

        is_fully_paid = new_balance >= 0
        if is_fully_paid:
            tx.payment_status = "paid"
            tx.remaining_amount = 0
            tx.paid_amount = float(tx.total_amount or tx.summa)
            if not getattr(tx, "fully_paid_date", None):
                tx.fully_paid_date = get_current_time()
        else:
            # Update paid_amount based on how much debt was reduced
            debt_reduced = amount
            tx.paid_amount = float(tx.paid_amount or 0) + debt_reduced
            tx.remaining_amount = abs(new_balance)

        await session.flush()
        return tx, is_fully_paid

    @staticmethod
    async def recalculate_transaction_balance(
        session: AsyncSession, transaction_id: int
    ) -> ClientTransaction:
        """
        Recalculate payment_balance_difference for a transaction based on its events.

        payment_balance_difference = total_paid_from_events - total_amount

        If positive: overpaid (credit)
        If negative: underpaid (debt)
        If zero: balanced
        """
        from src.infrastructure.database.dao.client_payment_event import (
            ClientPaymentEventDAO,
        )

        tx = await session.get(ClientTransaction, transaction_id)
        if not tx:
            raise ValueError(f"Transaction {transaction_id} not found")

        # Get total paid from events
        total_paid = await ClientPaymentEventDAO.get_total_paid_by_transaction_id(
            session, transaction_id
        )

        # Get expected amount
        expected = float(tx.total_amount or tx.summa or 0)

        # Calculate balance difference
        tx.payment_balance_difference = total_paid - expected
        tx.paid_amount = total_paid
        tx.remaining_amount = max(0, expected - total_paid)

        if tx.remaining_amount <= 0:
            tx.payment_status = "paid"
            if not getattr(tx, "fully_paid_date", None):
                tx.fully_paid_date = get_current_time()
        elif total_paid > 0:
            tx.payment_status = "partial"
        else:
            tx.payment_status = "pending"

        await session.flush()
        return tx

    @staticmethod
    async def process_refund(
        session: AsyncSession, client_code: str, amount: float
    ) -> float:
        """
        Deduct amount from client's positive balance (credit) to process a refund.

        Decreases payment_balance_difference of existing transactions.
        Does NOT create pseudo-transactions.

        Args:
            amount: Amount to refund (positive value)

        Returns:
            Remaining amount that could not be deducted (should be 0 if balance check passed)
        """
        # Get credit transactions (payment_balance_difference > 0)
        # Ordered by created_at ASC (FIFO)
        result = await session.execute(
            select(ClientTransaction)
            .where(
                ClientTransaction.client_code == client_code,
                ClientTransaction.payment_balance_difference > 0,
            )
            .order_by(ClientTransaction.created_at.asc())
            .with_for_update()
        )
        credit_txs = list(result.scalars().all())

        remaining = amount
        for tx in credit_txs:
            if remaining <= 0:
                break

            credit = float(tx.payment_balance_difference)
            to_deduct = min(credit, remaining)

            tx.payment_balance_difference = credit - to_deduct
            remaining -= to_deduct

        await session.flush()
        return remaining
