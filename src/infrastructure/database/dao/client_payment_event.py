"""Client Payment Event DAO."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.client_payment_event import ClientPaymentEvent
from src.infrastructure.tools.money_utils import money


class ClientPaymentEventDAO:
    """Data Access Object for ClientPaymentEvent operations."""

    @staticmethod
    async def create(
        session: AsyncSession,
        transaction_id: int,
        payment_provider: str,  # REQUIRED: 'cash', 'card', 'click', 'payme', 'wallet'
        amount: float,
        approved_by_admin_id: int | None = None,
        payment_type: str = 'online',  # Deprecated, kept for compatibility
        payment_card_id: int | None = None,
    ) -> ClientPaymentEvent:
        """
        Create a new payment event.

        Args:
            session: Database session
            transaction_id: ID of the transaction
            payment_provider: REQUIRED - 'cash', 'card', 'click', 'payme', or 'wallet'
            amount: Payment amount
            approved_by_admin_id: Admin who approved (optional)
            payment_type: DEPRECATED - kept for backward compatibility

        Returns:
            ClientPaymentEvent: Created payment event

        Raises:
            ValueError: If payment_provider is not valid
        """
        valid_providers = {'cash', 'click', 'payme', 'card', 'wallet'}
        if payment_provider not in valid_providers:
            raise ValueError(
                f"Invalid payment_provider: {payment_provider}. "
                f"Must be one of: {valid_providers}"
            )

        event = ClientPaymentEvent(
            transaction_id=transaction_id,
            payment_type=payment_type,
            amount=money(amount),
            approved_by_admin_id=approved_by_admin_id,
            payment_provider=payment_provider,
            payment_card_id=payment_card_id,
        )
        session.add(event)
        await session.flush()
        await session.refresh(event)
        return event

    @staticmethod
    async def get_by_transaction_id(
        session: AsyncSession,
        transaction_id: int
    ) -> list[ClientPaymentEvent]:
        """Get all payment events for a transaction, ordered by created_at."""
        result = await session.execute(
            select(ClientPaymentEvent)
            .where(ClientPaymentEvent.transaction_id == transaction_id)
            .order_by(ClientPaymentEvent.created_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_total_paid_by_transaction_id(
        session: AsyncSession,
        transaction_id: int
    ) -> float:
        """Calculate total paid amount from all events for a transaction."""
        result = await session.execute(
            select(func.sum(ClientPaymentEvent.amount))
            .where(ClientPaymentEvent.transaction_id == transaction_id)
        )
        total = result.scalar_one_or_none()
        return float(total) if total else 0.0

    @staticmethod
    async def count_by_transaction_id(
        session: AsyncSession,
        transaction_id: int
    ) -> int:
        """Count payment events for a transaction."""
        result = await session.execute(
            select(func.count(ClientPaymentEvent.id))
            .where(ClientPaymentEvent.transaction_id == transaction_id)
        )
        return result.scalar_one()

    @staticmethod
    async def get_payment_breakdown_by_transaction_id(
        session: AsyncSession,
        transaction_id: int
    ) -> dict[str, float]:
        """
        Get payment breakdown by provider for a transaction.

        Returns dict with provider as key and total amount as value.
        Example: {'cash': 100000.0, 'click': 50000.0, 'payme': 0.0}
        """
        result = await session.execute(
            select(
                ClientPaymentEvent.payment_provider,
                func.sum(ClientPaymentEvent.amount).label('total')
            )
            .where(ClientPaymentEvent.transaction_id == transaction_id)
            .group_by(ClientPaymentEvent.payment_provider)
        )

        breakdown: dict[str, float] = {
            'cash': 0.0, 'click': 0.0, 'payme': 0.0, 'card': 0.0, 'wallet': 0.0
        }
        for row in result:
            provider = row.payment_provider or 'cash'  # handle legacy NULL values
            breakdown[provider] = float(row.total)

        return breakdown

    # -------------------------------------------------------------------------
    # POS Cashier Log Queries
    # These methods join with ClientTransaction to surface client_code and reys
    # (flight) alongside each payment event.
    #
    # admin_id parameter:
    #   • int  → filter to that cashier only  (personal log / targeted admin view)
    #   • None → no filter, return all events (super-admin aggregate view)
    # -------------------------------------------------------------------------

    @staticmethod
    async def get_by_admin_id_paginated(
        session: AsyncSession,
        admin_id: int | None,
        limit: int,
        offset: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict]:
        """
        Return paginated payment events, optionally filtered to one cashier.

        Joins with client_transactions to include client_code and flight (reys).
        Results are ordered by created_at descending (most recent first).

        Why a raw join instead of relationship lazy-load: ClientPaymentEvent
        intentionally has no ORM relationship to ClientTransaction to keep the
        models lightweight.  A single joined query is also more performant than
        an N+1 load pattern.

        Args:
            session:   Async DB session.
            admin_id:  Admin DB PK to filter by, or None for all cashiers.
            limit:     Page size.
            offset:    Row offset for pagination.
            date_from: Inclusive lower bound on created_at (UTC-aware).
            date_to:   Inclusive upper bound on created_at (UTC-aware).

        Returns:
            List of dicts with keys:
              id, transaction_id, client_code, flight, paid_amount,
              payment_provider, cashier_id, created_at.
        """
        from src.infrastructure.database.models.client_transaction import (
            ClientTransaction,
        )

        query = (
            select(
                ClientPaymentEvent.id,
                ClientPaymentEvent.transaction_id,
                ClientTransaction.client_code,
                ClientTransaction.reys.label("flight"),
                ClientPaymentEvent.amount.label("paid_amount"),
                ClientPaymentEvent.payment_provider,
                ClientPaymentEvent.approved_by_admin_id.label("cashier_id"),
                ClientPaymentEvent.created_at,
            )
            .join(
                ClientTransaction,
                ClientPaymentEvent.transaction_id == ClientTransaction.id,
                isouter=True,
            )
        )

        if admin_id is not None:
            query = query.where(ClientPaymentEvent.approved_by_admin_id == admin_id)

        # Apply date range filters before pagination so LIMIT/OFFSET operates on
        # the correctly-filtered result set, not on an already-sliced page.
        if date_from is not None:
            query = query.where(ClientPaymentEvent.created_at >= date_from)
        if date_to is not None:
            query = query.where(ClientPaymentEvent.created_at <= date_to)

        query = query.order_by(ClientPaymentEvent.created_at.desc()).limit(limit).offset(offset)

        rows = (await session.execute(query)).all()

        return [
            {
                "id": row.id,
                "transaction_id": row.transaction_id,
                "client_code": row.client_code,
                "flight": row.flight,
                "paid_amount": float(row.paid_amount) if row.paid_amount else 0.0,
                "payment_provider": row.payment_provider or "cash",
                "cashier_id": row.cashier_id,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    @staticmethod
    async def count_by_admin_id(
        session: AsyncSession,
        admin_id: int | None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        """
        Count payment events, optionally filtered to one cashier.

        Applies the same optional date filter as get_by_admin_id_paginated so
        that total_count in the paginated response is always consistent with the
        items actually returned.

        Args:
            admin_id: Admin DB PK to filter by, or None for all cashiers.
        """
        query = select(func.count(ClientPaymentEvent.id))

        if admin_id is not None:
            query = query.where(ClientPaymentEvent.approved_by_admin_id == admin_id)

        if date_from is not None:
            query = query.where(ClientPaymentEvent.created_at >= date_from)
        if date_to is not None:
            query = query.where(ClientPaymentEvent.created_at <= date_to)

        result = await session.execute(query)
        return result.scalar_one()

    @staticmethod
    async def sum_today_by_admin_id(
        session: AsyncSession,
        admin_id: int | None,
    ) -> float:
        """
        Return the total amount processed today (UTC calendar day).

        Args:
            admin_id: Admin DB PK to filter by, or None for all cashiers.

        'Today' is intentionally defined in UTC so the value is deterministic
        across server restarts and timezone changes.  The frontend can apply
        its own local-timezone offset if needed.
        """
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        query = (
            select(func.sum(ClientPaymentEvent.amount))
            .where(ClientPaymentEvent.created_at >= today_start)
        )

        if admin_id is not None:
            query = query.where(ClientPaymentEvent.approved_by_admin_id == admin_id)

        result = await session.execute(query)
        total = result.scalar_one_or_none()
        return float(total) if total else 0.0

