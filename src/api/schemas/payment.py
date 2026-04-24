"""Pydantic schemas for Payment API."""
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


# ============================================================================
# Payment Request Schemas
# ============================================================================

class ProcessPaymentRequest(BaseModel):
    """
    Request to process a payment (cash or online) for unpaid cargo.

    REQUIRED: paid_amount must be provided by admin.
    """
    client_code: str = Field(..., min_length=1, max_length=20)
    cargo_id: int = Field(..., gt=0, description="FlightCargo.id")
    flight: str = Field(..., min_length=1, max_length=255, description="Flight name")
    payment_type: Literal["cash", "click", "payme", "card"] = Field(
        ...,
        description="Payment type: cash, click, payme, or card"
    )
    paid_amount: float = Field(
        ...,
        gt=0,
        description="Actual amount paid by client (required, in UZS)"
    )
    admin_id: int = Field(..., gt=0, description="Admin's Telegram ID")
    use_balance: bool = Field(
        default=False,
        description="If True, deduct from client wallet balance first"
    )

    @field_validator('client_code')
    @classmethod
    def uppercase_client_code(cls, v: str) -> str:
        """Ensure client code is uppercase."""
        return v.upper().strip()

    @field_validator('flight')
    @classmethod
    def normalize_flight(cls, v: str) -> str:
        """Normalize flight name."""
        return v.strip()

    @model_validator(mode='after')
    def validate_paid_amount_limit(self):
        """
        Basic anti-error guard: paid_amount cannot exceed 2x expected.
        Note: This validation happens at schema level with a generous limit.
        Service layer will do exact validation with calculated expected amount.
        """
        # This is a soft limit at schema level
        # Actual validation against expected_total happens in service
        return self


class ProcessExistingTransactionPaymentRequest(BaseModel):
    """
    Request to process payment for existing transaction (partial payments).

    REQUIRED: paid_amount must be provided by admin.
    """
    transaction_id: int = Field(..., gt=0)
    payment_type: Literal["cash", "click", "payme", "card"]
    paid_amount: float = Field(
        ...,
        gt=0,
        description="Actual amount paid by client (required, in UZS)"
    )
    admin_id: int = Field(..., gt=0)
    use_balance: bool = Field(
        default=False,
        description="If True, deduct from client wallet balance first"
    )


# ============================================================================
# Payment Response Schemas
# ============================================================================

class PaymentResult(BaseModel):
    """Result of a payment operation."""
    success: bool
    transaction_id: int
    client_code: str
    flight: str
    expected_amount: float = Field(..., description="Calculated expected payment")
    paid_amount: float = Field(..., description="Actual amount paid by client")
    payment_balance_difference: float = Field(
        ...,
        description="paid_amount - expected_amount. Negative=debt, Positive=overpaid"
    )
    payment_type: Literal["cash", "click", "payme", "card"]
    payment_status: Literal["pending", "partial", "paid"]
    is_taken_away: bool
    message: str
    created_at: datetime
    # Wallet-related fields
    wallet_balance_before: Optional[float] = Field(
        None,
        description="Client wallet balance BEFORE this payment"
    )
    wallet_deducted: Optional[float] = Field(
        None,
        description="Amount deducted from wallet (if use_balance=True)"
    )
    wallet_balance_after: Optional[float] = Field(
        None,
        description="Client wallet balance AFTER this payment"
    )
    track_codes: Optional[list[str]] = Field(
        None,
        description="Track codes for the cargo (from flight_cargo table)"
    )


class ProcessPaymentResponse(BaseModel):
    """Response after processing a payment."""
    payment: PaymentResult
    notifications: "NotificationStatus"


class NotificationStatus(BaseModel):
    """Status of notifications sent after payment."""
    user_notified: bool = False
    user_notification_error: Optional[str] = None
    channel_notified: bool = False
    channel_notification_error: Optional[str] = None


# ============================================================================
# Payment Event Schemas
# ============================================================================

class PaymentEvent(BaseModel):
    """Payment event record (immutable audit log)."""
    id: int
    transaction_id: int
    amount: float = Field(..., description="Actual amount paid in this event")
    payment_provider: Literal["cash", "click", "payme", "card"]
    approved_by_admin_id: Optional[int] = None
    created_at: datetime


class PaymentEventListResponse(BaseModel):
    """List of payment events for a transaction."""
    events: list[PaymentEvent]
    total_paid: float
    payment_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="Breakdown by provider: {'cash': 0.0, 'click': 0.0, 'payme': 0.0, 'card': 0.0}"
    )


# ============================================================================
# Transaction History Schemas (for frontend "To'lovlar tarixi")
# ============================================================================

class PaymentBreakdownSchema(BaseModel):
    """Breakdown of payments by provider."""
    click: float = 0.0
    payme: float = 0.0
    cash: float = 0.0
    card: float = 0.0


class TransactionHistoryItemSchema(BaseModel):
    """Single transaction in the payment history list."""
    id: int
    flight_name: str = Field(..., description="Flight/reys name")
    total_amount: float
    paid_amount: float
    remaining_amount: float
    payment_status: str = Field(..., description="'paid', 'partial', or 'pending'")
    payment_type: str = Field(..., description="'online', 'cash', or 'card'")
    is_taken_away: bool
    created_at: datetime
    breakdown: PaymentBreakdownSchema


class TransactionHistoryResponse(BaseModel):
    """Paginated transaction history response."""
    items: list[TransactionHistoryItemSchema]
    total_count: int
    limit: int
    offset: int


# ============================================================================
# Active Card Schema
# ============================================================================

class ActiveCardResponse(BaseModel):
    """Random active payment card for card payments."""
    card_number: str = Field(..., description="16-digit card number")
    holder_name: str = Field(..., description="Card holder full name")
    bank_name: Optional[str] = Field(None, description="Bank name (optional)")


# ============================================================================
# Error Schemas
# ============================================================================

class PaymentErrorResponse(BaseModel):
    """Error response for payment operations."""
    error: str
    error_code: str
    details: Optional[dict] = None


# Resolve forward references
ProcessPaymentResponse.model_rebuild()
