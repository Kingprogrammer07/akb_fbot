"""Client Transaction DAO."""

import json

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.dao.filters import apply_public_transaction_filter
import logging

logger = logging.getLogger(__name__)


class ClientTransactionDAO:
    """Data Access Object for ClientTransaction."""

    @staticmethod
    async def get_by_telegram_id(
        session: AsyncSession, telegram_id: int, include_hidden: bool = False
    ) -> list[ClientTransaction]:
        """Get all transactions for a telegram user (excludes UZPOST and WALLET_ADJ by default)."""
        query = select(ClientTransaction).where(
            ClientTransaction.telegram_id == telegram_id
        )
        query = apply_public_transaction_filter(query, include_hidden)
        query = query.order_by(ClientTransaction.created_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_client_code(
        session: AsyncSession,
        client_code: str | list[str],
        include_hidden: bool = False,
    ) -> list[ClientTransaction]:
        """Get all transactions for a client code or list of codes (excludes UZPOST and WALLET_ADJ by default)."""
        if isinstance(client_code, list):
            client_codes_upper = [c.upper() for c in client_code if c]
            condition = func.upper(ClientTransaction.client_code).in_(
                client_codes_upper
            )
        else:
            condition = func.upper(ClientTransaction.client_code) == client_code.upper()

        query = select(ClientTransaction).where(condition)
        query = apply_public_transaction_filter(query, include_hidden)
        query = query.order_by(ClientTransaction.created_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def check_payment_exists(
        session: AsyncSession,
        client_code: str | list[str],
        reys: str,
        include_hidden: bool = False,
    ) -> bool:
        """Check if payment already exists for this flight (excludes UZPOST and WALLET_ADJ by default)."""
        codes = [client_code] if isinstance(client_code, str) else client_code
        upper_codes = [c.upper() for c in codes]

        query = select(ClientTransaction).where(
            func.upper(ClientTransaction.client_code).in_(upper_codes),
            func.upper(ClientTransaction.reys) == reys.upper(),
            ClientTransaction.is_taken_away == False,
            ClientTransaction.payment_status == "paid",
            ClientTransaction.remaining_amount <= 0,
        )
        query = apply_public_transaction_filter(query, include_hidden)

        result = await session.execute(query)
        transactions = list(result.scalars().all())

        if len(transactions) > 1:
            duplicate_ids = [tx.id for tx in transactions]
            logger.error(
                f"[DATABASE DUBILKAT XATOSI] qayerda: check_payment_exists | "
                f"Mijoz kodi: {client_code} | Reys: {reys} | "
                f"Topilgan to'lov qatorlari soni: {len(transactions)} ta | "
                f"To'qnashgan qator ID lari: {duplicate_ids}"
            )
            return True

        return len(transactions) == 1

    @staticmethod
    async def get_by_client_code_flight_row(
        session: AsyncSession,
        client_code: str | list[str],
        reys: str,
        qator_raqami: int,
        include_hidden: bool = False,
    ) -> ClientTransaction | None:
        """Get transaction by client_code, flight, and row number (excludes UZPOST and WALLET_ADJ by default)."""
        if isinstance(client_code, list):
            client_codes_upper = [c.upper() for c in client_code if c]
            client_condition = func.upper(ClientTransaction.client_code).in_(
                client_codes_upper
            )
        else:
            client_condition = (
                func.upper(ClientTransaction.client_code) == client_code.upper()
            )

        query = select(ClientTransaction).where(
            client_condition,
            func.upper(ClientTransaction.reys) == reys.upper(),
            ClientTransaction.qator_raqami == qator_raqami,
        )
        query = apply_public_transaction_filter(query, include_hidden)
        result = await session.execute(query)
        transactions = list(result.scalars().all())

        if len(transactions) == 0:
            return None
        if len(transactions) == 1:
            return transactions[0]

        # Dublikat topildi — prioritet bo'yicha eng yaxshisini qaytaramiz:
        # paid > partial > pending, so'ng eng yangisi. Tozalash autofix skriptida.
        priority = {"paid": 0, "partial": 1, "pending": 2}
        transactions.sort(
            key=lambda t: (
                priority.get(t.payment_status, 99),
                -(t.id or 0),
            )
        )
        duplicate_ids = [t.id for t in transactions]
        logger.error(
            f"[DATABASE DUBILKAT XATOSI] qayerda: get_by_client_code_flight_row | "
            f"Mijoz kodi: {client_code} | Reys: {reys} | qator_raqami: {qator_raqami} | "
            f"Topilgan qatorlar soni: {len(transactions)} | IDlar: {duplicate_ids}"
        )
        return transactions[0]

    @staticmethod
    async def create(session: AsyncSession, data: dict) -> ClientTransaction:
        """Create a new transaction."""
        transaction = ClientTransaction(**data)
        session.add(transaction)
        await session.flush()
        await session.refresh(transaction)
        return transaction

    @staticmethod
    async def get_by_id(
        session: AsyncSession, transaction_id: int
    ) -> ClientTransaction | None:
        """Get transaction by ID."""
        result = await session.execute(
            select(ClientTransaction).where(ClientTransaction.id == transaction_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def delete(session: AsyncSession, transaction: ClientTransaction) -> None:
        """Delete a transaction."""
        await session.delete(transaction)
        await session.flush()

    @staticmethod
    async def count_by_telegram_id(
        session: AsyncSession, telegram_id: int, include_hidden: bool = False
    ) -> int:
        """Count total transactions for a telegram user (excludes UZPOST and WALLET_ADJ by default)."""
        query = select(func.count(ClientTransaction.id)).where(
            ClientTransaction.telegram_id == telegram_id
        )
        query = apply_public_transaction_filter(query, include_hidden)
        result = await session.execute(query)
        return result.scalar_one()

    @staticmethod
    async def count_by_client_code(
        session: AsyncSession,
        client_code: str | list[str],
        include_hidden: bool = False,
    ) -> int:
        """Count total transactions for a client code or list of codes (excludes UZPOST and WALLET_ADJ by default)."""
        if isinstance(client_code, list):
            client_codes_upper = [c.upper() for c in client_code if c]
            condition = func.upper(ClientTransaction.client_code).in_(
                client_codes_upper
            )
        else:
            condition = func.upper(ClientTransaction.client_code) == client_code.upper()

        query = select(func.count(ClientTransaction.id)).where(condition)
        query = apply_public_transaction_filter(query, include_hidden)
        result = await session.execute(query)
        return result.scalar_one()

    @staticmethod
    async def count_taken_away(
        session: AsyncSession, telegram_id: int, include_hidden: bool = False
    ) -> int:
        """Count taken away cargo for a telegram user (excludes UZPOST and WALLET_ADJ by default)."""
        query = select(func.count(ClientTransaction.id)).where(
            ClientTransaction.telegram_id == telegram_id,
            ClientTransaction.is_taken_away == True,
        )
        query = apply_public_transaction_filter(query, include_hidden)
        result = await session.execute(query)
        return result.scalar_one()

    @staticmethod
    async def count_taken_away_by_client_code(
        session: AsyncSession,
        client_code: str | list[str],
        include_hidden: bool = False,
    ) -> int:
        """Count taken away cargo for a client code or list of codes (excludes UZPOST and WALLET_ADJ by default)."""
        if isinstance(client_code, list):
            client_codes_upper = [c.upper() for c in client_code if c]
            condition = func.upper(ClientTransaction.client_code).in_(
                client_codes_upper
            )
        else:
            condition = func.upper(ClientTransaction.client_code) == client_code.upper()

        query = select(func.count(ClientTransaction.id)).where(
            condition, ClientTransaction.is_taken_away == True
        )
        query = apply_public_transaction_filter(query, include_hidden)
        result = await session.execute(query)
        return result.scalar_one()

    @staticmethod
    async def get_latest_by_telegram_id(
        session: AsyncSession, telegram_id: int, include_hidden: bool = False
    ) -> ClientTransaction | None:
        """Get latest transaction for a telegram user (excludes UZPOST and WALLET_ADJ by default)."""
        query = select(ClientTransaction).where(
            ClientTransaction.telegram_id == telegram_id
        )
        query = apply_public_transaction_filter(query, include_hidden)
        query = query.order_by(ClientTransaction.created_at.desc()).limit(1)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_latest_by_client_code(
        session: AsyncSession,
        client_code: str | list[str],
        include_hidden: bool = False,
    ) -> ClientTransaction | None:
        """Get latest transaction for a client code or list of codes (excludes UZPOST and WALLET_ADJ by default)."""
        if isinstance(client_code, list):
            client_codes_upper = [c.upper() for c in client_code if c]
            condition = func.upper(ClientTransaction.client_code).in_(
                client_codes_upper
            )
        else:
            condition = func.upper(ClientTransaction.client_code) == client_code.upper()

        query = select(ClientTransaction).where(condition)
        query = apply_public_transaction_filter(query, include_hidden)
        query = query.order_by(ClientTransaction.created_at.desc()).limit(1)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_telegram_id_paginated(
        session: AsyncSession,
        telegram_id: int,
        limit: int = 10,
        offset: int = 0,
        include_hidden: bool = False,
    ) -> list[ClientTransaction]:
        """Get paginated transactions for a telegram user (excludes UZPOST and WALLET_ADJ by default)."""
        query = select(ClientTransaction).where(
            ClientTransaction.telegram_id == telegram_id
        )
        query = apply_public_transaction_filter(query, include_hidden)
        query = (
            query.order_by(ClientTransaction.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_filtered_transactions(
        session: AsyncSession,
        client_code: str | list[str],
        filter_type: str,
        sort_order: str,
        limit: int,
        offset: int,
        flight_code: str | None = None,
        include_hidden: bool = True,
    ) -> list[ClientTransaction]:
        """Get filtered and sorted transactions (excludes UZPOST and WALLET_ADJ by default)."""
        if isinstance(client_code, list):
            client_codes_upper = [c.upper() for c in client_code if c]
            client_condition = func.upper(ClientTransaction.client_code).in_(
                client_codes_upper
            )
        else:
            client_condition = (
                func.upper(ClientTransaction.client_code) == client_code.upper()
            )

        query = select(ClientTransaction).where(client_condition)
        query = apply_public_transaction_filter(query, include_hidden)

        # Apply flight filter if provided
        if flight_code:
            query = query.where(func.upper(ClientTransaction.reys) == flight_code.upper())

        # Apply filters
        if filter_type == "paid":
            query = query.where(
                ClientTransaction.payment_status == "paid",
                ClientTransaction.remaining_amount <= 0,
            )
        elif filter_type == "unpaid":
            # "unpaid" means the client has not made any payment yet (pending status).
            # "partial" is its own distinct filter — do not conflate them.
            query = query.where(ClientTransaction.payment_status == "pending")
        elif filter_type == "partial":
            query = query.where(
                ClientTransaction.payment_status == "partial",
                ClientTransaction.remaining_amount > 0,
            )
        elif filter_type == "taken":
            query = query.where(ClientTransaction.is_taken_away == True)
        elif filter_type == "not_taken":
            query = query.where(ClientTransaction.is_taken_away == False)
        # "all" - no additional filter

        # Apply sorting
        if sort_order == "asc":
            query = query.order_by(ClientTransaction.created_at.asc())
        else:
            query = query.order_by(ClientTransaction.created_at.desc())

        # Apply pagination
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def count_filtered_transactions(
        session: AsyncSession,
        telegram_id: int,
        filter_type: str,
        flight_code: str | None = None,
        include_hidden: bool = False,
    ) -> int:
        """Count filtered transactions by telegram_id (deprecated, use count_filtered_transactions_by_client_code)."""
        query = select(func.count(ClientTransaction.id)).where(
            ClientTransaction.telegram_id == telegram_id
        )
        query = apply_public_transaction_filter(query, include_hidden)

        # Apply flight filter if provided
        if flight_code:
            query = query.where(func.upper(ClientTransaction.reys) == flight_code.upper())

        # Apply filters
        if filter_type == "paid":
            query = query.where(
                ClientTransaction.payment_status == "paid",
                ClientTransaction.remaining_amount <= 0,
            )
        elif filter_type == "unpaid":
            # "unpaid" means the client has not made any payment yet (pending status).
            # "partial" is its own distinct filter — do not conflate them.
            query = query.where(ClientTransaction.payment_status == "pending")
        elif filter_type == "partial":
            query = query.where(
                ClientTransaction.payment_status == "partial",
                ClientTransaction.remaining_amount > 0,
            )
        elif filter_type == "taken":
            query = query.where(ClientTransaction.is_taken_away == True)
        elif filter_type == "not_taken":
            query = query.where(ClientTransaction.is_taken_away == False)

        result = await session.execute(query)
        return result.scalar_one()

    @staticmethod
    def _is_backfill_transaction(tx: "ClientTransaction") -> bool:
        """
        Backfill skripti yaratgan tranzaksiyani aniqlaydi.

        Backfill tranzaksiyalari quyidagi belgilarga ega:
        - qator_raqami = 0 (Google Sheets qatori yo'q)
        - payment_status = 'pending'
        - summa = 0 (haqiqiy to'lov summasi kiritilmagan)
        - payment_balance_difference < 0 (qarz sifatida belgilangan)
        """
        return (
            tx.qator_raqami == 0
            and tx.payment_status == "pending"
            and float(tx.summa or 0) == 0.0
            and float(tx.payment_balance_difference or 0) < 0
        )

    @staticmethod
    async def get_by_client_code_flight(
        session: AsyncSession,
        client_code: str | list[str],
        reys: str,
        include_hidden: bool = False,
    ) -> ClientTransaction | None:
        """
        Get transaction by client_code and flight name.

        When duplicates are detected, automatically removes backfill-generated
        ghost transactions if a real payment transaction exists for the same
        client_code + reys combination. This is a self-healing mechanism to
        recover from past backfill script errors without manual DB intervention.
        """
        if isinstance(client_code, list):
            client_codes_upper = [c.upper() for c in client_code if c]
            client_condition = func.upper(ClientTransaction.client_code).in_(
                client_codes_upper
            )
        else:
            client_condition = (
                func.upper(ClientTransaction.client_code) == client_code.upper()
            )

        query = select(ClientTransaction).where(
            client_condition, func.upper(ClientTransaction.reys) == reys.upper()
        )
        query = apply_public_transaction_filter(query, include_hidden)

        result = await session.execute(query)
        transactions = list(result.scalars().all())

        if len(transactions) == 0:
            return None

        if len(transactions) == 1:
            return transactions[0]

        # --- Dublikat aniqlandi: avtomatik tozalash ---
        backfills = [
            tx for tx in transactions
            if ClientTransactionDAO._is_backfill_transaction(tx)
        ]
        real_payments = [tx for tx in transactions if tx not in backfills]

        if backfills and real_payments:
            # Haqiqiy to'lov bor va backfill ham bor — backfillni o'chiramiz
            deleted_ids = [tx.id for tx in backfills]
            for ghost in backfills:
                await session.delete(ghost)
            await session.flush()
            logger.warning(
                f"[DUBLIKAT AUTO-TOZALASH] client_code={client_code} | reys={reys} | "
                f"O'chirilgan backfill IDlar: {deleted_ids} | "
                f"Qoldirilgan haqiqiy tranzaksiya ID: {real_payments[0].id}"
            )
            return real_payments[0]

        # Ikkalasi ham bir xil turdagi tranzaksiya — qo'lda tekshirish kerak
        duplicate_ids = [tx.id for tx in transactions]
        logger.error(
            f"[DATABASE DUBILKAT XATOSI] qayerda: get_by_client_code_flight | "
            f"Mijoz kodi: {client_code} | Reys: {reys} | "
            f"Topilgan jami qatorlar soni: {len(transactions)} ta | "
            f"To'qnashgan qator ID lari: {duplicate_ids} | "
            f"Sababi: Bir xil turdagi dublikatlar — qo'lda tekshiring."
        )
        return transactions[0]

    @staticmethod
    async def get_by_flight(
        session: AsyncSession, flight_code: str, include_hidden: bool = False
    ) -> list[ClientTransaction]:
        """Get all transactions for a specific flight (excludes UZPOST and WALLET_ADJ by default)."""
        query = select(ClientTransaction).where(func.upper(ClientTransaction.reys) == flight_code.upper())
        query = apply_public_transaction_filter(query, include_hidden)
        query = query.order_by(ClientTransaction.created_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def mark_as_taken(session: AsyncSession, transaction_id: int) -> bool:
        """Mark transaction as cargo taken."""
        from datetime import datetime, timezone

        result = await session.execute(
            select(ClientTransaction).where(ClientTransaction.id == transaction_id)
        )
        transaction = result.scalar_one_or_none()

        if transaction:
            transaction.is_taken_away = True
            transaction.taken_away_date = datetime.now(timezone.utc)
            await session.flush()
            return True
        return False

    @staticmethod
    async def get_unique_flights_by_telegram_id(
        session: AsyncSession, telegram_id: int, include_hidden: bool = False
    ) -> list[str]:
        """Get unique flight codes for a telegram user (excludes UZPOST and WALLET_ADJ by default)."""
        query = select(ClientTransaction.reys).where(
            ClientTransaction.telegram_id == telegram_id
        )
        query = apply_public_transaction_filter(query, include_hidden)
        query = query.distinct().order_by(ClientTransaction.reys.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_unique_flights_by_client_code(
        session: AsyncSession,
        client_code: str | list[str],
        include_hidden: bool = False,
    ) -> list[str]:
        """Get unique flight codes for a client code or list of codes (excludes UZPOST and WALLET_ADJ by default)."""
        if isinstance(client_code, list):
            client_codes_upper = [c.upper() for c in client_code if c]
            condition = func.upper(ClientTransaction.client_code).in_(
                client_codes_upper
            )
        else:
            condition = func.upper(ClientTransaction.client_code) == client_code.upper()

        query = select(ClientTransaction.reys).where(condition)
        query = apply_public_transaction_filter(query, include_hidden)
        query = query.distinct().order_by(ClientTransaction.reys.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_client_code_and_flight(
        session: AsyncSession,
        client_code: str | list[str],
        reys: str,
        include_hidden: bool = False,
    ) -> list[ClientTransaction]:
        """Get all transactions by client_code and flight (excludes UZPOST and WALLET_ADJ by default)."""
        if isinstance(client_code, list):
            client_codes_upper = [c.upper() for c in client_code if c]
            client_condition = func.upper(ClientTransaction.client_code).in_(
                client_codes_upper
            )
        else:
            client_condition = (
                func.upper(ClientTransaction.client_code) == client_code.upper()
            )

        query = select(ClientTransaction).where(
            client_condition, func.upper(ClientTransaction.reys) == reys.upper()
        )
        query = apply_public_transaction_filter(query, include_hidden)
        query = query.order_by(ClientTransaction.created_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_all_transactions(
        session: AsyncSession, include_hidden: bool = False
    ) -> list[ClientTransaction]:
        """
        Get all client transactions (excludes UZPOST and WALLET_ADJ by default).

        Warning: This method returns ALL transactions matching the filter.
        Use with caution in production. For specific queries, prefer other
        methods like get_by_client_code() or get_by_telegram_id().

        Args:
            session: Database session
            include_hidden: If True, include UZPOST and WALLET_ADJ transactions
                          If False (default), exclude them

        Returns:
            List of all transactions, ordered by client_code and reys
        """
        query = select(ClientTransaction).order_by(
            ClientTransaction.client_code, ClientTransaction.reys
        )
        query = apply_public_transaction_filter(query, include_hidden)
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def mark_as_taken_by_client_and_flights(
        session: AsyncSession, client_codes: list[str], flights: list[str]
    ):
        from datetime import datetime, timezone

        # Clean the list (remove None or empty strings)
        valid_codes = [c for c in client_codes if c]
        if not valid_codes or not flights:
            return

        for flight in flights:
            result = await session.execute(
                select(ClientTransaction).where(
                    ClientTransaction.client_code.in_(valid_codes),
                    func.upper(ClientTransaction.reys) == flight.upper(),
                    ClientTransaction.is_taken_away == False,
                )
            )
            transactions = result.scalars().all()

            for tx in transactions:
                tx.is_taken_away = True
                tx.taken_away_date = datetime.now(timezone.utc)

        await session.flush()

    @staticmethod
    async def create_wallet_adjustment(
        session: AsyncSession,
        telegram_id: int,
        client_code: str,
        amount: float,
        reason: str,
    ) -> ClientTransaction:
        """
        Create a wallet adjustment pseudo-transaction.

        Args:
            amount: positive = credit (debt payment), negative = debit (refund/wallet usage)
            reason: 'refund', 'debt_payment', 'wallet_usage'
        """
        transaction = ClientTransaction(
            telegram_id=telegram_id,
            client_code=client_code,
            qator_raqami=0,
            reys=f"WALLET_ADJ:{reason}",
            summa=0,
            vazn="0",
            payment_type="online",
            payment_status="paid",
            paid_amount=0,
            total_amount=0,
            remaining_amount=0,
            payment_balance_difference=amount,
            is_taken_away=True,
        )
        session.add(transaction)
        await session.flush()
        await session.refresh(transaction)
        return transaction

    @staticmethod
    async def create_system_adjustment(
        session: AsyncSession,
        telegram_id: int,
        client_code: str,
        amount: float,
        reason: str,
    ) -> ClientTransaction:
        """
        Create a cashier-initiated system balance adjustment pseudo-transaction.

        Uses the ``SYS_ADJ:{reason}`` reys prefix so the record is excluded from
        user-facing transaction lists by ``apply_public_transaction_filter``, but
        surfaces in the POS cashier audit log via the linked ``ClientPaymentEvent``.

        Unlike ``create_wallet_adjustment`` (which is user-initiated wallet usage),
        this method records admin corrections — e.g. reversing an overpayment or
        manually crediting a shortfall — and should only be called from the POS
        adjust-balance endpoint.

        Args:
            session:     Async DB session (caller commits).
            telegram_id: Client's Telegram ID; use 0 when the client has no
                         Telegram account (the column is non-nullable).
            client_code: Normalised (upper-case) client code.
            amount:      Signed UZS delta.  Positive = credit (client owes less /
                         gets a refund); negative = debit (client owes more /
                         overpayment correction).
            reason:      Pre-sanitised slug with no colons or spaces (enforced by
                         the ``AdjustBalanceRequest`` validator before this point).
        """
        transaction = ClientTransaction(
            telegram_id=telegram_id,
            client_code=client_code,
            qator_raqami=0,
            reys=f"SYS_ADJ:{reason}",
            summa=0,
            vazn="0",
            payment_type="cash",
            payment_status="paid",
            paid_amount=0,
            total_amount=0,
            remaining_amount=0,
            payment_balance_difference=amount,
            is_taken_away=True,
        )
        session.add(transaction)
        await session.flush()
        await session.refresh(transaction)
        return transaction

    @staticmethod
    async def get_wallet_balances(
        session: AsyncSession, client_code: str | list[str]
    ) -> dict[str, float]:
        """
        Calculates Wallet balance and Debt separately.
        Returns a dict with positive 'wallet_balance' and negative 'debt'.
        """
        try:
            if isinstance(client_code, list):
                client_codes_upper = [c.upper() for c in client_code if c]
                client_condition = func.upper(ClientTransaction.client_code).in_(
                    client_codes_upper
                )
            else:
                client_condition = (
                    func.upper(ClientTransaction.client_code) == client_code.upper()
                )

            query_in = select(
                func.coalesce(func.sum(ClientTransaction.payment_balance_difference), 0)
            ).where(
                client_condition,
                ClientTransaction.payment_balance_difference > 0,
            )

            query_out = select(
                func.coalesce(func.sum(ClientTransaction.payment_balance_difference), 0)
            ).where(
                client_condition,
                ClientTransaction.reys.like("WALLET_ADJ%"),
                ClientTransaction.payment_balance_difference < 0,
            )

            query_debt = select(
                func.coalesce(func.sum(ClientTransaction.payment_balance_difference), 0)
            ).where(
                client_condition,
                ~ClientTransaction.reys.like("WALLET_ADJ%"),
                ClientTransaction.payment_balance_difference < 0,
            )

            val_in = float(
                (await session.execute(query_in)).scalar_one_or_none() or 0.0
            )
            val_out = float(
                (await session.execute(query_out)).scalar_one_or_none() or 0.0
            )
            val_debt = float(
                (await session.execute(query_debt)).scalar_one_or_none() or 0.0
            )

            available_wallet = val_in + val_out

            return {"wallet_balance": max(0.0, available_wallet), "debt": val_debt}

        except Exception as e:
            logger.error(f"Wallet balance error for {client_code}: {e}")
            return {"wallet_balance": 0.0, "debt": 0.0}

    @staticmethod
    async def sum_payment_balance_difference_by_client_code(
        session: AsyncSession, client_code: str | list[str]
    ) -> float:
        """Backward-compatible wrapper. Returns merged balance for legacy callers."""
        balances = await ClientTransactionDAO.get_wallet_balances(session, client_code)
        wallet = balances["wallet_balance"]
        debt = balances["debt"]
        return wallet if wallet > 0 else debt

    @staticmethod
    async def count_filtered_transactions_by_client_code(
        session: AsyncSession,
        client_code: str | list[str],
        filter_type: str,
        flight_code: str | None = None,
        include_hidden: bool = False,
    ) -> int:
        """Count filtered transactions by client_code(s) (excludes UZPOST and WALLET_ADJ by default)."""
        if isinstance(client_code, list):
            client_codes_upper = [c.upper() for c in client_code if c]
            client_condition = func.upper(ClientTransaction.client_code).in_(
                client_codes_upper
            )
        else:
            client_condition = (
                func.upper(ClientTransaction.client_code) == client_code.upper()
            )

        query = select(func.count(ClientTransaction.id)).where(client_condition)
        query = apply_public_transaction_filter(query, include_hidden)

        # Apply flight filter if provided
        if flight_code:
            query = query.where(func.upper(ClientTransaction.reys) == flight_code.upper())

        # Apply filters based on filter_type
        if filter_type == "paid":
            query = query.where(
                ClientTransaction.payment_status == "paid",
                ClientTransaction.remaining_amount <= 0,
            )
        elif filter_type == "unpaid":
            # "unpaid" means the client has not made any payment yet (pending status).
            # "partial" is its own distinct filter — do not conflate them.
            query = query.where(ClientTransaction.payment_status == "pending")
        elif filter_type == "partial":
            query = query.where(
                ClientTransaction.payment_status == "partial",
                ClientTransaction.remaining_amount > 0,
            )
        elif filter_type == "taken":
            query = query.where(ClientTransaction.is_taken_away == True)
        elif filter_type == "not_taken":
            query = query.where(ClientTransaction.is_taken_away == False)
        # "all" - no additional filter

        result = await session.execute(query)
        return result.scalar_one()

    # -------------------------------------------------------------------------
    # Warehouse (flight-scoped) queries
    # These methods use flight_name as the primary filter and do NOT require a
    # client_code, making them suitable for warehouse workers who browse cargo
    # by flight rather than by specific client.
    # -------------------------------------------------------------------------

    @staticmethod
    async def get_transactions_by_flight_filtered(
        session: AsyncSession,
        flight_name: str,
        filter_type: str = "all",
        sort_order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[ClientTransaction]:
        """
        Return paginated transactions for a specific flight with optional filters.

        Unlike ``get_filtered_transactions``, this method has NO client_code
        requirement — the flight_name is the sole primary filter.
        """
        query = (
            select(ClientTransaction)
            .where(func.upper(ClientTransaction.reys) == flight_name.upper())
        )
        query = apply_public_transaction_filter(query, include_hidden=False)

        if filter_type == "paid":
            query = query.where(
                ClientTransaction.payment_status == "paid",
                ClientTransaction.remaining_amount <= 0,
            )
        elif filter_type == "unpaid":
            # "unpaid" means the client has not made any payment yet (pending status).
            # "partial" is its own distinct filter — do not conflate them.
            query = query.where(ClientTransaction.payment_status == "pending")
        elif filter_type == "partial":
            query = query.where(
                ClientTransaction.payment_status == "partial",
                ClientTransaction.remaining_amount > 0,
            )
        elif filter_type == "taken":
            query = query.where(ClientTransaction.is_taken_away == True)
        elif filter_type == "not_taken":
            query = query.where(ClientTransaction.is_taken_away == False)

        if sort_order == "asc":
            query = query.order_by(ClientTransaction.created_at.asc())
        else:
            query = query.order_by(ClientTransaction.created_at.desc())

        query = query.limit(limit).offset(offset)
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def count_transactions_by_flight_filtered(
        session: AsyncSession,
        flight_name: str,
        filter_type: str = "all",
    ) -> int:
        """Count transactions for a specific flight with optional filters (no client_code required)."""
        query = (
            select(func.count(ClientTransaction.id))
            .where(func.upper(ClientTransaction.reys) == flight_name.upper())
        )
        query = apply_public_transaction_filter(query, include_hidden=False)

        if filter_type == "paid":
            query = query.where(
                ClientTransaction.payment_status == "paid",
                ClientTransaction.remaining_amount <= 0,
            )
        elif filter_type == "unpaid":
            # "unpaid" means the client has not made any payment yet (pending status).
            # "partial" is its own distinct filter — do not conflate them.
            query = query.where(ClientTransaction.payment_status == "pending")
        elif filter_type == "partial":
            query = query.where(
                ClientTransaction.payment_status == "partial",
                ClientTransaction.remaining_amount > 0,
            )
        elif filter_type == "taken":
            query = query.where(ClientTransaction.is_taken_away == True)
        elif filter_type == "not_taken":
            query = query.where(ClientTransaction.is_taken_away == False)

        result = await session.execute(query)
        return result.scalar_one()

    @staticmethod
    async def get_recent_flights_with_stats(
        session: AsyncSession,
        limit: int = 10,
    ) -> list[dict]:
        """
        Return the most recently active flights with cargo and unique-client counts.

        Uses FlightCargo (is_sent=True) as the primary source so that flights
        with unsettled cargo — where no ClientTransaction exists yet — are still
        visible in the warehouse dropdown.  Falls back to ClientTransaction if
        FlightCargo returns nothing (e.g. legacy data without FlightCargo rows).

        Ordered by the date of the latest cargo record so the freshest flights
        appear first.
        """
        from src.infrastructure.database.models.flight_cargo import FlightCargo

        # Primary: count all sent cargo items per flight regardless of payment status
        fc_query = (
            select(
                FlightCargo.flight_name,
                func.count(FlightCargo.id).label("tx_count"),
                func.count(func.distinct(func.upper(FlightCargo.client_id))).label("user_count"),
                func.max(FlightCargo.created_at).label("latest_at"),
            )
            .where(FlightCargo.is_sent == True)  # noqa: E712
            .group_by(FlightCargo.flight_name)
            .order_by(func.max(FlightCargo.created_at).desc())
            .limit(limit)
        )
        fc_result = await session.execute(fc_query)
        fc_rows = fc_result.all()

        if fc_rows:
            return [
                {
                    "flight_name": row.flight_name,
                    "tx_count": row.tx_count,
                    "user_count": row.user_count,
                    "latest_at": row.latest_at,
                }
                for row in fc_rows
            ]

        # Fallback: legacy data — no FlightCargo rows, use ClientTransaction
        ct_query = (
            select(
                ClientTransaction.reys,
                func.count(ClientTransaction.id).label("tx_count"),
                func.count(func.distinct(ClientTransaction.client_code)).label("user_count"),
                func.max(ClientTransaction.created_at).label("latest_at"),
            )
            .where(ClientTransaction.reys.isnot(None))
            .group_by(ClientTransaction.reys)
            .order_by(func.max(ClientTransaction.created_at).desc())
            .limit(limit)
        )
        ct_result = await session.execute(ct_query)
        return [
            {
                "flight_name": row.reys,
                "tx_count": row.tx_count,
                "user_count": row.user_count,
                "latest_at": row.latest_at,
            }
            for row in ct_result.all()
        ]
