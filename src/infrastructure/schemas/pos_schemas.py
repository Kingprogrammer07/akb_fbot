"""POS (Point of Sale) Fast Cashier — Pydantic schemas.

Covers four POS endpoints:
  • POST /payments/process-bulk       — atomic multi-cargo payment
  • GET  /payments/cashier-log        — personal cashier audit log
  • POST /payments/adjust-balance     — manual balance correction (SYS_ADJ)
  • GET  /payments/all-cashier-logs   — super-admin aggregate log (all cashiers)
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PaymentProvider = Literal["cash", "click", "payme", "card"]
DeliveryRequestType = Literal["uzpost", "bts", "akb", "yandex"]
DeliveryProofMethod = Literal["uzpost", "bts", "akb", "yandex", "self_pickup"]


# ---------------------------------------------------------------------------
# Bulk Payment — Request
# ---------------------------------------------------------------------------


class BulkPaymentItem(BaseModel):
    """A single cargo payment within an atomic bulk request."""

    cargo_id: int = Field(..., gt=0, description="FlightCargo.id")
    flight: str = Field(..., min_length=1, max_length=255, description="Flight name")
    client_code: str = Field(..., min_length=1, max_length=20)
    paid_amount: float = Field(..., ge=0, description="Actual amount paid (UZS). 0 is valid when use_balance=True covers the full cargo cost.")
    payment_type: PaymentProvider = Field(..., description="Payment provider")
    use_balance: bool = Field(
        default=False,
        description="If True, deduct from client wallet balance before cash",
    )
    card_id: int | None = Field(
        default=None,
        description="PaymentCard.id — required when payment_type='card'",
    )

    @field_validator("card_id")
    @classmethod
    def _card_id_required_for_card_payments(cls, v, info):
        if info.data.get("payment_type") == "card" and v is None:
            raise ValueError("card_id is required when payment_type='card'")
        return v

    @field_validator("client_code")
    @classmethod
    def _normalize_client_code(cls, v: str) -> str:
        return v.upper().strip()

    @field_validator("flight")
    @classmethod
    def _normalize_flight(cls, v: str) -> str:
        return v.strip()


class BulkPaymentRequest(BaseModel):
    """
    Atomic bulk payment request.

    All items are processed inside a single database transaction.
    If any item fails validation or processing, the entire batch is rejected
    and no records are written.
    """

    items: list[BulkPaymentItem] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="1–50 cargo payment items",
    )
    cashier_note: str | None = Field(
        None,
        max_length=500,
        description="Optional free-text note recorded in the audit log",
    )


# ---------------------------------------------------------------------------
# Bulk Payment — Response
# ---------------------------------------------------------------------------


class BulkItemResult(BaseModel):
    """Processing result for a single item within a bulk payment response."""

    model_config = ConfigDict(from_attributes=True)

    cargo_id: int
    client_code: str
    flight: str
    transaction_id: int
    paid_amount: float
    expected_amount: float
    payment_status: str
    is_taken_away: bool
    delivery_request_type: DeliveryRequestType | None = None
    delivery_proof_method: DeliveryProofMethod | None = None


class BulkPaymentResponse(BaseModel):
    """Response for a successfully committed atomic bulk payment."""

    processed_count: int = Field(..., description="Number of items processed")
    total_paid: float = Field(..., description="Sum of all paid amounts (UZS)")
    results: list[BulkItemResult]


# ---------------------------------------------------------------------------
# Cashier Log — Response
# ---------------------------------------------------------------------------


class CashierLogItem(BaseModel):
    """A single entry in a cashier payment audit log.

    ``cashier_id`` is populated only in the super-admin aggregate view
    (``GET /payments/all-cashier-logs``); it is ``None`` in the personal log.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    client_code: str | None = None
    flight: str | None = None
    paid_amount: float
    payment_provider: str
    cashier_id: int | None = None
    created_at: datetime


class CashierLogResponse(BaseModel):
    """Paginated cashier log with daily totals."""

    items: list[CashierLogItem]
    total_count: int
    page: int
    size: int
    total_pages: int
    today_total: float = Field(..., description="Sum of amounts processed today (UZS)")


# ---------------------------------------------------------------------------
# Balance Adjustment — Request / Response
# ---------------------------------------------------------------------------


class AdjustBalanceRequest(BaseModel):
    """
    Manual cashier balance correction.

    Creates a hidden SYS_ADJ pseudo-transaction on the client's account and
    writes a PaymentEvent so the adjustment appears in the cashier audit log.

    amount > 0  →  credit  (client owes less / gets a refund)
    amount < 0  →  debit   (client owes more / correction for overpayment)
    """

    client_code: str = Field(..., min_length=1, max_length=20)
    amount: float = Field(
        ...,
        description="Non-zero signed UZS amount. Positive = credit, negative = debit.",
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Short reason slug — becomes the SYS_ADJ suffix in the DB",
    )

    @field_validator("client_code")
    @classmethod
    def _normalize_client_code(cls, v: str) -> str:
        return v.upper().strip()

    @field_validator("amount")
    @classmethod
    def _nonzero_amount(cls, v: float) -> float:
        if v == 0.0:
            raise ValueError("amount cannot be zero")
        return v

    @field_validator("reason")
    @classmethod
    def _sanitize_reason(cls, v: str) -> str:
        # Prevent colon injection into "SYS_ADJ:{reason}" stored in the reys column.
        sanitized = v.strip().replace(":", "_").replace(" ", "_")
        if not sanitized:
            raise ValueError("reason cannot be empty after sanitization")
        return sanitized


class AdjustBalanceResponse(BaseModel):
    """Confirmation of a completed balance adjustment."""

    transaction_id: int = Field(..., description="ID of the created SYS_ADJ pseudo-transaction")
    client_code: str
    amount: float
    reason: str
    new_wallet_balance: float = Field(
        ..., description="Client's net wallet balance after the adjustment (UZS)"
    )


class _POSReasonMixin(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def _sanitize_reason(cls, value: str) -> str:
        sanitized = value.strip()
        if not sanitized:
            raise ValueError("reason cannot be empty")
        return sanitized


class UpdateTakenStatusRequest(_POSReasonMixin):
    is_taken_away: bool


class UpdateDeliveryRequestTypeRequest(_POSReasonMixin):
    delivery_request_type: DeliveryRequestType


class UpdateProofDeliveryMethodRequest(_POSReasonMixin):
    delivery_proof_method: DeliveryProofMethod


class TransactionStatusUpdateResponse(BaseModel):
    success: bool = True
    transaction_id: int
    is_taken_away: bool
    taken_away_date: datetime | None = None
    delivery_request_type: DeliveryRequestType | None = None
    delivery_proof_method: DeliveryProofMethod | None = None
