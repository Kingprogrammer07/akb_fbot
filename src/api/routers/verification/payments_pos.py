"""POS (Point of Sale) Fast Cashier — FastAPI router.

Provides four endpoints:
  POST /payments/process-bulk       — atomic multi-cargo payment (cashier)
  GET  /payments/cashier-log        — personal paginated audit log (cashier)
  POST /payments/adjust-balance     — manual balance correction (cashier)
  GET  /payments/all-cashier-logs   — aggregate log, all cashiers (super-admin)

Authentication: Admin JWT via X-Admin-Authorization header.
Authorization:  RBAC permissions:
  • pos:process      — POST /payments/process-bulk
  • pos:read         — GET  /payments/cashier-log
  • pos:adjust       — POST /payments/adjust-balance
  • audit_logs:read  — GET  /payments/all-cashier-logs

All permissions must be explicitly granted to a role by a super-admin
through the Admin Panel (GET /system-permissions lists them; POST
/system-roles or PUT /system-roles/{id}/permissions assigns them).
The super-admin role bypasses all permission checks automatically.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import AdminJWTPayload, get_db, require_permission
from src.api.services.verification.payment_pos_service import (
    POSPaymentError,
    PaymentPOSService,
)
from src.infrastructure.schemas.pos_schemas import (
    AdjustBalanceRequest,
    AdjustBalanceResponse,
    BulkPaymentRequest,
    BulkPaymentResponse,
    CashierLogResponse,
    TransactionStatusUpdateResponse,
    UpdateDeliveryRequestTypeRequest,
    UpdateProofDeliveryMethodRequest,
    UpdateTakenStatusRequest,
)

router = APIRouter(prefix="/payments", tags=["POS Cashier"])


# ---------------------------------------------------------------------------
# POST /payments/process-bulk
# ---------------------------------------------------------------------------


@router.post(
    "/process-bulk",
    response_model=BulkPaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Process bulk payment (POS — atomic)",
    description=(
        "Process 1–50 cargo payments in a single atomic database transaction. "
        "All items succeed or the entire batch is rejected — no partial writes. "
        "Requires `pos:process` permission."
    ),
)
async def process_bulk_payment(
    body: BulkPaymentRequest,
    admin: AdminJWTPayload = Depends(require_permission("pos", "process")),
    session: AsyncSession = Depends(get_db),
) -> BulkPaymentResponse:
    """
    Atomic bulk cargo payment for POS cashiers.

    **Atomicity guarantee**: every item is flushed inside the same SQLAlchemy
    session and committed in a single call at the very end.  If any cargo fails
    pre-validation (not found, already paid, wrong client/flight) the entire
    batch is rejected before a single row is written.

    **Request body**:
    - `items`: 1–50 `BulkPaymentItem` objects.
    - `cashier_note`: optional free-text note (not stored in DB; for UI display).

    **Each item**:
    - `cargo_id`, `flight`, `client_code` — identify the cargo uniquely.
    - `paid_amount` — actual UZS amount handed over at the counter.
    - `payment_type` — `cash`, `card`, `click`, or `payme`.
    - `use_balance` — if `true`, the client's wallet credit is applied first.

    **Side effects** (same as the single-payment endpoint):
    - Creates `ClientTransaction` + `ClientPaymentEvent` per item.
    - Cash/card + fully-paid → `is_taken_away = true`.
    - Writes `admin.admin_id` (Admin DB PK) to `approved_by_admin_id` so the
      cashier log can filter by it.
    """
    try:
        return await PaymentPOSService.process_bulk_payment(
            items=body.items,
            admin=admin,
            session=session,
        )
    except POSPaymentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": exc.message,
                "failed_cargo_id": exc.failed_cargo_id,
            },
        ) from exc


# ---------------------------------------------------------------------------
# GET /payments/cashier-log
# ---------------------------------------------------------------------------


@router.get(
    "/cashier-log",
    response_model=CashierLogResponse,
    summary="Shared cashier log — all POS cashiers visible to pos:read holders",
    description=(
        "Returns a paginated list of payments processed by ALL cashiers, "
        "ordered by most recent first. Each item includes a `cashier_id` field "
        "(Admin DB PK) so the frontend can colour-code entries by cashier. "
        "Designed to prevent duplicate payments: any cashier with `pos:read` "
        "can see what colleagues have already processed before starting a new "
        "transaction. "
        "Requires `pos:read` permission."
    ),
)
async def get_cashier_log(
    page: int = Query(1, ge=1, description="1-based page number"),
    size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    date_from: datetime | None = Query(
        None,
        description="Inclusive lower bound filter on created_at (ISO 8601 UTC)",
    ),
    date_to: datetime | None = Query(
        None,
        description="Inclusive upper bound filter on created_at (ISO 8601 UTC)",
    ),
    admin: AdminJWTPayload = Depends(require_permission("pos", "read")),
    session: AsyncSession = Depends(get_db),
) -> CashierLogResponse:
    """
    Shared cashier log — visible to every POS user with ``pos:read``.

    Returns payment events from ALL cashiers so that any cashier on shift can
    detect duplicate-payment risks before processing a new transaction.  Each
    item carries a non-null ``cashier_id`` (Admin DB PK) so the caller can
    identify who processed each event; the frontend uses this to colour-code
    entries by cashier.

    **Why shared, not personal?**
    Multiple cashiers may work the same shift without direct communication.
    A shared log lets every cashier verify that a cargo has not already been
    paid by a colleague, eliminating same-cargo double-payments.

    **Query parameters**:
    - ``page`` / ``size`` — standard pagination.
    - ``date_from`` / ``date_to`` — optional ISO 8601 UTC datetime bounds.

    **Response**:
    - ``items``: list of ``CashierLogItem``, each with a populated ``cashier_id``.
    - ``today_total``: grand total across all cashiers for today (UTC day).
    """
    return await PaymentPOSService.get_all_cashier_logs(
        page=page,
        size=size,
        session=session,
        cashier_id=None,
        date_from=date_from,
        date_to=date_to,
    )


# ---------------------------------------------------------------------------
# POST /payments/adjust-balance
# ---------------------------------------------------------------------------


@router.post(
    "/adjust-balance",
    response_model=AdjustBalanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Manual cashier balance adjustment (SYS_ADJ)",
    description=(
        "Create a cashier-initiated balance correction for a client. "
        "Positive amounts credit the client (they owe less); negative amounts "
        "debit the client (they owe more). "
        "The adjustment is hidden from user-facing transaction lists but appears "
        "in the cashier audit log. "
        "Requires `pos:adjust` permission."
    ),
)
async def adjust_balance(
    body: AdjustBalanceRequest,
    admin: AdminJWTPayload = Depends(require_permission("pos", "adjust")),
    session: AsyncSession = Depends(get_db),
) -> AdjustBalanceResponse:
    """
    Manual cashier balance correction.

    Creates a ``SYS_ADJ:{reason}`` pseudo-transaction on the client's record
    and a corresponding ``ClientPaymentEvent`` so the adjustment appears in
    ``GET /payments/cashier-log``.

    **Payload**:
    - ``client_code`` — the client to adjust (case-insensitive, normalised to upper).
    - ``amount`` — signed UZS amount; non-zero.
      Positive = credit (reduce what they owe / issue a refund).
      Negative = debit (increase what they owe / claw back an overpayment).
    - ``reason`` — short slug (1–64 chars); colons and spaces are replaced with
      underscores automatically.

    **Response**:
    - ``transaction_id`` — ID of the created SYS_ADJ transaction.
    - ``new_wallet_balance`` — client's net position (credit − debt) after the
      adjustment.  Positive = client has a net credit; negative = net debt.
    """
    try:
        return await PaymentPOSService.adjust_balance(
            body=body,
            admin=admin,
            session=session,
        )
    except POSPaymentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": exc.message},
        ) from exc


def _raise_pos_status_error(exc: POSPaymentError) -> None:
    """Translate service-layer POS status edit errors into HTTP responses."""
    if exc.error_code in {"TRANSACTION_NOT_FOUND", "DELIVERY_REQUEST_NOT_FOUND", "DELIVERY_PROOF_NOT_FOUND"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": exc.message},
        ) from exc
    if exc.error_code in {"AMBIGUOUS_DELIVERY_REQUEST", "NO_STATUS_CHANGE"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": exc.message},
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"error": exc.message},
    ) from exc


@router.patch(
    "/transactions/{transaction_id}/taken-status",
    response_model=TransactionStatusUpdateResponse,
    summary="Update POS taken-away status for a single transaction",
    description=(
        "Toggle `is_taken_away` for a single transaction from the POS screen. "
        "Requires `pos:update_status` permission and a mandatory reason."
    ),
)
async def update_taken_status(
    transaction_id: int = Path(..., gt=0),
    body: UpdateTakenStatusRequest = ...,
    admin: AdminJWTPayload = Depends(require_permission("pos", "update_status")),
    session: AsyncSession = Depends(get_db),
) -> TransactionStatusUpdateResponse:
    try:
        return await PaymentPOSService.update_taken_status(
            transaction_id=transaction_id,
            body=body,
            admin=admin,
            session=session,
        )
    except POSPaymentError as exc:
        _raise_pos_status_error(exc)


@router.patch(
    "/transactions/{transaction_id}/delivery-request-type",
    response_model=TransactionStatusUpdateResponse,
    summary="Update POS delivery-request type for a single transaction",
    description=(
        "Update the single-flight `delivery_request.delivery_type` visible from the POS screen. "
        "Requires `pos:update_status` permission and a mandatory reason."
    ),
)
async def update_delivery_request_type(
    transaction_id: int = Path(..., gt=0),
    body: UpdateDeliveryRequestTypeRequest = ...,
    admin: AdminJWTPayload = Depends(require_permission("pos", "update_status")),
    session: AsyncSession = Depends(get_db),
) -> TransactionStatusUpdateResponse:
    try:
        return await PaymentPOSService.update_delivery_request_type(
            transaction_id=transaction_id,
            body=body,
            admin=admin,
            session=session,
        )
    except POSPaymentError as exc:
        _raise_pos_status_error(exc)


@router.patch(
    "/transactions/{transaction_id}/proof-delivery-method",
    response_model=TransactionStatusUpdateResponse,
    summary="Update POS proof delivery method for a single transaction",
    description=(
        "Update the latest `cargo_delivery_proofs.delivery_method` visible from the POS screen. "
        "Requires `pos:update_status` permission and a mandatory reason."
    ),
)
async def update_proof_delivery_method(
    transaction_id: int = Path(..., gt=0),
    body: UpdateProofDeliveryMethodRequest = ...,
    admin: AdminJWTPayload = Depends(require_permission("pos", "update_status")),
    session: AsyncSession = Depends(get_db),
) -> TransactionStatusUpdateResponse:
    try:
        return await PaymentPOSService.update_proof_delivery_method(
            transaction_id=transaction_id,
            body=body,
            admin=admin,
            session=session,
        )
    except POSPaymentError as exc:
        _raise_pos_status_error(exc)


# ---------------------------------------------------------------------------
# GET /payments/all-cashier-logs
# ---------------------------------------------------------------------------


@router.get(
    "/all-cashier-logs",
    response_model=CashierLogResponse,
    summary="All cashier logs — super-admin aggregate view",
    description=(
        "Returns payment events from ALL cashiers, ordered by most recent first. "
        "An optional `cashier_id` query parameter narrows the view to one specific "
        "cashier — useful for targeted investigation. "
        "Each item includes a `cashier_id` field identifying who processed it. "
        "Requires `audit_logs:read` permission."
    ),
)
async def get_all_cashier_logs(
    page: int = Query(1, ge=1, description="1-based page number"),
    size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    cashier_id: int | None = Query(
        None,
        description="Filter to a specific cashier's Admin DB PK (omit for all cashiers)",
    ),
    date_from: datetime | None = Query(
        None,
        description="Inclusive lower bound filter on created_at (ISO 8601 UTC)",
    ),
    date_to: datetime | None = Query(
        None,
        description="Inclusive upper bound filter on created_at (ISO 8601 UTC)",
    ),
    admin: AdminJWTPayload = Depends(require_permission("audit_logs", "read")),
    session: AsyncSession = Depends(get_db),
) -> CashierLogResponse:
    """
    Super-admin aggregate cashier log.

    Returns payment events created by ALL cashiers (i.e. all rows where
    ``approved_by_admin_id IS NOT NULL``).  The personal endpoint
    ``GET /payments/cashier-log`` remains unchanged — it always returns
    only the caller's own events.

    **Query parameters**:
    - ``cashier_id`` — optional filter to one cashier's Admin DB PK.
    - ``page`` / ``size`` — standard pagination.
    - ``date_from`` / ``date_to`` — optional ISO 8601 UTC datetime bounds.

    **Response**:
    - Same ``CashierLogResponse`` shape as the personal log.
    - Each ``CashierLogItem.cashier_id`` is populated so the caller can
      distinguish events from different cashiers.
    - ``today_total`` reflects today's grand total across all cashiers (or
      the specified cashier when ``cashier_id`` is given).
    """
    return await PaymentPOSService.get_all_cashier_logs(
        page=page,
        size=size,
        session=session,
        cashier_id=cashier_id,
        date_from=date_from,
        date_to=date_to,
    )
