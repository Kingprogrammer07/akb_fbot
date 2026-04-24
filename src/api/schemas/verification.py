"""Pydantic schemas for Client Verification API."""
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


# ============================================================================
# Enums / Literals
# ============================================================================

FilterType = Literal["all", "taken", "not_taken", "partial", "pending"]
SortOrder = Literal["asc", "desc"]
PaymentStatus = Literal["pending", "partial", "paid"]
PaymentType = Literal["online", "cash"]
PaymentProvider = Literal["cash", "click", "payme"]
DeliveryRequestType = Literal["uzpost", "bts", "akb", "yandex"]
DeliveryProofMethod = Literal["uzpost", "bts", "akb", "yandex", "self_pickup"]
BalanceStatus = Literal["debt", "overpaid", "balanced"]


# ============================================================================
# Client Schemas
# ============================================================================

class ClientStats(BaseModel):
    """Client statistics summary."""
    total_payments: int = Field(..., description="Total number of transactions")
    cargo_taken: int = Field(..., description="Number of cargos marked as taken")


class ClientSearchResult(BaseModel):
    """Client search result with basic info and stats."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_code: str
    full_name: str
    telegram_id: Optional[int] = None
    phone: Optional[str] = None
    is_admin: bool = False
    stats: ClientStats
    flights: list[str] = Field(default_factory=list, description="List of flight codes")

    # Client balance aggregation
    client_balance: float = Field(
        0.0,
        description="Sum of all payment_balance_difference. Negative=debt, Positive=overpaid"
    )
    client_balance_status: BalanceStatus = Field(
        "balanced",
        description="Balance status: 'debt', 'overpaid', or 'balanced'"
    )


class ClientSearchResponse(BaseModel):
    """Response for client search endpoint."""
    client: ClientSearchResult


class ClientFullInfo(BaseModel):
    """Full client information for detailed view."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_code: str
    full_name: str
    telegram_id: Optional[int] = None
    phone: Optional[str] = None
    passport_series: Optional[str] = None
    pinfl: Optional[str] = None
    date_of_birth: Optional[date] = None
    region: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    is_admin: bool = False
    referral_count: int = 0
    extra_passports_count: int = 0
    passport_image_file_ids: list[str] = Field(
        default_factory=list,
        description="Telegram file_ids for passport images. "
                    "Use GET /api/v1/clients/{client_id}/passport-images/metadata to resolve URLs."
    )
    created_at: datetime

    # Payment stats
    transaction_count: int = 0
    latest_transaction: Optional["TransactionSummary"] = None

    # Client balance aggregation
    client_balance: float = Field(
        0.0,
        description="Sum of all payment_balance_difference. Negative=debt, Positive=overpaid"
    )
    client_balance_status: BalanceStatus = Field(
        "balanced",
        description="Balance status: 'debt', 'overpaid', or 'balanced'"
    )


class ClientFullInfoResponse(BaseModel):
    """Response for full client info endpoint."""
    client: ClientFullInfo


# ============================================================================
# Transaction Schemas
# ============================================================================

