"""POS Fast Cashier — service layer.

Four responsibilities:
  1. process_bulk_payment  — atomic multi-cargo payment (all-or-nothing commit),
                             followed by fire-and-forget Telegram notifications.
  2. get_cashier_log       — paginated personal audit log for a cashier.
  3. get_all_cashier_logs  — super-admin aggregate view of all cashier activity.
  4. adjust_balance        — cashier-initiated manual balance correction (SYS_ADJ).

Every write operation (process_bulk_payment, adjust_balance) flushes an
AdminAuditLog entry inside the same DB transaction before committing, so
super-admins see a complete, tamper-evident record of all POS activity.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.admin_audit_log import AdminAuditLogDAO
from src.infrastructure.database.dao.client_payment_event import ClientPaymentEventDAO
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.delivery_request import DeliveryRequestDAO
from src.infrastructure.database.dao.cargo_delivery_proof import CargoDeliveryProofDAO
from src.infrastructure.schemas.pos_schemas import (
    AdjustBalanceRequest,
    AdjustBalanceResponse,
    BulkItemResult,
    BulkPaymentItem,
    BulkPaymentResponse,
    CashierLogItem,
    CashierLogResponse,
    TransactionStatusUpdateResponse,
    UpdateDeliveryRequestTypeRequest,
    UpdateProofDeliveryMethodRequest,
    UpdateTakenStatusRequest,
)
from src.infrastructure.tools.s3_manager import s3_manager
import logging

from src.infrastructure.tools.datetime_utils import get_current_time
from src.infrastructure.services.client import ClientService
from src.api.services.verification.transaction_view_service import TransactionViewService

if TYPE_CHECKING:
    from src.api.dependencies import AdminJWTPayload

logger = logging.getLogger(__name__)

class POSPaymentError(Exception):
    """Raised when a POS bulk payment or adjustment cannot be processed."""

    def __init__(
        self,
        message: str,
        failed_cargo_id: int | None = None,
        error_code: str | None = None,
    ) -> None:
        self.message = message
        self.failed_cargo_id = failed_cargo_id
        self.error_code = error_code
        super().__init__(message)


class PaymentPOSService:
    """Service for POS (Point of Sale) cashier operations."""

    @staticmethod
    async def process_bulk_payment(
        items: list[BulkPaymentItem],
        admin: "AdminJWTPayload",
        session: AsyncSession,
    ) -> BulkPaymentResponse:
        """
        Process multiple cargo payments as a single atomic database transaction,
        then fire Telegram notifications in parallel after the commit.

        Algorithm — three phases:

        Phase 1 — Read-only pre-validation (no flushes, no inserts):
          For each BulkPaymentItem, verify:
            • The client exists.
            • The cargo exists and belongs to the client + flight.
            • No duplicate transaction already exists for this cargo.
          Any failure raises POSPaymentError immediately, before any DB write.

        Phase 2 — Write (flush-only per item, single commit at the very end):
          For each pre-validated item, call
          PaymentService.create_payment_transaction() which only flushes.
          A single session.commit() persists everything atomically.
          Any exception triggers session.rollback() so no partial state is left.

        Phase 3 — Notifications (post-commit, fire-and-forget):
          Telegram messages are sent in parallel via asyncio.gather with
          return_exceptions=True so a failing notification never surfaces as
          an API error to the cashier.

        Why admin_id is the Admin DB PK, not a Telegram ID:
          The POS system authenticates via Admin JWT (no Telegram dependency).
          Storing the Admin DB PK in approved_by_admin_id makes the cashier log
          query trivially consistent — it filters by the same PK.
          The old payment system stores Telegram IDs in the same column; both
          coexist without conflict because the cashier log only queries by PK.

        Args:
            items:   Pre-validated list of BulkPaymentItem (from request schema).
            admin:   Authenticated admin from JWT; admin.admin_id is used as
                     approved_by_admin_id for every payment event created.
            session: Shared async DB session — NOT committed inside this method
                     until all items are flushed successfully.

        Returns:
            BulkPaymentResponse with per-item results and aggregate totals.

        Raises:
            POSPaymentError: If any item fails pre-validation or processing.
        """
        # Deferred imports to avoid circular dependencies at module load time.
        from src.api.services.verification.payment_service import (
            PaymentService,
            PaymentServiceError,
        )
        from src.api.services.verification.utils import (
            get_cargo_details,
            validate_cargo_ownership,
        )
        from src.infrastructure.database.dao.client_transaction import (
            ClientTransactionDAO,
        )
        from src.infrastructure.services.client import ClientService

        client_service = ClientService()

        # ------------------------------------------------------------------
        # Phase 1: Read-only pre-validation — collect all data before writes.
        # ------------------------------------------------------------------
        prevalidated: list[dict] = []

        for idx, item in enumerate(items):
            human_idx = idx + 1  # 1-based for user-facing error messages

            client = await client_service.get_client_by_code(item.client_code, session)
            if not client:
                raise POSPaymentError(
                    message=f"{human_idx}-element: '{item.client_code}' kodli mijoz topilmadi.",
                    failed_cargo_id=item.cargo_id,
                )

            # The cashier may have typed either the real flight code or the
            # partner-specific mask shown to the client.  Translate the input
            # to the real name so all downstream lookups (cargo ownership,
            # transaction de-duplication, ledger writes) hit canonical data.
            try:
                from src.infrastructure.services.flight_mask import (
                    FlightMaskService,
                )
                from src.infrastructure.services.partner_resolver import (
                    PartnerNotFoundError,
                    get_resolver,
                )
                _partner = await get_resolver().resolve_by_client_code(
                    session, item.client_code
                )
                normalized = await FlightMaskService.normalize_flight_input(
                    session, _partner.id, item.flight
                )
                # Mutate the validated request item in place; downstream
                # references already use ``item.flight`` directly.
                if normalized != item.flight:
                    item.flight = normalized
            except PartnerNotFoundError:
                # Unknown prefix → keep the input as-is so callers can still
                # see the raw error rather than a misleading masking failure.
                pass

            cargo_data = await get_cargo_details(item.cargo_id, session)
            if not cargo_data:
                raise POSPaymentError(
                    message=f"{human_idx}-element: {item.cargo_id} raqamli yuk topilmadi.",
                    failed_cargo_id=item.cargo_id,
                )

            is_valid, error_msg = validate_cargo_ownership(
                cargo_data, item.client_code, item.flight, client
            )
            if not is_valid:
                raise POSPaymentError(
                    message=f"{human_idx}-element: {error_msg}",
                    failed_cargo_id=item.cargo_id,
                )

            duplicate_tx = await ClientTransactionDAO.get_by_client_code_flight_row(
                session, client.active_codes, item.flight, item.cargo_id
            )
            if duplicate_tx and duplicate_tx.payment_status == "paid":
                raise POSPaymentError(
                    message=(
                        f"{human_idx}-element: {item.cargo_id} raqamli yuk uchun to'lov "
                        f"allaqachon to'liq amalga oshirilgan (tranzaksiya #{duplicate_tx.id})."
                    ),
                    failed_cargo_id=item.cargo_id,
                )

            # If no exact-match tx was found, look for a pending-debt row written by
            # bulk_cargo_sender (qator_raqami=0, payment_status='pending').  Re-using
            # that row avoids creating a second transaction for the same user+flight.
            if not duplicate_tx:
                pending_debt_tx = await ClientTransactionDAO.get_by_client_code_flight_row(
                    session, client.active_codes, item.flight, 0
                )
                if pending_debt_tx and pending_debt_tx.payment_status == "pending":
                    duplicate_tx = pending_debt_tx

            prevalidated.append(
                {
                    "item": item,
                    "client": client,
                    "cargo_data": cargo_data,
                    "existing_tx": duplicate_tx,
                }
            )

        # ------------------------------------------------------------------
        # Phase 2: Write — flush per item, single commit at the end.
        # ------------------------------------------------------------------
        results: list[BulkItemResult] = []
        created_transaction_ids: list[int] = []
        active_codes_by_transaction: dict[int, list[str]] = {}
        # Keyed by cargo_id so Phase 3 can look up wallet_deducted per item.
        wallet_deducted_map: dict[int, float] = {}

        try:
            for entry in prevalidated:
                item: BulkPaymentItem = entry["item"]
                client = entry["client"]
                cargo_data: dict = entry["cargo_data"]

                (
                    new_tx,
                    _payment_balance_difference,
                    _wallet_balance_before,
                    wallet_deducted,
                    _wallet_balance_after,
                ) = await PaymentService.create_payment_transaction(
                    # Use the code from flight_cargos — the authoritative source.
                    # cargo_data["client_id"] is exactly how the warehouse registered
                    # this cargo, so the transaction must be stored under the same key.
                    client_code=cargo_data["client_id"],
                    flight=item.flight,
                    cargo_id=item.cargo_id,
                    paid_amount=item.paid_amount,
                    payment_type=item.payment_type,
                    admin_id=admin.admin_id,
                    session=session,
                    expected_amount=cargo_data["total_amount"],
                    weight=cargo_data["weight"],
                    telegram_id=client.telegram_id or 0,
                    use_balance=item.use_balance,
                    allow_overpayment=True,
                    existing_tx=entry["existing_tx"],
                    card_id=item.card_id,
                )

                wallet_deducted_map[item.cargo_id] = wallet_deducted or 0.0
                created_transaction_ids.append(new_tx.id)
                active_codes_by_transaction[new_tx.id] = client.active_codes or [
                    new_tx.client_code
                ]

                results.append(
                    BulkItemResult(
                        cargo_id=item.cargo_id,
                        client_code=item.client_code,
                        flight=item.flight,
                        transaction_id=new_tx.id,
                        paid_amount=item.paid_amount,
                        expected_amount=cargo_data["total_amount"],
                        payment_status=new_tx.payment_status,
                        is_taken_away=new_tx.is_taken_away,
                    )
                )

            # Flush an immutable audit record BEFORE committing so the log
            # entry and the payment rows are always in the same transaction.
            # If the commit is rolled back, the audit entry rolls back too —
            # no phantom records for failed operations.
            await AdminAuditLogDAO.log(
                session=session,
                action="POS_BULK_PAYMENT",
                admin_id=admin.admin_id,
                role_snapshot=admin.role_name,
                details={
                    "items_count": len(results),
                    "total_paid": sum(r.paid_amount for r in results),
                    "cargo_ids": [r.cargo_id for r in results],
                },
            )

            # Single atomic commit for the entire batch.
            await session.commit()

        except PaymentServiceError as exc:
            await session.rollback()
            raise POSPaymentError(
                message=exc.message,
                failed_cargo_id=None,
            ) from exc
        except POSPaymentError:
            await session.rollback()
            raise
        except Exception as exc:
            await session.rollback()
            raise POSPaymentError(
                message=f"To'lovlarni qayta ishlashda xatolik yuz berdi: {exc}",
            ) from exc

        # ------------------------------------------------------------------
        # Phase 3: Fire-and-forget Telegram notifications (post-commit).
        #
        # Each notification runs independently. return_exceptions=True means a
        # failed Telegram send never surfaces as an API error to the cashier.
        # ------------------------------------------------------------------
        notification_coroutines = [
            PaymentService._send_payment_notifications(
                client=entry["client"],
                transaction_id=result.transaction_id,
                flight=result.flight,
                amount=result.paid_amount,
                payment_type=entry["item"].payment_type,
                admin_id=admin.admin_id,
                is_cash=entry["item"].payment_type == "cash",
                # translator is defined in the method signature but the body uses
                # a locally-built user_text instead — pass a no-op to satisfy it.
                translator=lambda key, **kw: key,
                wallet_deducted=wallet_deducted_map.get(entry["item"].cargo_id) or None,
            )
            for entry, result in zip(prevalidated, results)
        ]
        await asyncio.gather(*notification_coroutines, return_exceptions=True)

        if created_transaction_ids:
            refreshed_transactions = []
            for transaction_id in created_transaction_ids:
                refreshed_tx = await ClientTransactionDAO.get_by_id(session, transaction_id)
                if refreshed_tx:
                    refreshed_transactions.append(refreshed_tx)
            status_map = await TransactionViewService.get_status_map(
                session,
                refreshed_transactions,
                active_codes_by_transaction=active_codes_by_transaction,
            )
            results = [
                TransactionViewService.build_bulk_item_result(
                    result,
                    status_map.get(result.transaction_id),
                )
                for result in results
            ]

        return BulkPaymentResponse(
            processed_count=len(results),
            total_paid=sum(r.paid_amount for r in results),
            results=results,
        )

    @staticmethod
    async def get_cashier_log(
        admin_id: int,
        page: int,
        size: int,
        session: AsyncSession,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> CashierLogResponse:
        """
        Return a paginated audit log of all payments processed by this cashier.

        Filters by approved_by_admin_id == admin_id, which the POS bulk endpoint
        populates with the Admin DB PK.  This means the log only surfaces records
        created through the POS system for this specific cashier.

        Args:
            admin_id:  Admin DB PK from the JWT payload.
            page:      1-based page number.
            size:      Items per page (1–100).
            session:   Async DB session.
            date_from: Optional inclusive lower bound filter (UTC-aware datetime).
            date_to:   Optional inclusive upper bound filter (UTC-aware datetime).

        Returns:
            CashierLogResponse with paginated items and today's total.
        """
        offset = (page - 1) * size

        total_count = await ClientPaymentEventDAO.count_by_admin_id(
            session, admin_id, date_from=date_from, date_to=date_to
        )
        total_pages = max(1, math.ceil(total_count / size))

        raw_rows = await ClientPaymentEventDAO.get_by_admin_id_paginated(
            session,
            admin_id,
            limit=size,
            offset=offset,
            date_from=date_from,
            date_to=date_to,
        )

        today_total = await ClientPaymentEventDAO.sum_today_by_admin_id(
            session, admin_id
        )

        items = [
            CashierLogItem(
                id=row["id"],
                transaction_id=row["transaction_id"],
                client_code=row["client_code"],
                flight=row["flight"],
                paid_amount=row["paid_amount"],
                payment_provider=row["payment_provider"],
                created_at=row["created_at"],
            )
            for row in raw_rows
        ]

        return CashierLogResponse(
            items=items,
            total_count=total_count,
            page=page,
            size=size,
            total_pages=total_pages,
            today_total=today_total,
        )

    @staticmethod
    async def get_all_cashier_logs(
        page: int,
        size: int,
        session: AsyncSession,
        cashier_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> CashierLogResponse:
        """
        Return a paginated log of ALL payment events across every cashier.

        This is the super-admin aggregate view of POS activity.  An optional
        ``cashier_id`` narrows the results to one specific cashier (useful when
        a super-admin investigates a particular cashier's history).

        Internally delegates to the same DAO methods as ``get_cashier_log`` but
        passes ``admin_id=None`` (or the provided ``cashier_id``) so the WHERE
        clause on ``approved_by_admin_id`` is omitted / targeted accordingly.

        Args:
            page:       1-based page number.
            size:       Items per page (1–100).
            session:    Async DB session.
            cashier_id: Optional Admin DB PK to filter; None = all cashiers.
            date_from:  Optional inclusive lower bound filter (UTC-aware).
            date_to:    Optional inclusive upper bound filter (UTC-aware).

        Returns:
            CashierLogResponse with per-item ``cashier_id`` populated.
        """
        offset = (page - 1) * size

        total_count = await ClientPaymentEventDAO.count_by_admin_id(
            session, cashier_id, date_from=date_from, date_to=date_to
        )
        total_pages = max(1, math.ceil(total_count / size))

        raw_rows = await ClientPaymentEventDAO.get_by_admin_id_paginated(
            session,
            cashier_id,
            limit=size,
            offset=offset,
            date_from=date_from,
            date_to=date_to,
        )

        today_total = await ClientPaymentEventDAO.sum_today_by_admin_id(
            session, cashier_id
        )

        items = [
            CashierLogItem(
                id=row["id"],
                transaction_id=row["transaction_id"],
                client_code=row["client_code"],
                flight=row["flight"],
                paid_amount=row["paid_amount"],
                payment_provider=row["payment_provider"],
                cashier_id=row["cashier_id"],
                created_at=row["created_at"],
            )
            for row in raw_rows
        ]

        return CashierLogResponse(
            items=items,
            total_count=total_count,
            page=page,
            size=size,
            total_pages=total_pages,
            today_total=today_total,
        )

    @staticmethod
    async def adjust_balance(
        body: AdjustBalanceRequest,
        admin: "AdminJWTPayload",
        session: AsyncSession,
    ) -> AdjustBalanceResponse:
        """
        Apply a manual cashier balance correction to a client's account.

        Creates a hidden ``SYS_ADJ:{reason}`` pseudo-transaction on the client's
        record (invisible to user-facing transaction lists) and a corresponding
        ``ClientPaymentEvent`` (visible in the cashier audit log via
        ``GET /payments/cashier-log``).

        Design notes:
          • A positive ``amount`` credits the client — they owe less or receive
            a partial refund (e.g. cashier keyed in too much).
          • A negative ``amount`` debits the client — they owe more (e.g.
            cashier gave too much wallet credit by mistake).
          • The ``ClientPaymentEvent.amount`` stores the signed value so that
            ``today_total`` in the cashier log correctly nets out debits.
          • The returned ``new_wallet_balance`` is the client's net position
            (wallet_balance + debt) after the adjustment is committed.

        Args:
            body:    Validated AdjustBalanceRequest (client_code, amount, reason
                     are all pre-sanitised by Pydantic validators).
            admin:   Authenticated cashier from JWT; admin.admin_id is stored in
                     approved_by_admin_id of the created payment event.
            session: Async DB session — committed inside this method on success.

        Returns:
            AdjustBalanceResponse confirming the created transaction and new balance.

        Raises:
            POSPaymentError: If the client is not found.
        """
        from src.infrastructure.services.client import ClientService

        client_service = ClientService()
        client = await client_service.get_client_by_code(body.client_code, session)
        if not client:
            raise POSPaymentError(
                message=f"'{body.client_code}' kodli mijoz topilmadi.",
            )

        # primary_code is the canonical identifier — resolves extra_code → client_code
        # → legacy_code → str(telegram_id). Must be used for all downstream writes
        # so the transaction is stored under the same key every other part of the
        # system uses for this client.
        canonical_code = client.primary_code

        adj_tx = await ClientTransactionDAO.create_system_adjustment(
            session=session,
            telegram_id=client.telegram_id or 0,
            client_code=canonical_code,
            amount=body.amount,
            reason=body.reason,
        )

        # Store the signed amount so the cashier log correctly reflects direction:
        # negative = debit (client owes more), positive = credit (client owes less).
        # today_total in the cashier log is a net figure — debits reduce it, which
        # is the correct semantic for balance adjustments (unlike cargo payments
        # which are always positive cash inflows).
        #
        # payment_provider="wallet" identifies this as a balance adjustment in the
        # cashier log. The reason is visible in the linked transaction's reys column
        # (shown as "flight" in the log as "SYS_ADJ:{reason}") and in AdminAuditLog.
        await ClientPaymentEventDAO.create(
            session=session,
            transaction_id=adj_tx.id,
            payment_provider="wallet",
            amount=body.amount,
            approved_by_admin_id=admin.admin_id,
        )

        # Flush the admin audit record inside the same transaction so the
        # adjustment and its audit trail are always committed together.
        await AdminAuditLogDAO.log(
            session=session,
            action="POS_ADJUST_BALANCE",
            admin_id=admin.admin_id,
            role_snapshot=admin.role_name,
            details={
                "client_code": canonical_code,
                "amount": body.amount,
                "reason": body.reason,
                "transaction_id": adj_tx.id,
                # "credit" when positive (client owes less), "debit" when negative
                "direction": "credit" if body.amount > 0 else "debit",
            },
        )

        await session.commit()

        # Compute the client's net balance after the committed adjustment.
        balances = await ClientTransactionDAO.get_wallet_balances(
            session, canonical_code
        )
        new_wallet_balance = balances["wallet_balance"] + balances["debt"]

        return AdjustBalanceResponse(
            transaction_id=adj_tx.id,
            client_code=canonical_code,
            amount=body.amount,
            reason=body.reason,
            new_wallet_balance=new_wallet_balance,
        )

    @staticmethod
    async def _load_transaction_with_codes(
        transaction_id: int,
        session: AsyncSession,
    ) -> tuple[object, list[str]]:
        """Load a transaction and resolve all active client-code aliases for it."""
        transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)
        if not transaction:
            raise POSPaymentError(
                message="Transaction not found",
                error_code="TRANSACTION_NOT_FOUND",
            )

        client = await ClientService().get_client_by_code(transaction.client_code, session)
        active_codes = client.active_codes if client and client.active_codes else [transaction.client_code]
        return transaction, active_codes

    @staticmethod
    async def _build_status_update_response(
        session: AsyncSession,
        transaction: object,
        active_codes: list[str],
    ) -> TransactionStatusUpdateResponse:
        """Return the current transaction status payload for POS edit endpoints."""
        status_context = await TransactionViewService.get_status_context(
            session,
            transaction,
            active_codes,
        )
        return TransactionStatusUpdateResponse(
            transaction_id=transaction.id,
            is_taken_away=transaction.is_taken_away,
            taken_away_date=transaction.taken_away_date,
            delivery_request_type=status_context.delivery_request_type,
            delivery_proof_method=status_context.delivery_proof_method,
        )

    @staticmethod
    async def update_taken_status(
        transaction_id: int,
        body: UpdateTakenStatusRequest,
        admin: "AdminJWTPayload",
        session: AsyncSession,
    ) -> TransactionStatusUpdateResponse:
        """Toggle the cargo take-away flag for a single transaction."""
        transaction, active_codes = await PaymentPOSService._load_transaction_with_codes(
            transaction_id,
            session,
        )

        if transaction.is_taken_away == body.is_taken_away:
            raise POSPaymentError(
                message="Transaction already has the requested taken status",
                error_code="NO_STATUS_CHANGE",
            )

        old_value = transaction.is_taken_away
        old_taken_away_date = transaction.taken_away_date

        transaction.is_taken_away = body.is_taken_away
        transaction.taken_away_date = get_current_time() if body.is_taken_away else None

        # When reverting taken-away (true -> false), drop existing warehouse delivery
        # proofs so warehouse staff can re-mark the cargo. Snapshot deleted rows into
        # the audit log so the original evidence (who/when/which photos) survives.
        deleted_proofs_snapshot: list[dict] = []
        s3_keys_to_delete: list[str] = []
        if old_value is True and body.is_taken_away is False:
            existing_proofs = await CargoDeliveryProofDAO.get_by_transaction_id(
                session, transaction.id
            )
            for proof in existing_proofs:
                proof_keys = list(proof.photo_s3_keys or [])
                deleted_proofs_snapshot.append({
                    "id": proof.id,
                    "delivery_method": proof.delivery_method,
                    "photo_s3_keys": proof_keys,
                    "marked_by_admin_id": proof.marked_by_admin_id,
                    "created_at": proof.created_at.isoformat() if proof.created_at else None,
                })
                s3_keys_to_delete.extend(proof_keys)
            if existing_proofs:
                await CargoDeliveryProofDAO.delete_by_transaction_id(
                    session, transaction.id
                )


        await AdminAuditLogDAO.log(
            session=session,
            action="POS_UPDATE_TAKEN_STATUS",
            admin_id=admin.admin_id,
            role_snapshot=admin.role_name,
            details={
                "transaction_id": transaction.id,
                "client_code": transaction.client_code,
                "flight": transaction.reys,
                "field": "is_taken_away",
                "old_value": old_value,
                "new_value": transaction.is_taken_away,
                "old_taken_away_date": old_taken_away_date.isoformat()
                if old_taken_away_date
                else None,
                "new_taken_away_date": transaction.taken_away_date.isoformat()
                if transaction.taken_away_date
                else None,
                "reason": body.reason,
                "source_row_id": transaction.id,
                "deleted_proofs": deleted_proofs_snapshot,
            },
        )
        await session.commit()
        # Post-commit S3 cleanup — fire-and-forget. Audit log retains the keys so
        # any S3 failure can be retried later without re-reading deleted DB rows.
        if s3_keys_to_delete:
            results = await asyncio.gather(
                *(s3_manager.delete_file(key) for key in s3_keys_to_delete),
                return_exceptions=True,
            )
            failed = [
                key for key, ok in zip(s3_keys_to_delete, results)
                if isinstance(ok, Exception) or ok is False
            ]
            if failed:
                logger.warning(
                    "S3 proof cleanup partial failure for tx=%s: %d/%d keys failed: %s",
                    transaction.id,
                    len(failed),
                    len(s3_keys_to_delete),
                    failed,
                )

        return await PaymentPOSService._build_status_update_response(
            session,
            transaction,
            active_codes,
        )

    @staticmethod
    async def update_delivery_request_type(
        transaction_id: int,
        body: UpdateDeliveryRequestTypeRequest,
        admin: "AdminJWTPayload",
        session: AsyncSession,
    ) -> TransactionStatusUpdateResponse:
        """Update the single-flight delivery-request type for one transaction."""
        transaction, active_codes = await PaymentPOSService._load_transaction_with_codes(
            transaction_id,
            session,
        )
        status_context = await TransactionViewService.get_status_context(
            session,
            transaction,
            active_codes,
        )
        if status_context.delivery_request_ambiguous:
            raise POSPaymentError(
                message="Legacy delivery request data is ambiguous for this transaction",
                error_code="AMBIGUOUS_DELIVERY_REQUEST",
            )
        if status_context.delivery_request_id is None:
            raise POSPaymentError(
                message="Delivery request not found for this transaction",
                error_code="DELIVERY_REQUEST_NOT_FOUND",
            )

        delivery_request = await DeliveryRequestDAO.get_by_id(
            session,
            status_context.delivery_request_id,
        )
        if not delivery_request:
            raise POSPaymentError(
                message="Delivery request not found for this transaction",
                error_code="DELIVERY_REQUEST_NOT_FOUND",
            )
        if delivery_request.delivery_type == body.delivery_request_type:
            raise POSPaymentError(
                message="Delivery request type already has the requested value",
                error_code="NO_STATUS_CHANGE",
            )

        old_value = delivery_request.delivery_type
        delivery_request.delivery_type = body.delivery_request_type
        await session.flush()

        await AdminAuditLogDAO.log(
            session=session,
            action="POS_UPDATE_DELIVERY_REQUEST_TYPE",
            admin_id=admin.admin_id,
            role_snapshot=admin.role_name,
            details={
                "transaction_id": transaction.id,
                "client_code": transaction.client_code,
                "flight": transaction.reys,
                "field": "delivery_request_type",
                "old_value": old_value,
                "new_value": delivery_request.delivery_type,
                "reason": body.reason,
                "source_row_id": delivery_request.id,
            },
        )
        await session.commit()

        return await PaymentPOSService._build_status_update_response(
            session,
            transaction,
            active_codes,
        )

    @staticmethod
    async def update_proof_delivery_method(
        transaction_id: int,
        body: UpdateProofDeliveryMethodRequest,
        admin: "AdminJWTPayload",
        session: AsyncSession,
    ) -> TransactionStatusUpdateResponse:
        """Update the latest warehouse proof delivery method for one transaction."""
        transaction, active_codes = await PaymentPOSService._load_transaction_with_codes(
            transaction_id,
            session,
        )
        proofs = await CargoDeliveryProofDAO.get_by_transaction_id(session, transaction.id)
        latest_proof = proofs[0] if proofs else None
        if latest_proof is None:
            raise POSPaymentError(
                message="Delivery proof not found for this transaction",
                error_code="DELIVERY_PROOF_NOT_FOUND",
            )
        if latest_proof.delivery_method == body.delivery_proof_method:
            raise POSPaymentError(
                message="Delivery proof method already has the requested value",
                error_code="NO_STATUS_CHANGE",
            )

        old_value = latest_proof.delivery_method
        latest_proof.delivery_method = body.delivery_proof_method
        await session.flush()

        await AdminAuditLogDAO.log(
            session=session,
            action="POS_UPDATE_PROOF_DELIVERY_METHOD",
            admin_id=admin.admin_id,
            role_snapshot=admin.role_name,
            details={
                "transaction_id": transaction.id,
                "client_code": transaction.client_code,
                "flight": transaction.reys,
                "field": "delivery_proof_method",
                "old_value": old_value,
                "new_value": latest_proof.delivery_method,
                "reason": body.reason,
                "source_row_id": latest_proof.id,
            },
        )
        await session.commit()

        return await PaymentPOSService._build_status_update_response(
            session,
            transaction,
            active_codes,
        )
