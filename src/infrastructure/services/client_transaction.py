"""Client Transaction Service."""

from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.models.client_transaction import ClientTransaction


class ClientTransactionService:
    """Service layer for ClientTransaction operations."""

    async def get_user_transactions(
        self, telegram_id: int, session: AsyncSession
    ) -> list[ClientTransaction]:
        """Get all transactions for a user."""
        return await ClientTransactionDAO.get_by_telegram_id(session, telegram_id)

    async def check_payment_exists(
        self,
        client_code: str,
        reys: str,
        qator_raqami: int = 0,
        session: AsyncSession = None,
    ) -> bool:
        """Check if payment already made for this flight."""
        return await ClientTransactionDAO.check_payment_exists(
            session, client_code, reys
        )

    async def create_transaction(
        self,
        telegram_id: int,
        client_code: str,
        qator_raqami: int,
        reys: str,
        summa: float,
        vazn: str,
        session: AsyncSession,
        payment_receipt_file_id: str | None = None,
        payment_type: str = "online",
        is_taken_away: bool = False,
        taken_away_date: datetime | None = None,
        payment_status: str = "paid",
        paid_amount: float | None = None,
        total_amount: float | None = None,
        remaining_amount: float | None = None,
        payment_deadline: datetime | None = None,
        existing_tx: ClientTransaction | None = None,
    ) -> ClientTransaction:
        """Create a new payment transaction or update an existing pending one."""
        # Set defaults for partial payment fields
        if paid_amount is None:
            paid_amount = summa
        if total_amount is None:
            total_amount = summa
        if remaining_amount is None:
            remaining_amount = (
                0.0 if payment_status == "paid" else (total_amount - paid_amount)
            )

        if existing_tx:
            # Update existing transaction instead of creating a new one.
            # Also update qator_raqami so a pending-debt row (qator_raqami=0)
            # gets the real cargo row number once it's actually paid.
            # client_code ni canonical kod bilan sinxronlaymiz — turli yo'llarda
            # bir xil kod yozilishi uchun (dublikat oldini olish).
            if client_code:
                existing_tx.client_code = client_code
            existing_tx.qator_raqami = qator_raqami
            existing_tx.summa = summa
            existing_tx.vazn = vazn
            if payment_receipt_file_id:
                existing_tx.payment_receipt_file_id = payment_receipt_file_id
            existing_tx.payment_type = payment_type
            if is_taken_away:
                existing_tx.is_taken_away = True
            if taken_away_date:
                existing_tx.taken_away_date = taken_away_date
            existing_tx.payment_status = payment_status
            existing_tx.paid_amount = paid_amount
            existing_tx.total_amount = total_amount
            existing_tx.remaining_amount = remaining_amount
            existing_tx.payment_deadline = payment_deadline

            # Since existing_tx is already bound to the session (we just fetched it),
            # we just need to return it. Changes will be flushed/committed by caller.
            return existing_tx

        data = {
            "telegram_id": telegram_id,
            "client_code": client_code,
            "qator_raqami": qator_raqami,
            "reys": reys,
            "summa": summa,
            "vazn": vazn,
            "payment_receipt_file_id": payment_receipt_file_id,
            "payment_type": payment_type,
            "is_taken_away": is_taken_away,
            "taken_away_date": taken_away_date,
            "payment_status": payment_status,
            "paid_amount": paid_amount,
            "total_amount": total_amount,
            "remaining_amount": remaining_amount,
            "payment_deadline": payment_deadline,
        }
        return await ClientTransactionDAO.create(session, data)

    async def count_transactions_by_telegram_id(
        self, telegram_id: int, session: AsyncSession
    ) -> int:
        """Count total transactions for a user (deprecated, use count_transactions_by_client_code)."""
        return await ClientTransactionDAO.count_by_telegram_id(session, telegram_id)

    async def count_transactions_by_client_code(
        self, client_code: str | list[str], session: AsyncSession
    ) -> int:
        """Count total transactions for a client code or list of codes."""
        return await ClientTransactionDAO.count_by_client_code(session, client_code)

    async def count_taken_away_by_telegram_id(
        self, telegram_id: int, session: AsyncSession
    ) -> int:
        """Count taken away cargo for a user (deprecated, use count_taken_away_by_client_code)."""
        return await ClientTransactionDAO.count_taken_away(session, telegram_id)

    async def count_taken_away_by_client_code(
        self, client_code: str | list[str], session: AsyncSession
    ) -> int:
        """Count taken away cargo for a client code or list of codes."""
        return await ClientTransactionDAO.count_taken_away_by_client_code(
            session, client_code
        )

    async def get_latest_transaction_by_telegram_id(
        self, telegram_id: int, session: AsyncSession
    ) -> ClientTransaction | None:
        """Get latest transaction for a user (deprecated, use get_latest_transaction_by_client_code)."""
        return await ClientTransactionDAO.get_latest_by_telegram_id(
            session, telegram_id
        )

    async def get_latest_transaction_by_client_code(
        self, client_code: str, session: AsyncSession
    ) -> ClientTransaction | None:
        """Get latest transaction for a client code."""
        return await ClientTransactionDAO.get_latest_by_client_code(
            session, client_code
        )

    async def get_transactions_by_telegram_id(
        self, telegram_id: int, session: AsyncSession, limit: int = 10, offset: int = 0
    ) -> list[ClientTransaction]:
        """Get paginated transactions for a user."""
        return await ClientTransactionDAO.get_by_telegram_id_paginated(
            session, telegram_id, limit, offset
        )

    async def get_filtered_transactions(
        self,
        client_code: str | list[str],
        session: AsyncSession,
        filter_type: str,
        sort_order: str,
        limit: int,
        offset: int,
        flight_code: str | None = None,
    ) -> list[ClientTransaction]:
        """Get filtered and sorted transactions for a client code or list of codes."""
        return await ClientTransactionDAO.get_filtered_transactions(
            session, client_code, filter_type, sort_order, limit, offset, flight_code
        )

    async def get_filtered_transactions_by_client_code(
        self,
        client_code: str | list[str],
        session: AsyncSession,
        filter_type: str,
        sort_order: str,
        limit: int,
        offset: int,
        flight_code: str | None = None,
    ) -> list[ClientTransaction]:
        """Get filtered and sorted transactions by client_code or list of codes."""
        return await ClientTransactionDAO.get_filtered_transactions(
            session, client_code, filter_type, sort_order, limit, offset, flight_code
        )

    async def count_filtered_transactions(
        self,
        telegram_id: int,
        session: AsyncSession,
        filter_type: str,
        flight_code: str | None = None,
    ) -> int:
        """Count filtered transactions (deprecated, use count_filtered_transactions_by_client_code)."""
        return await ClientTransactionDAO.count_filtered_transactions(
            session, telegram_id, filter_type, flight_code
        )

    async def count_filtered_transactions_by_client_code(
        self,
        client_code: str | list[str],
        session: AsyncSession,
        filter_type: str,
        flight_code: str | None = None,
    ) -> int:
        """Count filtered transactions by client_code or list of codes."""
        return await ClientTransactionDAO.count_filtered_transactions_by_client_code(
            session, client_code, filter_type, flight_code
        )

    async def get_transactions_by_flight(
        self, flight_code: str, session: AsyncSession
    ) -> list[ClientTransaction]:
        """Get all transactions for a specific flight."""
        return await ClientTransactionDAO.get_by_flight(session, flight_code)

    async def mark_as_taken(self, transaction_id: int, session: AsyncSession) -> bool:
        """Mark a transaction as cargo taken."""
        return await ClientTransactionDAO.mark_as_taken(session, transaction_id)

    async def get_unique_flights_by_telegram_id(
        self, telegram_id: int, session: AsyncSession
    ) -> list[str]:
        """Get unique flight codes for a telegram user."""
        return await ClientTransactionDAO.get_unique_flights_by_telegram_id(
            session, telegram_id
        )

    async def get_unique_flights_by_client_code(
        self, client_code: str | list[str], session: AsyncSession
    ) -> list[str]:
        """Get unique flight codes for a client code or list of codes."""
        return await ClientTransactionDAO.get_unique_flights_by_client_code(
            session, client_code
        )
