"""Pydantic schemas for Warehouse (ombor) API endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Delivery method enum (kept as Literal for strict validation + OpenAPI docs)
# ---------------------------------------------------------------------------

DeliveryMethod = Literal["uzpost", "bts", "akb", "yandex", "self_pickup"]

DELIVERY_METHOD_LABELS: dict[str, str] = {
    "uzpost": "UzPost",
    "bts": "BTS",
    "akb": "AKB yetkazib berish",
    "yandex": "Yandex",
    "self_pickup": "O'zi olib ketdi",
}

# ---------------------------------------------------------------------------
# Payment / taken-away filter enums
# ---------------------------------------------------------------------------

PaymentStatusFilter = Literal["all", "paid", "unpaid", "partial"]
TakenStatusFilter = Literal["all", "taken", "not_taken"]


# ---------------------------------------------------------------------------
# Flight dropdown option (last N flights with stats)
# ---------------------------------------------------------------------------

class WarehouseFlightOption(BaseModel):
    """One flight entry in the dropdown, with transaction/client counts."""

    flight_name: str
    tx_count: int
    user_count: int
    latest_at: datetime


class WarehouseFlightsResponse(BaseModel):
    """List of recent flights for the warehouse flight-picker dropdown."""

    items: list[WarehouseFlightOption]


# ---------------------------------------------------------------------------
# Transaction row returned to the warehouse worker
# ---------------------------------------------------------------------------

class WarehouseTransactionItem(BaseModel):
    """Single cargo transaction row as seen by a warehouse worker."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    client_code: str
    client_full_name: str | None = None   # injected by the router (not on the ORM model)
    client_phone: str | None = None       # injected by the router
    flight_name: str = Field(alias="reys")
    row_number: int = Field(alias="qator_raqami")
    weight: str = Field(alias="vazn")
    total_amount: float | None
    paid_amount: float
    remaining_amount: float
    payment_status: str
    is_taken_away: bool
    taken_away_date: datetime | None
    has_proof: bool = False               # True if at least one CargoDeliveryProof exists
    created_at: datetime


class WarehouseFlightTransactionsResponse(BaseModel):
    """Paginated list of transactions for a single flight."""

    flight_name: str
    items: list[WarehouseTransactionItem]
    total_count: int
    total_pages: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Mark-taken response
# ---------------------------------------------------------------------------

class DeliveryProofResponse(BaseModel):
    """Proof record returned after a successful mark-taken operation."""

    model_config = ConfigDict(from_attributes=True)

    proof_id: int
    transaction_id: int
    delivery_method: str
    photo_s3_keys: list[str]
    marked_by_admin_id: int | None
    created_at: datetime


class MarkTakenAwayResponse(BaseModel):
    """Full response after marking cargo as taken-away."""

    transaction_id: int
    client_code: str
    flight_name: str
    delivery_method: str
    delivery_method_label: str
    photo_count: int
    proof: DeliveryProofResponse
    telegram_notified: bool
    message: str


class BulkMarkTakenAwayResponse(BaseModel):
    """Response after marking multiple cargos as taken-away."""

    transaction_ids: list[int]
    client_code: str
    delivery_method: str
    delivery_method_label: str
    photo_count: int
    proofs_created: int
    telegram_notified: bool
    message: str


# ---------------------------------------------------------------------------
# Warehouse worker own activity log
# (reads from cargo_delivery_proofs — NOT admin_audit_logs)
# ---------------------------------------------------------------------------

class WarehouseActivityItem(BaseModel):
    """
    One take-away event in the warehouse worker's own activity log.

    Includes transaction context and presigned photo URLs so the frontend
    can display both the cargo info and the proof images inline.
    """

    proof_id: int
    transaction_id: int
    client_code: str | None
    flight_name: str | None
    total_amount: float | None
    paid_amount: float | None
    remaining_amount: float | None
    payment_status: str | None
    delivery_method: str
    delivery_method_label: str
    photo_urls: list[str]   # presigned S3 URLs, valid for a limited time
    photo_count: int
    created_at: datetime


class WarehouseActivityResponse(BaseModel):
    """Paginated self-activity log for a warehouse worker."""

    items: list[WarehouseActivityItem]
    total_count: int
    total_pages: int
    page: int
    size: int


class WarehouseTransactionsSearchResponse(BaseModel):
    """Paginated transaction search results across all flights (no flight filter required)."""

    items: list[WarehouseTransactionItem]
    total_count: int
    total_pages: int
    page: int
    size: int


class GroupedTransactionItem(BaseModel):
    id: int
    qator_raqami: int
    vazn: str
    summa: float
    payment_status: str
    remaining_amount: float
    is_taken_away: bool
    taken_away_date: datetime | None
    comment: str | None
    has_proof: bool


class FlightGroup(BaseModel):
    flight_name: str
    total_weight_kg: float
    total_amount: float
    total_remaining_amount: float
    flight_cargo_photos: list[str]  # presigned URLs for cargo from China
    transactions: list[GroupedTransactionItem]


class ClientGroup(BaseModel):
    client_code: str
    full_name: str | None
    phone: str | None
    wallet_balance: float
    debt: float
    total_unpaid_amount: float
    flights: list[FlightGroup]


class WarehouseGroupedSearchResponse(BaseModel):
    """Grouped transaction search results."""
    items: list[ClientGroup]
    total_count: int
    page: int
    size: int

