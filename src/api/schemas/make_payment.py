"""Pydantic schemas for Make Payment API (user-facing payment flow)."""
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Response Schemas
# ============================================================================

class AvailableFlightItem(BaseModel):
    """Single flight available for payment."""
    flight_name: str
    total_payment: Optional[float] = Field(
        None,
        description="Total payment in UZS. None means report not yet sent by admin.",
    )
    payment_status: Literal["unpaid", "partial"] = Field(
        ...,
        description="Current payment status for this flight.",
    )
    remaining_amount: Optional[float] = Field(
        None,
        description="Remaining amount for partial payments.",
    )


class AvailableFlightsResponse(BaseModel):
    """List of flights available for payment."""
    flights: list[AvailableFlightItem]
    count: int


class FlightPaymentDetailsResponse(BaseModel):
    """Comprehensive payment calculation for a specific flight."""
    flight_name: str
    client_code: str
    total_payment: float = Field(..., description="Total payment amount in UZS")
    total_weight: float = Field(..., description="Total cargo weight in kg")
    price_per_kg_usd: float
    price_per_kg_uzs: float
    extra_charge: float = Field(0, description="Extra charge from static data")
    track_codes: list[str] = Field(default_factory=list)
    wallet_balance: float = Field(0, description="Current wallet balance in UZS")
    partial_allowed: bool = Field(
        ...,
        description="Whether partial payment is allowed (total >= 25000)",
    )
    # Existing partial payment info
    has_existing_partial: bool = False
    existing_paid_amount: Optional[float] = None
    existing_remaining_amount: Optional[float] = None
    # Active payment card
    card_number: Optional[str] = None
    card_owner: Optional[str] = None


# ============================================================================
# Request Schemas
# ============================================================================

class WalletOnlyPaymentRequest(BaseModel):
    """Request to pay fully from wallet balance."""
    flight_name: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0, description="Amount to pay from wallet (UZS)")
    payment_mode: Literal["full", "partial", "full_remaining"] = Field(
        "full",
        description="Payment mode context",
    )

    @field_validator("flight_name")
    @classmethod
    def strip_flight_name(cls, v: str) -> str:
        return v.strip()


class CashPaymentRequest(BaseModel):
    """Request to submit a cash payment."""
    flight_name: str = Field(..., min_length=1, max_length=255)
    wallet_used: float = Field(
        0,
        ge=0,
        description="Amount deducted from wallet (0 if not using wallet)",
    )

    @field_validator("flight_name")
    @classmethod
    def strip_flight_name(cls, v: str) -> str:
        return v.strip()


class OnlinePaymentSubmission(BaseModel):
    """
    Metadata for online payment submission.
    Actual file is sent as UploadFile (multipart form).
    """
    flight_name: str = Field(..., min_length=1, max_length=255)
    payment_mode: Literal["full", "partial", "full_remaining"] = Field(
        "full",
        description="full = pay total, partial = pay custom amount, full_remaining = pay remaining on existing partial",
    )
    paid_amount: float = Field(..., gt=0, description="Amount being paid (UZS)")
    wallet_used: float = Field(
        0,
        ge=0,
        description="Amount deducted from wallet (0 if not using wallet)",
    )

    @field_validator("flight_name")
    @classmethod
    def strip_flight_name(cls, v: str) -> str:
        return v.strip()


# ============================================================================
# Generic Response
# ============================================================================

class PaymentSubmissionResponse(BaseModel):
    """Response after submitting a payment for admin approval."""
    success: bool = True
    message: str
    flight_name: str
    amount: float = Field(..., description="Total amount of this payment")
    wallet_used: float = Field(0, description="Amount deducted from wallet")
    payment_mode: str