class TransactionSummary(BaseModel):
    """Summary of a transaction for listings."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    flight: str = Field(..., alias="reys")
    row_number: int = Field(..., alias="qator_raqami")
    amount: float = Field(..., alias="summa", description="Expected total payment (calculated)")
    weight: Optional[str] = Field(None, alias="vazn")
    payment_status: PaymentStatus
    payment_type: PaymentType
    is_taken_away: bool
    taken_away_date: Optional[datetime] = None
    has_receipt: bool = False
    created_at: datetime

    # Payment tracking fields
    paid_amount: float = Field(0.0, description="Actual amount paid by client")
    total_amount: Optional[float] = Field(None, description="Expected total payment")
    remaining_amount: float = Field(0.0, description="Amount remaining to pay")
    payment_balance_difference: float = Field(
        0.0,
        description="paid_amount - expected_total. Negative=debt, Positive=overpaid, Zero=exact"
    )
    delivery_request_type: Optional[DeliveryRequestType] = None
    delivery_proof_method: Optional[DeliveryProofMethod] = None


class TransactionDetail(TransactionSummary):
    """Detailed transaction with additional fields."""
    client_code: str
    telegram_id: Optional[int] = None
    payment_deadline: Optional[datetime] = None
    receipt_file_id: Optional[str] = Field(None, alias="payment_receipt_file_id")


class TransactionListRequest(BaseModel):
    """Request parameters for transaction list - ALL REQUIRED."""
    client_code: str = Field(..., min_length=1, description="Client code (required)")
    filter_type: FilterType = Field(..., description="Filter type (required)")
    sort_order: SortOrder = Field(..., description="Sort order (required)")
    flight_code: Optional[str] = Field(None, description="Flight filter (optional)")
    limit: int = Field(..., ge=1, le=100, description="Items per page (required)")
    offset: int = Field(..., ge=0, description="Offset for pagination (required)")


class TransactionListResponse(BaseModel):
    """Paginated transaction list response."""
    transactions: list[TransactionSummary]
    total_count: int
    limit: int
    offset: int
    total_pages: int
    filter_type: FilterType
    sort_order: SortOrder
    flight_filter: Optional[str] = None


class MarkTakenRequest(BaseModel):
    """Request to mark transaction as cargo taken."""
    is_taken_away: bool = True


class MarkTakenResponse(BaseModel):
    """Response after marking transaction as taken."""
    success: bool
    transaction_id: int
    is_taken_away: bool
    taken_away_date: Optional[datetime] = None
    message: str


# ============================================================================
# Unpaid Cargo Schemas
# ============================================================================

class UnpaidCargoItem(BaseModel):
    """Unpaid cargo item from flight_cargo table."""
    model_config = ConfigDict(from_attributes=True)

    cargo_id: int
    flight: str = Field(..., alias="flight_name")
    row_number: int
    weight: float
    price_per_kg: float
    expected_amount: float = Field(..., alias="total_payment", description="Expected total in UZS")
    currency: str = "UZS"
    payment_status: Literal["pending"] = "pending"
    created_at: datetime


class UnpaidCargoListRequest(BaseModel):
    """Request parameters for unpaid cargo list - ALL REQUIRED."""
    filter_type: Literal["all", "pending"] = Field(..., description="Filter type (required)")
    sort_order: SortOrder = Field(..., description="Sort order (required)")
    flight_code: Optional[str] = Field(None, description="Flight filter (optional)")
    limit: int = Field(..., ge=1, le=100, description="Items per page (required)")
    offset: int = Field(..., ge=0, description="Offset for pagination (required)")


class UnpaidCargoListResponse(BaseModel):
    """Response for unpaid cargo list endpoint."""
    items: list[UnpaidCargoItem]
    total_count: int
    limit: int
    offset: int
    total_pages: int
    filter_type: str
    sort_order: SortOrder
    flight_filter: Optional[str] = None


# ============================================================================
# Flight Schemas
# ============================================================================

class FlightListRequest(BaseModel):
    """Request parameters for flight list - filters required."""
    include_sheets: bool = Field(..., description="Include Google Sheets flights (required)")
    include_database: bool = Field(..., description="Include database flights (required)")


class FlightListResponse(BaseModel):
    """List of available flights for a client."""
    flights: list[str]
    source: Literal["database", "sheets", "combined"]


class FlightMatch(BaseModel):
    """Flight match from Google Sheets."""
    flight_name: str
    row_number: int
    client_code: str
    track_codes: list[str] = Field(default_factory=list)


# ============================================================================
# Cargo Schemas
# ============================================================================

class CargoPhoto(BaseModel):
    """Cargo photo information.

    ARCHITECTURE v2.0: Use file_id with metadata endpoints.
    URL field is deprecated - use resolve endpoints instead.
    """
    file_id: str = Field(..., description="Telegram file_id")
    url: Optional[str] = Field(
        None,
        deprecated=True,
        description="DEPRECATED: Use GET /api/v1/flights/photos/{cargo_id}/metadata instead"
    )


class CargoImageSchema(BaseModel):
    """Cargo image with file_id metadata.

    ARCHITECTURE v2.0: Use file_id with metadata endpoints instead of binary streaming.
    Resolve URLs via GET /api/v1/flights/photos/{cargo_id}/metadata
    """
    file_id: str = Field(..., description="Telegram file_id - use with metadata endpoints")
    telegram_url: Optional[str] = Field(
        None,
        description="Temporary Telegram URL (valid ~1 hour). "
                    "Use /api/v1/flights/photos/{cargo_id}/resolve to refresh."
    )


class TransactionCargoImagesResponse(BaseModel):
    """Response for transaction cargo images endpoint."""
    transaction_id: int
    flight: str
    cargo_id: Optional[int] = Field(None, description="FlightCargo ID if found")
    images: list[CargoImageSchema] = Field(default_factory=list)
    total_count: int = 0


class CargoDetail(BaseModel):
    """Detailed cargo information."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    flight_name: str
    client_id: str
    weight_kg: Optional[float] = None
    price_per_kg: Optional[float] = None
    comment: Optional[str] = None
    is_sent: bool
    photos: list[CargoPhoto] = Field(default_factory=list)
    created_at: datetime


class CargoListResponse(BaseModel):
    """Response for cargo list endpoint."""
    cargos: list[CargoDetail]
    total_count: int


# ============================================================================
# Flight Payment Summary Schema
# ============================================================================

class FlightPaymentSummary(BaseModel):
    """Payment summary for all cargos of a client in a flight."""
    total_weight: float
    price_per_kg_usd: float
    price_per_kg_uzs: float
    extra_charge: float
    total_payment: float
    track_codes: list[str] = Field(default_factory=list)


# Resolve forward references
ClientFullInfo.model_rebuild()
