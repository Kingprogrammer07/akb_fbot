"""Shared transaction enrichment + response mapping helpers for admin/POS views."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.verification import TransactionDetail, TransactionSummary
from src.infrastructure.database.models.cargo_delivery_proof import CargoDeliveryProof
from src.infrastructure.database.models.delivery_request import DeliveryRequest
from src.infrastructure.schemas.pos_schemas import BulkItemResult

if TYPE_CHECKING:
    from src.infrastructure.database.models.client_transaction import ClientTransaction

logger = logging.getLogger(__name__)

ACTIVE_DELIVERY_REQUEST_STATUSES = ("pending", "approved")


@dataclass(slots=True)
class TransactionStatusContext:
    """Resolved delivery-related context for a single transaction row."""

    delivery_request_id: int | None = None
    delivery_request_type: str | None = None
    delivery_request_ambiguous: bool = False
    delivery_proof_id: int | None = None
    delivery_proof_method: str | None = None


class TransactionViewService:
    """Build enriched transaction read models without duplicating router logic."""

    @staticmethod
    def _normalize_active_codes(
        transaction: "ClientTransaction",
        active_codes: Iterable[str] | None,
    ) -> set[str]:
        candidates = [transaction.client_code]
        if active_codes:
            candidates = [*active_codes]
        return {
            str(code).strip().upper()
            for code in candidates
            if code is not None and str(code).strip()
        }

    @staticmethod
    def _parse_request_flights(raw_value: str) -> list[str]:
        """Parse delivery_request.flight_names JSON into normalized flight codes."""
        try:
            parsed = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Skipping delivery request with invalid flight_names payload: %r", raw_value)
            return []

        if isinstance(parsed, list):
            flights = parsed
        else:
            flights = [parsed]

        normalized: list[str] = []
        for flight in flights:
            if flight is None:
                continue
            text = str(flight).strip().upper()
            if text:
                normalized.append(text)
        return normalized

    @staticmethod
    def _calculate_payment_view(
        transaction: "ClientTransaction",
    ) -> tuple[float, float, float, float]:
        """Derive the normalized payment fields used by admin-facing read models."""
        if transaction.total_amount is not None:
            total_amount = float(transaction.total_amount)
        else:
            total_amount = float(transaction.summa or 0)

        if transaction.paid_amount is not None:
            paid_amount = float(transaction.paid_amount)
        else:
            paid_amount = (
                float(transaction.summa or 0)
                if transaction.payment_status == "paid"
                else 0.0
            )

        if transaction.remaining_amount is not None:
            remaining_amount = float(transaction.remaining_amount)
        else:
            remaining_amount = max(total_amount - paid_amount, 0.0)

        payment_balance_difference = (
            getattr(transaction, "payment_balance_difference", 0.0) or 0.0
        )
        return total_amount, paid_amount, remaining_amount, float(payment_balance_difference)

    @classmethod
    async def get_status_map(
        cls,
        session: AsyncSession,
        transactions: Iterable["ClientTransaction"],
        active_codes_by_transaction: dict[int, Iterable[str]] | None = None,
    ) -> dict[int, TransactionStatusContext]:
        """Resolve delivery-request + delivery-proof context for multiple transactions."""
        transaction_list = [tx for tx in transactions if getattr(tx, "id", None) is not None]
        if not transaction_list:
            return {}

        contexts = {
            tx.id: TransactionStatusContext()
            for tx in transaction_list
        }
        normalized_codes_by_transaction = {
            tx.id: cls._normalize_active_codes(
                tx,
                active_codes_by_transaction.get(tx.id) if active_codes_by_transaction else None,
            )
            for tx in transaction_list
        }
        transaction_ids = [tx.id for tx in transaction_list]
        transaction_flights = {
            tx.id: str(tx.reys or "").strip().upper()
            for tx in transaction_list
        }

        proof_rows = (
            await session.execute(
                select(CargoDeliveryProof)
                .where(CargoDeliveryProof.transaction_id.in_(transaction_ids))
                .order_by(
                    CargoDeliveryProof.transaction_id.asc(),
                    CargoDeliveryProof.created_at.desc(),
                    CargoDeliveryProof.id.desc(),
                )
            )
        ).scalars().all()

        for proof in proof_rows:
            context = contexts.get(proof.transaction_id)
            if not context or context.delivery_proof_id is not None:
                continue
            context.delivery_proof_id = proof.id
            context.delivery_proof_method = proof.delivery_method

        all_client_codes = sorted(
            {
                code
                for codes in normalized_codes_by_transaction.values()
                for code in codes
            }
        )
        if not all_client_codes:
            return contexts

        delivery_requests = (
            await session.execute(
                select(DeliveryRequest)
                .where(
                    func.upper(DeliveryRequest.client_code).in_(all_client_codes),
                    DeliveryRequest.status.in_(ACTIVE_DELIVERY_REQUEST_STATUSES),
                )
                .order_by(DeliveryRequest.created_at.desc(), DeliveryRequest.id.desc())
            )
        ).scalars().all()

        for transaction in transaction_list:
            context = contexts[transaction.id]
            target_codes = normalized_codes_by_transaction[transaction.id]
            target_flight = transaction_flights[transaction.id]
            exact_matches: list[DeliveryRequest] = []
            has_multi_flight_match = False

            for request in delivery_requests:
                request_code = str(request.client_code or "").strip().upper()
                if request_code not in target_codes:
                    continue

                request_flights = cls._parse_request_flights(request.flight_names)
                if target_flight not in request_flights:
                    continue

                if len(request_flights) != 1:
                    has_multi_flight_match = True
                    continue

                exact_matches.append(request)
                if len(exact_matches) > 1:
                    break

            if len(exact_matches) == 1 and not has_multi_flight_match:
                context.delivery_request_id = exact_matches[0].id
                context.delivery_request_type = exact_matches[0].delivery_type
            elif len(exact_matches) > 1 or has_multi_flight_match:
                context.delivery_request_ambiguous = True

        return contexts

    @classmethod
    async def get_status_context(
        cls,
        session: AsyncSession,
        transaction: "ClientTransaction",
        active_codes: Iterable[str] | None = None,
    ) -> TransactionStatusContext:
        """Resolve delivery-related context for a single transaction."""
        status_map = await cls.get_status_map(
            session,
            [transaction],
            active_codes_by_transaction={transaction.id: active_codes or [transaction.client_code]},
        )
        return status_map.get(transaction.id, TransactionStatusContext())

    @classmethod
    def build_transaction_summary(
        cls,
        transaction: "ClientTransaction",
        context: TransactionStatusContext | None = None,
    ) -> TransactionSummary:
        """Map an ORM transaction row into the shared summary response shape."""
        status = context or TransactionStatusContext()
        total_amount, paid_amount, remaining_amount, balance_difference = (
            cls._calculate_payment_view(transaction)
        )
        return TransactionSummary(
            id=transaction.id,
            reys=transaction.reys,
            qator_raqami=transaction.qator_raqami,
            summa=float(transaction.summa) if transaction.summa else 0.0,
            vazn=transaction.vazn,
            payment_status=transaction.payment_status,
            payment_type="cash" if transaction.payment_type == "cash" else "online",
            is_taken_away=transaction.is_taken_away,
            taken_away_date=transaction.taken_away_date,
            has_receipt=bool(transaction.payment_receipt_file_id),
            created_at=transaction.created_at,
            paid_amount=paid_amount,
            total_amount=total_amount if transaction.total_amount else None,
            remaining_amount=remaining_amount,
            payment_balance_difference=balance_difference,
            delivery_request_type=status.delivery_request_type,
            delivery_proof_method=status.delivery_proof_method,
        )

    @classmethod
    def build_transaction_detail(
        cls,
        transaction: "ClientTransaction",
        context: TransactionStatusContext | None = None,
    ) -> TransactionDetail:
        """Map an ORM transaction row into the detailed response shape."""
        summary = cls.build_transaction_summary(transaction, context)
        return TransactionDetail(
            **summary.model_dump(),
            client_code=transaction.client_code,
            telegram_id=transaction.telegram_id,
            payment_deadline=transaction.payment_deadline,
            payment_receipt_file_id=transaction.payment_receipt_file_id,
        )

    @staticmethod
    def build_bulk_item_result(
        result: BulkItemResult,
        context: TransactionStatusContext | None = None,
    ) -> BulkItemResult:
        """Attach delivery-related status context to an existing POS bulk result."""
        status = context or TransactionStatusContext()
        return result.model_copy(
            update={
                "delivery_request_type": status.delivery_request_type,
                "delivery_proof_method": status.delivery_proof_method,
            }
        )
