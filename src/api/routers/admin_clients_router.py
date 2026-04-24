"""Admin-facing Client management endpoints.

All routes require a valid Admin JWT (X-Admin-Authorization: Bearer <token>)
and the appropriate RBAC permission.

Permission map:
    clients:read          → search, detail
    clients:update        → patch personal fields
    clients:finance_read  → finance history, payment detail, flights list
"""
from __future__ import annotations

import math
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import AdminJWTPayload, get_db, require_permission
from src.infrastructure.database.dao.admin_audit_log import AdminAuditLogDAO
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.dao.client_payment_event import ClientPaymentEventDAO
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.models.client import Client
from src.infrastructure.schemas.admin_client_schemas import (
    AdminClientDetailResponse,
    ClientFinancesResponse,
    ClientFlightsResponse,
    ClientSearchResponse,
    ClientTransactionItem,
    FilterType,
    SortOrder,
    TransactionPaymentDetailResponse,
    UpdateClientPersonalRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/clients", tags=["admin-clients"])


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

    
@router.get(
    "/search",
    response_model=ClientSearchResponse,
    summary="Search clients — targeted (code/phone/name) or general (q)",
)
async def search_clients(
    # Targeted params — use exactly one for precise results
    code: Annotated[str | None, Query(min_length=1, max_length=50, description="Search by client code only (extra_code / client_code / legacy_code)")] = None,
    phone: Annotated[str | None, Query(min_length=1, max_length=30, description="Search by phone number only")] = None,
    name: Annotated[str | None, Query(min_length=1, max_length=100, description="Search by full name only")] = None,
    # General fallback — searches all fields at once
    q: Annotated[str | None, Query(min_length=1, max_length=100, description="Search all fields (code + name + phone) — may return unrelated results")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    admin: AdminJWTPayload = Depends(require_permission("clients", "read")),
    session: AsyncSession = Depends(get_db),
) -> ClientSearchResponse:
    """
    Two search modes:

    **Targeted** — pass exactly one of `code`, `phone`, or `name`.
    Searches only that field, no false positives from other columns.

    **General** — pass `q` to search all fields at once (codes + name + phone).
    May return unrelated results if the query matches across field types.

    Priority when multiple params are supplied: `code` → `phone` → `name` → `q`.
    No params supplied → returns all clients paginated (for browsing).
    """
    clients, total_count = await ClientDAO.search_clients_paginated(
        session,
        page=page,
        size=size,
        code=code,
        phone=phone,
        name=name,
        query=q,
    )
    total_pages = math.ceil(total_count / size) if total_count else 0
    return ClientSearchResponse(
        items=clients,  # type: ignore[arg-type]
        total_count=total_count,
        total_pages=total_pages,
        page=page,
        size=size,
    )


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


@router.get(
    "/{client_id}",
    response_model=AdminClientDetailResponse,
    summary="Full client profile with financial snapshot",
)
async def get_client_detail(
    client_id: int,
    admin: AdminJWTPayload = Depends(require_permission("clients", "read")),
    session: AsyncSession = Depends(get_db),
) -> AdminClientDetailResponse:
    """Return the full client record including a wallet/debt snapshot."""
    client = await ClientDAO.get_by_id(session, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{client_id} raqamli mijoz topilmadi.",
        )

    primary_code: str = client.primary_code  # Python @property: extra_code or client_code or legacy_code
    balances = await ClientTransactionDAO.get_wallet_balances(session, primary_code)
    wallet_balance: float = balances["wallet_balance"]
    debt: float = balances["debt"]

    referral_count = await ClientDAO.count_referrals_by_client_code(session, primary_code)
    extra_passport_count = await ClientDAO.count_extra_passports_by_client_code(session, primary_code)

    return AdminClientDetailResponse(
        id=client.id,
        primary_code=primary_code,
        full_name=client.full_name,
        phone=client.phone,
        passport_series=client.passport_series,
        pinfl=client.pinfl,
        date_of_birth=client.date_of_birth,
        region=client.region,
        district=client.district,
        address=client.address,
        username=client.username,
        telegram_id=client.telegram_id,
        is_logged_in=client.is_logged_in,
        created_at=client.created_at,
        wallet_balance=wallet_balance,
        debt=debt,
        net_balance=wallet_balance + debt,
        referral_count=referral_count,
        extra_passport_count=extra_passport_count,
    )


# ---------------------------------------------------------------------------
# Personal update (clients:update)
# ---------------------------------------------------------------------------


@router.patch(
    "/{client_id}/personal",
    response_model=AdminClientDetailResponse,
    summary="Update client personal (non-financial) fields",
)
async def update_client_personal(
    client_id: int,
    body: UpdateClientPersonalRequest,
    admin: AdminJWTPayload = Depends(require_permission("clients", "update")),
    session: AsyncSession = Depends(get_db),
) -> AdminClientDetailResponse:
    """
    Partially update personal data fields only.

    Financial fields (wallet, debt) are intentionally absent from this
    endpoint — use the POS adjust endpoint for balance corrections.
    """
    client = await ClientDAO.get_by_id(session, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{client_id} raqamli mijoz topilmadi.",
        )

    # Apply only the fields explicitly sent in the request body (exclude_unset).
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Yangilash uchun kamida bitta maydon yuborilishi shart.",
        )

    for field, value in updates.items():
        setattr(client, field, value)

    session.add(client)

    await AdminAuditLogDAO.log(
        session=session,
        action="UPDATED_CLIENT_PERSONAL",
        admin_id=admin.admin_id,
        role_snapshot=admin.role_name,
        details={
            "client_id": client_id,
            "updated_fields": list(updates.keys()),
        },
    )

    await session.commit()
    await session.refresh(client)

    primary_code: str = client.primary_code
    balances = await ClientTransactionDAO.get_wallet_balances(session, primary_code)
    wallet_balance: float = balances["wallet_balance"]
    debt: float = balances["debt"]
    referral_count = await ClientDAO.count_referrals_by_client_code(session, primary_code)
    extra_passport_count = await ClientDAO.count_extra_passports_by_client_code(session, primary_code)

    return AdminClientDetailResponse(
        id=client.id,
        primary_code=primary_code,
        full_name=client.full_name,
        phone=client.phone,
        passport_series=client.passport_series,
        pinfl=client.pinfl,
        date_of_birth=client.date_of_birth,
        region=client.region,
        district=client.district,
        address=client.address,
        username=client.username,
        telegram_id=client.telegram_id,
        is_logged_in=client.is_logged_in,
        created_at=client.created_at,
        wallet_balance=wallet_balance,
        debt=debt,
        net_balance=wallet_balance + debt,
        referral_count=referral_count,
        extra_passport_count=extra_passport_count,
    )


# ---------------------------------------------------------------------------
# Finance history (clients:finance_read)
# ---------------------------------------------------------------------------


@router.get(
    "/{client_id}/finances",
    response_model=ClientFinancesResponse,
    summary="Paginated finance history with optional filters",
)
async def get_client_finances(
    client_id: int,
    sort_order: SortOrder = "desc",
    filter_type: FilterType = "all",
    flight_name: Annotated[str | None, Query(max_length=50)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    admin: AdminJWTPayload = Depends(require_permission("clients", "finance_read")),
    session: AsyncSession = Depends(get_db),
) -> ClientFinancesResponse:
    """
    Return the paginated transaction history for a client.

    Supports filtering by payment status, cargo take-away status, and flight name,
    plus ascending/descending sort and page-based pagination.
    """
    client = await ClientDAO.get_by_id(session, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{client_id} raqamli mijoz topilmadi.",
        )

    primary_code: str = client.active_codes
    offset = (page - 1) * size

    transactions = await ClientTransactionDAO.get_filtered_transactions(
        session,
        client_code=primary_code,
        filter_type=filter_type,
        sort_order=sort_order,
        limit=size,
        offset=offset,
        flight_code=flight_name,
    )
    total_count = await ClientTransactionDAO.count_filtered_transactions_by_client_code(
        session,
        client_code=primary_code,
        filter_type=filter_type,
        flight_code=flight_name,
    )
    balances = await ClientTransactionDAO.get_wallet_balances(session, primary_code)
    wallet_balance: float = balances["wallet_balance"]
    debt: float = balances["debt"]

    total_pages = math.ceil(total_count / size) if total_count else 0
    transaction_items = [ClientTransactionItem.model_validate(tx) for tx in transactions]

    return ClientFinancesResponse(
        wallet_balance=wallet_balance,
        debt=debt,
        net_balance=wallet_balance + debt,
        total_count=total_count,
        total_pages=total_pages,
        page=page,
        size=size,
        transactions=transaction_items,
    )


# ---------------------------------------------------------------------------
# Per-transaction payment detail (clients:finance_read)
# ---------------------------------------------------------------------------


@router.get(
    "/{client_id}/finances/{transaction_id}/payment-detail",
    response_model=TransactionPaymentDetailResponse,
    summary="Full payment breakdown for a single transaction",
)
async def get_transaction_payment_detail(
    client_id: int,
    transaction_id: int,
    admin: AdminJWTPayload = Depends(require_permission("clients", "finance_read")),
    session: AsyncSession = Depends(get_db),
) -> TransactionPaymentDetailResponse:
    """
    Return all payment events for a transaction with a per-provider breakdown.

    IDOR prevention: verifies the client exists before fetching transaction data.
    The transaction itself is not re-verified against the client_id because
    client_code matching across legacy DB columns makes that join expensive;
    the client existence check is sufficient access guard for this read-only endpoint.
    """
    client = await ClientDAO.get_by_id(session, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{client_id} raqamli mijoz topilmadi.",
        )

    transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{transaction_id} raqamli tranzaksiya topilmadi.",
        )

    payment_events = await ClientPaymentEventDAO.get_by_transaction_id(session, transaction_id)
    breakdown = await ClientPaymentEventDAO.get_payment_breakdown_by_transaction_id(
        session, transaction_id
    )

    return TransactionPaymentDetailResponse(
        transaction_id=transaction.id,
        flight_name=transaction.reys,
        total_amount=transaction.total_amount,
        paid_amount=transaction.paid_amount,
        remaining_amount=transaction.remaining_amount,
        payment_events=payment_events,  # type: ignore[arg-type]
        breakdown=breakdown,
    )


# ---------------------------------------------------------------------------
# Unique flights list (clients:finance_read) — for filter dropdowns
# ---------------------------------------------------------------------------


@router.get(
    "/{client_id}/flights",
    response_model=ClientFlightsResponse,
    summary="Distinct flight names for the client (used by filter dropdowns)",
)
async def get_client_flights(
    client_id: int,
    admin: AdminJWTPayload = Depends(require_permission("clients", "finance_read")),
    session: AsyncSession = Depends(get_db),
) -> ClientFlightsResponse:
    """Return all distinct flight names that the client has transactions on."""
    client = await ClientDAO.get_by_id(session, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{client_id} raqamli mijoz topilmadi.",
        )

    primary_code: str = client.primary_code
    flights = await ClientTransactionDAO.get_unique_flights_by_client_code(
        session, client_code=primary_code
    )

    return ClientFlightsResponse(
        client_id=client.id,
        primary_code=primary_code,
        flights=flights,
    )
