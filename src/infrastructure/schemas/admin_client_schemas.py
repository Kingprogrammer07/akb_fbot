"""
Pydantic schemas for the Admin Clients management API.

Covers:
  - Paginated client search
  - Full client detail (personal + financial summary)
  - Personal data partial update (no financial fields)
  - Paginated client finance history with filters
  - Per-transaction payment event detail + provider breakdown
  - Unique flights list (for frontend dropdown)
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class ClientSearchItem(BaseModel):
    """Minimal client representation for search result rows."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    primary_code: str
    full_name: str
    phone: str | None = None
    region: str | None = None
    district: str | None = None
    is_logged_in: bool
    created_at: datetime


class ClientSearchResponse(BaseModel):
    """Paginated client search response."""

    items: list[ClientSearchItem]
    total_count: int
    total_pages: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

class AdminClientDetailResponse(BaseModel):
    """
    Full client record as seen by an admin.

    Financial summary (wallet_balance, debt, net_balance) is always included
    and is read-only; modifying finances requires a separate permission.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    primary_code: str
    full_name: str
    phone: str | None = None
    passport_series: str | None = None
    pinfl: str | None = None
    date_of_birth: date | None = None
    region: str | None = None
    district: str | None = None
    address: str | None = None
    username: str | None = None
    telegram_id: int | None = None
    is_logged_in: bool
    created_at: datetime
    # Financial summary (requires clients:finance_read at the deeper endpoints;
    # here we return a quick balance snapshot alongside the profile).
    wallet_balance: float = 0.0
    debt: float = 0.0
    net_balance: float = 0.0
    referral_count: int = 0
    extra_passport_count: int = 0


# ---------------------------------------------------------------------------
# Personal update (clients:update)
# ---------------------------------------------------------------------------

class UpdateClientPersonalRequest(BaseModel):
    """
    Only personal, non-financial fields may be updated through this schema.

    Financial adjustments (balance, debt) are intentionally absent —
    those require the ``pos:adjust`` POS endpoint and a separate RBAC grant.
    """

    full_name: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    phone: Annotated[str, Field(max_length=20)] | None = None
    date_of_birth: date | None = None
    region: Annotated[str, Field(max_length=128)] | None = None
    district: Annotated[str, Field(max_length=128)] | None = None
    address: Annotated[str, Field(max_length=512)] | None = None


# ---------------------------------------------------------------------------
# Finance history (clients:finance_read)
# ---------------------------------------------------------------------------

SortOrder = Literal["asc", "desc"]
FilterType = Literal["all", "paid", "unpaid", "partial", "taken", "not_taken"]


class ClientTransactionItem(BaseModel):
    """
    Single transaction row as shown in the admin finance view.

    Field aliases map to the legacy Uzbek DB column names so Pydantic can
    populate the schema directly from ORM objects via ``from_attributes=True``.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    flight_name: str = Field(alias="reys")
    row_number: int = Field(alias="qator_raqami")
    amount: float = Field(alias="summa")
    weight: str = Field(alias="vazn")
    payment_type: str
    payment_status: str
    paid_amount: float
    remaining_amount: float
    total_amount: float | None = None
    is_taken_away: bool
    taken_away_date: datetime | None = None
    payment_balance_difference: float
    created_at: datetime


class ClientFinancesResponse(BaseModel):
    """Paginated finance history with running balance summary."""

    wallet_balance: float
    debt: float
    net_balance: float
    total_count: int
    total_pages: int
    page: int
    size: int
    transactions: list[ClientTransactionItem]


# ---------------------------------------------------------------------------
# Per-transaction payment detail (clients:finance_read)
# ---------------------------------------------------------------------------

class PaymentEventItem(BaseModel):
    """Individual payment event (one instalment within a transaction)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    payment_provider: str
    amount: float
    created_at: datetime


class TransactionPaymentDetailResponse(BaseModel):
    """
    Full payment breakdown for a single transaction.

    ``breakdown`` aggregates all events by provider so the frontend can show
    e.g. "150 000 naqd + 50 000 Click" at a glance.
    """

    transaction_id: int
    flight_name: str
    total_amount: float | None
    paid_amount: float
    remaining_amount: float
    payment_events: list[PaymentEventItem]
    breakdown: dict[str, float]


# ---------------------------------------------------------------------------
# Unique flights list (clients:finance_read) — for filter dropdowns
# ---------------------------------------------------------------------------

class ClientFlightsResponse(BaseModel):
    """Distinct flight names for the given client — used by frontend dropdowns."""

    client_id: int
    primary_code: str
    flights: list[str]
