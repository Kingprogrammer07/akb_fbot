"""Warehouse (ombor) API endpoints.

Designed for warehouse workers who need to:
  1. Browse cargo transactions per flight.
  2. Search clients within a flight to locate their cargo.
  3. Mark cargo as taken-away, uploading photographic proof and selecting a
     delivery method.  After a successful mark the system:
       a) Persists photos to S3 under the ``warehouse/`` folder.
       b) Saves a ``CargoDeliveryProof`` record.
       c) Sets ``ClientTransaction.is_taken_away = True``.
       d) Sends a Telegram notification with all details + photos to the
          configured warehouse proof group.

Permission map:
    warehouse:read       → flight transaction list + client search
    warehouse:mark_taken → mark cargo as taken-away (requires proof photos)
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import datetime
from html import escape
from typing import Annotated

from aiogram.types import InputMediaPhoto
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import AdminJWTPayload, get_db, require_permission
from src.bot.bot_instance import bot
from src.config import config
from src.infrastructure.database.dao.admin_account import AdminAccountDAO
from src.infrastructure.database.dao.admin_audit_log import AdminAuditLogDAO
from src.infrastructure.database.dao.cargo_delivery_proof import CargoDeliveryProofDAO
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.tools.image_optimizer import optimize_image_to_webp
from src.infrastructure.tools.s3_manager import s3_manager
from src.infrastructure.tools.datetime_utils import get_current_time, to_tashkent
from src.infrastructure.schemas.warehouse_schemas import (
    BulkMarkTakenAwayResponse,
    ClientGroup,
    DeliveryMethod,
    DELIVERY_METHOD_LABELS,
    DeliveryProofResponse,
    FlightGroup,
    GroupedTransactionItem,
    MarkTakenAwayResponse,
    PaymentStatusFilter,
    TakenStatusFilter,
    WarehouseActivityItem,
    WarehouseActivityResponse,
    WarehouseFlightOption,
    WarehouseFlightsResponse,
    WarehouseFlightTransactionsResponse,
    WarehouseGroupedSearchResponse,
    WarehouseTransactionItem,
    WarehouseTransactionsSearchResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/warehouse", tags=["warehouse"])

_MAX_PHOTOS = 10  # hard cap per take-away event
_MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB per file

_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "image/heic",
    }
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _upload_proof_photo(
    raw_bytes: bytes,
    original_filename: str,
    transaction_id: int,
    idx: int,
) -> str:
    """Upload one proof photo to S3 and return its key.

    Optimises to WebP first; falls back to original bytes on conversion error.
    """
    try:
        upload_bytes = await optimize_image_to_webp(raw_bytes)
        ext = "webp"
    except Exception:
        upload_bytes = raw_bytes
        ext = (
            original_filename.rsplit(".", 1)[-1] if "." in original_filename else "jpg"
        )

    unique_name = f"proof_{uuid.uuid4().hex[:8]}_{idx + 1}.{ext}"
    s3_key = await s3_manager.upload_file(
        file_content=upload_bytes,
        file_name=unique_name,
        telegram_id=0,
        client_code=str(transaction_id),
        base_folder="warehouse",
        sub_folder=str(transaction_id),
        content_type="image/webp" if ext == "webp" else "image/jpeg",
    )
    return s3_key


def _format_business_datetime(dt: datetime | None = None) -> str:
    """Render a UTC timestamp in business timezone for Telegram captions."""
    return to_tashkent(dt or get_current_time()).strftime("%d.%m.%Y %H:%M")


def _escape_html(value: str | None) -> str:
    """Escape untrusted values before injecting them into HTML captions."""
    return escape(value or "", quote=False)


def _build_warehouse_admin_label(
    system_username: str | None,
    admin_id: int,
    fallback_role_name: str,
) -> str:
    """Format the warehouse worker label shown in Telegram notifications."""
    display_name = (system_username or "").strip() or fallback_role_name
    return f"{display_name} (ID: {admin_id})"


async def _resolve_warehouse_admin_label(
    session: AsyncSession,
    admin: AdminJWTPayload,
) -> str:
    """Load the admin panel username for Telegram notifications."""
    admin_account = await AdminAccountDAO.get_by_id_with_relations(
        session, admin.admin_id
    )
    return _build_warehouse_admin_label(
        system_username=admin_account.system_username if admin_account else None,
        admin_id=admin.admin_id,
        fallback_role_name=admin.role_name,
    )


def _build_payment_status_label(payment_status: str, remaining_amount: float) -> str:
    """Return a human-friendly payment status label for warehouse notifications."""
    payment_status_labels: dict[str, str] = {
        "paid": "✅ To'liq to'langan",
        "partial": f"⚠️ Qisman to'langan ({remaining_amount:,.0f} so'm qoldi)",
        "pending": f"❌ To'lanmagan ({remaining_amount:,.0f} so'm qoldi)",
    }
    if payment_status in payment_status_labels:
        return payment_status_labels[payment_status]
    return f"ℹ️ To'lov holati: {_escape_html(payment_status)}"


def _build_single_taken_away_caption(
    *,
    client_code: str,
    client_full_name: str | None,
    flight_name: str,
    remaining_amount: float,
    payment_status: str,
    delivery_method: str,
    admin_label: str,
    comment: str | None,
    event_time: datetime | None,
) -> str:
    """Build the rich Telegram caption for a single take-away event."""
    caption_lines = [
        "📦 <b>Yuk olib ketildi</b>",
        "",
        (
            f"👤 Mijoz: <b>{_escape_html(client_full_name or client_code)}</b> "
            f"(<code>{_escape_html(client_code)}</code>)"
        ),
        f"✈️ Reys: <b>{_escape_html(flight_name)}</b>",
        f"💰 To'lov: {_build_payment_status_label(payment_status, remaining_amount)}",
        (
            "🚚 Yetkazib berish: "
            f"<b>{_escape_html(DELIVERY_METHOD_LABELS.get(delivery_method, delivery_method))}</b>"
        ),
        f"👷 Ombor xodimi: <b>{_escape_html(admin_label)}</b>",
        f"🕒 Sana: <b>{_format_business_datetime(event_time)}</b>",
    ]
    if comment and comment.strip():
        caption_lines.extend(["", f"💬 Izoh: {_escape_html(comment.strip())}"])
    return "\n".join(caption_lines)


def _build_bulk_taken_away_caption(
    *,
    transaction_count: int,
    client_code: str,
    delivery_method: str,
    admin_label: str,
    flight_counts: dict[str, int],
    comment: str | None,
    event_time: datetime | None,
) -> str:
    """Build the rich Telegram caption for a bulk take-away event."""
    flight_lines = [
        f"• <b>{_escape_html(flight_name)}</b>: {count} ta yuk"
        for flight_name, count in flight_counts.items()
    ]
    if not flight_lines:
        flight_lines = ["• <i>Reys ma'lum emas</i>"]

    caption_lines = [
        "✅ <b>Yangi ommaviy yuk topshirish (Omborxona)</b>",
        "",
        f"📦 Tranzaksiyalar: <b>{transaction_count} ta</b>",
        f"👤 Mijoz: <code>{_escape_html(client_code)}</code>",
        "✈️ Reyslar:",
        *flight_lines,
        (
            "🚚 Yetkazib berish: "
            f"<b>{_escape_html(DELIVERY_METHOD_LABELS.get(delivery_method, delivery_method))}</b>"
        ),
        f"👷 Ombor xodimi: <b>{_escape_html(admin_label)}</b>",
        f"🕒 Sana: <b>{_format_business_datetime(event_time)}</b>",
    ]
    if comment and comment.strip():
        caption_lines.extend(["", f"💬 Izoh: {_escape_html(comment.strip())}"])
    return "\n".join(caption_lines)


async def _resolve_warehouse_photo_urls(s3_keys: list[str]) -> list[str]:
    """Convert proof S3 keys to presigned URLs for Telegram delivery."""
    presigned_urls: list[str] = []
    for key in s3_keys:
        try:
            url = await s3_manager.generate_presigned_url(key)
        except Exception as exc:
            logger.warning("Failed to generate presigned URL for warehouse proof %r: %s", key, exc)
            continue
        if url:
            presigned_urls.append(url)
    return presigned_urls


async def _send_warehouse_notification_message(
    *,
    caption: str,
    s3_keys: list[str],
    log_context: str,
) -> bool:
    """Send a warehouse notification as text, photo, or media group."""
    group_id = config.telegram.WAREHOUSE_TAKEN_AWAY_PROVE_GROUP_ID
    if not group_id:
        logger.warning("Warehouse proof notification skipped for %s: group id not configured", log_context)
        return False

    try:
        presigned_urls = await _resolve_warehouse_photo_urls(s3_keys)
        if not presigned_urls:
            await bot.send_message(
                chat_id=group_id,
                text=caption,
                parse_mode="HTML",
            )
            return True

        if len(presigned_urls) == 1:
            await bot.send_photo(
                chat_id=group_id,
                photo=presigned_urls[0],
                caption=caption,
                parse_mode="HTML",
            )
            return True

        media = [
            InputMediaPhoto(
                media=presigned_urls[0],
                caption=caption,
                parse_mode="HTML",
            ),
            *[InputMediaPhoto(media=url) for url in presigned_urls[1:]],
        ]
        await bot.send_media_group(chat_id=group_id, media=media)
        return True
    except Exception as exc:
        logger.error(
            "Warehouse Telegram notification failed for %s: %s",
            log_context,
            exc,
        )
        return False


async def _send_taken_away_notification(
    transaction_id: int,
    client_code: str,
    client_full_name: str | None,
    flight_name: str,
    remaining_amount: float,
    payment_status: str,
    delivery_method: str,
    admin_label: str,
    s3_keys: list[str],
    event_time: datetime | None = None,
    comment: str | None = None,
) -> bool:
    """Send a rich Telegram notification for a single take-away event."""
    caption = _build_single_taken_away_caption(
        client_code=client_code,
        client_full_name=client_full_name,
        flight_name=flight_name,
        remaining_amount=remaining_amount,
        payment_status=payment_status,
        delivery_method=delivery_method,
        admin_label=admin_label,
        comment=comment,
        event_time=event_time,
    )
    return await _send_warehouse_notification_message(
        caption=caption,
        s3_keys=s3_keys,
        log_context=f"tx={transaction_id}",
    )


async def _send_bulk_taken_away_notification(
    *,
    transaction_ids: list[int],
    client_code: str,
    delivery_method: str,
    admin_label: str,
    s3_keys: list[str],
    flight_counts: dict[str, int],
    event_time: datetime | None = None,
    comment: str | None = None,
) -> bool:
    """Send a rich Telegram notification for a bulk take-away event."""
    caption = _build_bulk_taken_away_caption(
        transaction_count=len(transaction_ids),
        client_code=client_code,
        delivery_method=delivery_method,
        admin_label=admin_label,
        flight_counts=flight_counts,
        comment=comment,
        event_time=event_time,
    )
    return await _send_warehouse_notification_message(
        caption=caption,
        s3_keys=s3_keys,
        log_context=f"bulk txs={transaction_ids}",
    )


# ---------------------------------------------------------------------------
# Recent flights dropdown
# ---------------------------------------------------------------------------


@router.get(
    "/flights",
    response_model=WarehouseFlightsResponse,
    summary="So'nggi 10 ta reys (dropdown uchun, statistika bilan)",
)
async def get_recent_flights(
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    admin: AdminJWTPayload = Depends(require_permission("warehouse", "read")),
    session: AsyncSession = Depends(get_db),
) -> WarehouseFlightsResponse:
    """
    Return the most recently active flights for the warehouse flight-picker dropdown.

    Each item includes the flight name, total transaction count, and the number
    of unique clients — making it easy for the frontend to show a meaningful
    label (e.g. ``CH123 — 34 yuk / 18 mijoz``).
    """
    rows = await ClientTransactionDAO.get_recent_flights_with_stats(
        session, limit=limit
    )
    return WarehouseFlightsResponse(
        items=[WarehouseFlightOption(**row) for row in rows],
    )


# ---------------------------------------------------------------------------
# Own activity log — reads from cargo_delivery_proofs, NOT admin_audit_logs
# ---------------------------------------------------------------------------


@router.get(
    "/my-activity",
    response_model=WarehouseActivityResponse,
    summary="O'zimning so'nggi faoliyatim (olib ketildi belgilashlari + rasmlar)",
)
async def get_my_activity(
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    admin: AdminJWTPayload = Depends(require_permission("warehouse", "read")),
    session: AsyncSession = Depends(get_db),
) -> WarehouseActivityResponse:
    """
    Return this warehouse worker's own take-away history from ``cargo_delivery_proofs``.

    Each entry shows the cargo/client/flight context plus presigned photo URLs
    so the frontend can render the proof images inline.

    This endpoint reads from ``cargo_delivery_proofs``, **not** ``admin_audit_logs``
    (which is an internal super-admin-only trail).  A warehouse worker never has
    access to other workers' records — only their own ``marked_by_admin_id`` rows.
    """
    offset = (page - 1) * size
    proofs = await CargoDeliveryProofDAO.get_by_admin_id_paginated(
        session,
        admin_id=admin.admin_id,
        limit=size,
        offset=offset,
    )
    total_count = await CargoDeliveryProofDAO.count_by_admin_id(
        session, admin_id=admin.admin_id
    )
    total_pages = math.ceil(total_count / size) if total_count else 0

    items: list[WarehouseActivityItem] = []
    for proof in proofs:
        tx = proof.transaction  # eagerly loaded by the DAO via selectinload

        # Generate presigned URLs so the frontend can display proof photos inline.
        photo_urls: list[str] = []
        for s3_key in proof.photo_s3_keys or []:
            try:
                url = await s3_manager.generate_presigned_url(s3_key)
                photo_urls.append(url)
            except Exception:
                logger.warning("Failed to generate presigned URL for key %r", s3_key)

        items.append(
            WarehouseActivityItem(
                proof_id=proof.id,
                transaction_id=proof.transaction_id,
                client_code=tx.client_code if tx else None,
                flight_name=tx.reys if tx else None,
                total_amount=float(tx.total_amount)
                if tx and tx.total_amount is not None
                else None,
                paid_amount=float(tx.paid_amount) if tx else None,
                remaining_amount=float(tx.remaining_amount) if tx else None,
                payment_status=tx.payment_status if tx else None,
                delivery_method=proof.delivery_method,
                delivery_method_label=DELIVERY_METHOD_LABELS.get(
                    proof.delivery_method, proof.delivery_method
                ),
                photo_urls=photo_urls,
                photo_count=len(photo_urls),
                created_at=proof.created_at,
            )
        )

    return WarehouseActivityResponse(
        items=items,
        total_count=total_count,
        total_pages=total_pages,
        page=page,
        size=size,
    )


# ---------------------------------------------------------------------------
# Client search (same as admin search, re-exposed under warehouse prefix)
# ---------------------------------------------------------------------------


@router.get(
    "/clients/search",
    response_model_include=None,
    summary="Mijozlarni qidirish (kod, telefon yoki ism bo'yicha)",
)
async def search_clients(
    code: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    phone: Annotated[str | None, Query(min_length=1, max_length=30)] = None,
    name: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=50)] = 20,
    admin: AdminJWTPayload = Depends(require_permission("warehouse", "read")),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Minimal client search for warehouse workers — returns id, primary_code, full_name, phone."""
    clients, total_count = await ClientDAO.search_clients_paginated(
        session, page=page, size=size, code=code, phone=phone, name=name, query=q
    )
    return {
        "items": [
            {
                "id": c.id,
                "primary_code": c.primary_code,
                "full_name": c.full_name,
                "phone": c.phone,
            }
            for c in clients
        ],
        "total_count": total_count,
        "total_pages": math.ceil(total_count / size) if total_count else 0,
        "page": page,
        "size": size,
    }


# ---------------------------------------------------------------------------
# Transaction search across all flights (no flight required)
# ---------------------------------------------------------------------------


@router.get(
    "/transactions/search",
    response_model=WarehouseTransactionsSearchResponse,
    summary="Tranzaksiyalarni qidirish (reys tanlanmasa ham ishlaydi)",
)
async def search_transactions(
    code: Annotated[str | None, Query(max_length=50)] = None,
    phone: Annotated[str | None, Query(max_length=30)] = None,
    name: Annotated[str | None, Query(max_length=100)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    flight: Annotated[str | None, Query(max_length=50)] = None,
    payment_status: PaymentStatusFilter = "all",
    taken_status: TakenStatusFilter = "all",
    sort_order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 50,
    admin: AdminJWTPayload = Depends(require_permission("warehouse", "read")),
    session: AsyncSession = Depends(get_db),
) -> WarehouseTransactionsSearchResponse:
    """
    Mijoz kodi, telefon yoki ism bo'yicha tranzaksiyalarni qidirish.

    - ``flight`` parametri ixtiyoriy — berilmasa barcha reyslar bo'yicha qidiradi.
    - Kamida bitta qidiruv parametri (``code``, ``phone``, ``name`` yoki ``q``) talab qilinadi.
    - Natijalar ``payment_status`` / ``taken_status`` filtrlari bilan toraytiriladi.
    """
    # Normalize empty/whitespace query params (e.g. phone="") to None.
    code = code.strip() if code and code.strip() else None
    phone = phone.strip() if phone and phone.strip() else None
    name = name.strip() if name and name.strip() else None
    q = q.strip() if q and q.strip() else None
    flight = flight.strip() if flight and flight.strip() else None

    if not any([code, phone, name, q]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Kamida bitta qidiruv parametri kerak: code, phone, name yoki q.",
        )

    # Translate the partner-mask flight name (if used) to its real value
    # before building the DAO filter — cashiers may type either form.
    if flight and code:
        from src.infrastructure.services.flight_mask import FlightMaskService
        from src.infrastructure.services.partner_resolver import (
            PartnerNotFoundError,
            get_resolver,
        )
        try:
            _partner = await get_resolver().resolve_by_client_code(session, code)
            flight = await FlightMaskService.normalize_flight_input(
                session, _partner.id, flight
            )
        except PartnerNotFoundError:
            pass

    # Build combined filter_type
    if taken_status == "taken":
        dao_filter_type = "taken"
    elif taken_status == "not_taken":
        dao_filter_type = "not_taken"
    else:
        dao_filter_type = payment_status  # all | paid | unpaid | partial

    # Find matching clients
    matched_clients, _ = await ClientDAO.search_clients_paginated(
        session, page=1, size=200, code=code, phone=phone, name=name, query=q
    )
    if not matched_clients:
        return WarehouseTransactionsSearchResponse(
            items=[], total_count=0, total_pages=0, page=page, size=size
        )

    # Collect all code variants (extra_code, client_code, legacy_code)
    code_variants: list[str] = []
    for c in matched_clients:
        for attr in ("extra_code", "client_code", "legacy_code"):
            val = getattr(c, attr, None)
            if val:
                code_variants.append(val)
    client_code_filter = list(set(code_variants))

    offset = (page - 1) * size

    db_transactions = await ClientTransactionDAO.get_filtered_transactions(
        session,
        client_code=client_code_filter,
        filter_type=dao_filter_type,
        sort_order=sort_order,
        limit=size,
        offset=offset,
        flight_code=flight,
    )
    total_count = await ClientTransactionDAO.count_filtered_transactions_by_client_code(
        session,
        client_code=client_code_filter,
        filter_type=dao_filter_type,
        flight_code=flight,
    )

    # Build client lookup map for name/phone enrichment
    unique_codes = {tx.client_code for tx in db_transactions if tx.client_code}
    client_map: dict[str, tuple[str | None, str | None]] = {}
    for tx_code in unique_codes:
        client_obj = await ClientDAO.get_by_client_code(session, tx_code)
        if client_obj:
            client_map[tx_code.upper()] = (client_obj.full_name, client_obj.phone)

    # Single batch query to know which transactions already have proof.
    search_tx_ids = [tx.id for tx in db_transactions]
    proven_ids = await CargoDeliveryProofDAO.get_proven_transaction_ids(session, search_tx_ids)

    items: list[WarehouseTransactionItem] = []
    for tx in db_transactions:
        full_name, phone_val = client_map.get(
            (tx.client_code or "").upper(), (None, None)
        )
        item = WarehouseTransactionItem.model_validate(tx)
        item.client_full_name = full_name
        item.client_phone = phone_val
        item.has_proof = tx.id in proven_ids
        items.append(item)

    total_pages = math.ceil(total_count / size) if total_count else 0

    return WarehouseTransactionsSearchResponse(
        items=items,
        total_count=total_count,
        total_pages=total_pages,
        page=page,
        size=size,
    )


# ---------------------------------------------------------------------------
# Flight transaction list
# ---------------------------------------------------------------------------


@router.get(
    "/flight/{flight_name}/transactions",
    response_model=WarehouseFlightTransactionsResponse,
    summary="Reys bo'yicha barcha tranzaksiyalar ro'yxati",
)
async def list_flight_transactions(
    flight_name: str,
    payment_status: PaymentStatusFilter = "all",
    taken_status: TakenStatusFilter = "all",
    # Additional client-level filters within the flight
    code: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    phone: Annotated[str | None, Query(min_length=1, max_length=30)] = None,
    name: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort_order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 50,
    admin: AdminJWTPayload = Depends(require_permission("warehouse", "read")),
    session: AsyncSession = Depends(get_db),
) -> WarehouseFlightTransactionsResponse:
    """
    Return all cargo transactions for a given flight, with optional filters.

    If ``code``, ``phone``, or ``name`` is supplied, the result is narrowed to
    client(s) matching that filter who also have a transaction in this flight.

    ``payment_status`` / ``taken_status`` filters are applied server-side and
    map to the existing ``get_filtered_transactions`` DAO logic.
    """
    # Build combined filter_type for the DAO.
    # The DAO supports: all | paid | unpaid | partial | taken | not_taken
    # taken_status takes precedence when both are non-"all" (rare in practice).
    if taken_status == "taken":
        dao_filter_type = "taken"
    elif taken_status == "not_taken":
        dao_filter_type = "not_taken"
    else:
        dao_filter_type = payment_status  # all | paid | unpaid | partial

    # Resolve client code filter when the worker searches by phone or name.
    client_code_filter: str | list[str] | None = None
    if code or phone or name:
        matched_clients, _ = await ClientDAO.search_clients_paginated(
            session, page=1, size=200, code=code, phone=phone, name=name
        )
        if not matched_clients:
            return WarehouseFlightTransactionsResponse(
                flight_name=flight_name,
                items=[],
                total_count=0,
                total_pages=0,
                page=page,
                size=size,
            )
        # Collect all code variants so legacy codes are matched too.
        code_variants: list[str] = []
        for c in matched_clients:
            for attr in ("extra_code", "client_code", "legacy_code"):
                val = getattr(c, attr, None)
                if val:
                    code_variants.append(val)
        client_code_filter = list(set(code_variants)) if code_variants else None

    offset = (page - 1) * size

    # Fetch from ClientTransactionDAO (Paid, Partial, explicitly pending)
    if client_code_filter is not None:
        db_transactions = await ClientTransactionDAO.get_filtered_transactions(
            session,
            client_code=client_code_filter,
            filter_type=dao_filter_type,
            sort_order=sort_order,
            limit=size,
            offset=offset,
            flight_code=flight_name,
        )
        db_total_count = (
            await ClientTransactionDAO.count_filtered_transactions_by_client_code(
                session,
                client_code=client_code_filter,
                filter_type=dao_filter_type,
                flight_code=flight_name,
            )
        )
    else:
        db_transactions = (
            await ClientTransactionDAO.get_transactions_by_flight_filtered(
                session,
                flight_name=flight_name,
                filter_type=dao_filter_type,
                sort_order=sort_order,
                limit=size,
                offset=offset,
            )
        )
        db_total_count = (
            await ClientTransactionDAO.count_transactions_by_flight_filtered(
                session,
                flight_name=flight_name,
                filter_type=dao_filter_type,
            )
        )

    # Fetch unpaid/unrecorded items from FlightCargo
    # We only inject these if filter allows unpaid/not_taken
    synthetic_items: list[WarehouseTransactionItem] = []
    synthetic_count = 0
    if dao_filter_type in ("all", "unpaid", "not_taken"):
        from src.infrastructure.database.models.flight_cargo import FlightCargo
        from src.infrastructure.database.models.client_transaction import (
            ClientTransaction,
        )
        from src.api.services.verification.utils import get_usd_rate, get_extra_charge
        from sqlalchemy import select, and_, exists, func

        # Subquery to find cargos that already have a transaction
        has_transaction = (
            select(ClientTransaction.id)
            .where(
                and_(
                    func.upper(ClientTransaction.reys)
                    == func.upper(FlightCargo.flight_name),
                    func.upper(ClientTransaction.client_code)
                    == func.upper(FlightCargo.client_id),
                )
            )
            .exists()
        )

        stmt = select(FlightCargo).where(
            func.upper(FlightCargo.flight_name) == flight_name.upper(),
            FlightCargo.is_sent == True,
            ~has_transaction,
        )

        if client_code_filter is not None:
            if isinstance(client_code_filter, list):
                upper_codes = [c.upper() for c in client_code_filter]
                stmt = stmt.where(func.upper(FlightCargo.client_id).in_(upper_codes))
            else:
                stmt = stmt.where(
                    func.upper(FlightCargo.client_id) == client_code_filter.upper()
                )

        # Count synthetic items
        count_stmt = select(func.count(FlightCargo.id)).select_from(stmt.subquery())
        synthetic_count = (await session.execute(count_stmt)).scalar_one()

        # Fetch page of synthetic items if we need to
        # Since pagination is tricky with two tables, we'll try to fetch what's needed.
        # For simplicity, if we fetch db_transactions and we still have room in `size`, we fetch synthetic.
        # But proper pagination requires union. Let's just fetch all synthetic for now and append,
        # or do a UNION in python. This API is only for one flight, usually < 500 cargos.

        if synthetic_count > 0:
            stmt = stmt.order_by(FlightCargo.created_at.desc())
            # Simple pagination logic:
            synthetic_offset = max(0, offset - db_total_count)
            synthetic_limit = max(0, size - len(db_transactions))

            if synthetic_limit > 0:
                stmt = stmt.offset(synthetic_offset).limit(synthetic_limit)
                raw_cargos = (await session.execute(stmt)).scalars().all()

                usd_rate = await get_usd_rate(session)
                extra_charge = await get_extra_charge(session)

                for cargo in raw_cargos:
                    weight = float(cargo.weight_kg) if cargo.weight_kg else 0.0
                    price_per_kg = (
                        float(cargo.price_per_kg) if cargo.price_per_kg else 0.0
                    )
                    if weight > 0 and price_per_kg > 0:
                        total_amt = weight * price_per_kg * usd_rate + extra_charge
                    else:
                        total_amt = 0.0

                    synthetic_items.append(
                        WarehouseTransactionItem(
                            id=-cargo.id,  # Negative ID to indicate it's from FlightCargo
                            client_code=cargo.client_id,
                            reys=cargo.flight_name,
                            qator_raqami=cargo.id,
                            vazn=str(weight),
                            total_amount=total_amt,
                            paid_amount=0.0,
                            remaining_amount=total_amt,
                            payment_status="pending",
                            is_taken_away=False,
                            taken_away_date=None,
                            created_at=cargo.created_at,
                        )
                    )

    total_count = db_total_count + synthetic_count

    total_pages = math.ceil(total_count / size) if total_count else 0

    # Build client lookup map for name/phone enrichment.
    unique_codes = {tx.client_code for tx in db_transactions if tx.client_code}
    client_map: dict[str, tuple[str | None, str | None]] = {}
    for tx_code in unique_codes:
        client_obj = await ClientDAO.get_by_client_code(session, tx_code)
        if client_obj:
            client_map[tx_code.upper()] = (client_obj.full_name, client_obj.phone)

    # Single batch query to know which transactions already have proof.
    real_tx_ids = [tx.id for tx in db_transactions]
    proven_ids = await CargoDeliveryProofDAO.get_proven_transaction_ids(session, real_tx_ids)

    items: list[WarehouseTransactionItem] = []
    for tx in db_transactions:
        full_name, phone_val = client_map.get(
            (tx.client_code or "").upper(), (None, None)
        )
        item = WarehouseTransactionItem.model_validate(tx)
        item.client_full_name = full_name
        item.client_phone = phone_val
        item.has_proof = tx.id in proven_ids
        items.append(item)

    items.extend(synthetic_items)

    # Sort items if synthetic ones were appended
    # For now they are appended after db items, which might break sorting but allows pagination to work simply

    return WarehouseFlightTransactionsResponse(
        flight_name=flight_name,
        items=items,
        total_count=total_count,
        total_pages=total_pages,
        page=page,
        size=size,
    )


# ---------------------------------------------------------------------------
# Mark as taken-away
# ---------------------------------------------------------------------------


@router.post(
    "/transactions/bulk-mark-taken",
    response_model=BulkMarkTakenAwayResponse,
    status_code=status.HTTP_200_OK,
    summary="Bir nechta yukni olib ketildi deb belgilash (1 marta rasm yuklash bilan)",
)
async def bulk_mark_cargo_taken(
    transaction_ids: str = Form(
        ..., description="Tranzaksiya ID lari vergul bilan ajratilgan (masalan: 101,102,105) yoki JSON ro'yxat"
    ),
    delivery_method: DeliveryMethod = Form(
        ..., description="Yetkazib berish usuli: uzpost | bts | akb | yandex"
    ),
    photos: list[UploadFile] = File(
        ..., description="Isbotlovchi rasmlar (1 dan 10 tagacha)"
    ),
    comment: Annotated[str | None, Form(description="Omborxonachi izohi (ixtiyoriy)")] = None,
    admin: AdminJWTPayload = Depends(require_permission("warehouse", "mark_taken")),
    session: AsyncSession = Depends(get_db),
) -> BulkMarkTakenAwayResponse:
    """
    Mark multiple cargo transactions as taken-away at once.

    1. Parse transaction IDs.
    2. Upload photos ONLY ONCE to S3.
    3. For each transaction, create a CargoDeliveryProof linking to the same S3 photos.
    4. Set ClientTransaction.is_taken_away = True.
    5. Send a single bulk Telegram notification.
    """
    # Parse transaction_ids
    try:
        if transaction_ids.strip().startswith("["):
            t_ids = json.loads(transaction_ids)
        else:
            t_ids = [int(x.strip()) for x in transaction_ids.split(",") if x.strip()]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Noto'g'ri transaction_ids formati. Vergul bilan ajratilgan sonlar yoki JSON ro'yxat bering."
        )

    if not t_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hech qanday tranzaksiya ID berilmadi."
        )
    if len(set(t_ids)) != len(t_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="transaction_ids ichida takroriy ID bo'lmasligi kerak.",
        )

    if len(photos) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Kamida bitta rasm yuborilishi shart.",
        )
    if len(photos) > _MAX_PHOTOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Rasm soni {_MAX_PHOTOS} tadan oshmasligi kerak.",
        )

    # Validate all transactions exist and are not already proven
    from src.infrastructure.database.models.client_transaction import ClientTransaction
    from sqlalchemy import select

    tx_stmt = select(ClientTransaction).where(ClientTransaction.id.in_(t_ids))
    tx_results = (await session.execute(tx_stmt)).scalars().all()
    tx_by_id = {tx.id: tx for tx in tx_results}

    missing_ids = sorted(set(t_ids) - set(tx_by_id))
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tranzaksiyalar topilmadi: {list(missing_ids)}"
        )

    ordered_transactions = [tx_by_id[tx_id] for tx_id in t_ids]
    normalized_client_codes = {
        (tx.client_code or "").strip().upper() for tx in ordered_transactions
    }
    if "" in normalized_client_codes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Barcha tranzaksiyalarda client_code bo'lishi shart.",
        )
    if len(normalized_client_codes) != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Ommaviy topshirishda barcha tranzaksiyalar bitta mijozga "
                "tegishli bo'lishi shart."
            ),
        )

    proven_ids_result = await CargoDeliveryProofDAO.get_proven_transaction_ids(
        session, list(tx_by_id)
    )
    if proven_ids_result:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Ushbu tranzaksiyalar uchun isbot allaqachon mavjud: "
                f"{sorted(proven_ids_result)}"
            ),
        )

    # Use the first transaction ID as a folder reference for S3 (to keep things organized)
    base_tx_id = ordered_transactions[0].id
    client_code = ordered_transactions[0].client_code

    # --- Upload photos to S3 (ONLY ONCE) ---
    s3_keys: list[str] = []
    for idx, photo in enumerate(photos):
        content_type = (photo.content_type or "").lower()
        if content_type not in _ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{idx + 1}-rasm noto'g'ri fayl turi: {content_type!r}."
            )

        raw_bytes = await photo.read()
        if not raw_bytes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{idx + 1}-rasm bo'sh."
            )
        if len(raw_bytes) > _MAX_PHOTO_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"{idx + 1}-rasm hajmi o'ta katta."
            )
            
        try:
            s3_key = await _upload_proof_photo(
                raw_bytes=raw_bytes,
                original_filename=photo.filename or f"bulk_proof_{idx + 1}.jpg",
                transaction_id=base_tx_id,
                idx=idx,
            )
            s3_keys.append(s3_key)
        except Exception as exc:
            logger.exception("Bulk photo upload error idx=%d", idx)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{idx + 1}-rasmni yuklashda xatolik yuz berdi.",
            ) from exc

    # --- Database Persist (Multiple Proofs, Same S3 Keys) ---
    proofs_created = 0
    now = get_current_time()
    flight_counts: dict[str, int] = {}

    for tx in ordered_transactions:
        # 1. Create proof
        await CargoDeliveryProofDAO.create(
            session=session,
            transaction_id=tx.id,
            delivery_method=delivery_method,
            photo_s3_keys=s3_keys,
            marked_by_admin_id=admin.admin_id,
        )
        proofs_created += 1

        # 2. Mark taken
        if not tx.is_taken_away:
            tx.is_taken_away = True
            tx.taken_away_date = now

        # Collect data for notification
        flight_name = (tx.reys or "").strip() or "Noma'lum"
        flight_counts[flight_name] = flight_counts.get(flight_name, 0) + 1

    # Log to Audit
    await AdminAuditLogDAO.log(
        session=session,
        action="bulk_mark_cargo_taken",
        admin_id=admin.admin_id,
        role_snapshot=admin.role_name,
        details={
            "target_id": base_tx_id,  # Using first ID as reference
            "transaction_ids": t_ids,
            "delivery_method": delivery_method,
            "photo_count": len(s3_keys),
            "comment": comment,
        },
    )

    await session.commit()

    admin_label = await _resolve_warehouse_admin_label(session, admin)
    telegram_notified = await _send_bulk_taken_away_notification(
        transaction_ids=t_ids,
        client_code=client_code,
        delivery_method=delivery_method,
        admin_label=admin_label,
        s3_keys=s3_keys,
        flight_counts=flight_counts,
        comment=comment,
        event_time=now,
    )

    return BulkMarkTakenAwayResponse(
        transaction_ids=t_ids,
        client_code=client_code,
        delivery_method=delivery_method,
        delivery_method_label=DELIVERY_METHOD_LABELS.get(delivery_method, delivery_method),
        photo_count=len(s3_keys),
        proofs_created=proofs_created,
        telegram_notified=telegram_notified,
        message="Barcha yuklar muvaffaqiyatli 'olib ketildi' deb belgilandi va isbot saqlandi.",
    )


@router.post(
    "/transactions/{transaction_id}/mark-taken",
    response_model=MarkTakenAwayResponse,
    status_code=status.HTTP_200_OK,
    summary="Yukni olib ketildi deb belgilash (rasm bilan)",
)
async def mark_cargo_taken(
    transaction_id: int,
    delivery_method: DeliveryMethod = Form(
        ..., description="Yetkazib berish usuli: uzpost | bts | akb | yandex"
    ),
    photos: list[UploadFile] = File(
        ..., description="Isbotlovchi rasmlar (1 dan 10 tagacha)"
    ),
    comment: Annotated[str | None, Form(description="Omborxonachi izohi (ixtiyoriy)")] = None,
    admin: AdminJWTPayload = Depends(require_permission("warehouse", "mark_taken")),
    session: AsyncSession = Depends(get_db),
) -> MarkTakenAwayResponse:
    """
    Mark a cargo transaction as taken-away.

    Steps performed atomically:
    1. Validate transaction exists.
    2. Upload proof photos to S3 (``warehouse/{transaction_id}/``).
    3. Persist a ``CargoDeliveryProof`` record.
    4. Set ``ClientTransaction.is_taken_away = True``.
    5. Commit the DB transaction.
    6. Send a Telegram notification to the warehouse proof group.
    7. Log to ``AdminAuditLog``.

    The endpoint deliberately allows marking taken-away regardless of payment
    status — a partially-paid cargo may still be released by a warehouse
    worker with appropriate permissions.  Payment recovery is a separate
    business process.
    """
    if len(photos) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Kamida bitta rasm yuborilishi shart.",
        )
    if len(photos) > _MAX_PHOTOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Rasm soni {_MAX_PHOTOS} tadan oshmasligi kerak.",
        )

    transaction = None
    if transaction_id > 0:
        transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)
    else:
        # It's an unpaid cargo from FlightCargo without a transaction
        from src.infrastructure.database.models.flight_cargo import FlightCargo
        from src.infrastructure.database.models.client_transaction import (
            ClientTransaction,
        )
        from src.api.services.verification.utils import get_usd_rate, get_extra_charge

        cargo_id = -transaction_id
        cargo = await session.get(FlightCargo, cargo_id)
        if cargo:
            # Create a pending ClientTransaction for this cargo
            client_obj = await ClientDAO.get_by_client_code(session, cargo.client_id)
            telegram_id = client_obj.telegram_id if client_obj else 0

            canonical_code = client_obj.payment_code if client_obj else cargo.client_id

            usd_rate = await get_usd_rate(session)
            extra_charge = await get_extra_charge(session)
            weight = float(cargo.weight_kg) if cargo.weight_kg else 0.0
            price_per_kg = float(cargo.price_per_kg) if cargo.price_per_kg else 0.0
            if weight > 0 and price_per_kg > 0:
                total_amt = weight * price_per_kg * usd_rate + extra_charge
            else:
                total_amt = 0.0

            transaction = ClientTransaction(
                telegram_id=telegram_id,
                client_code=canonical_code,
                qator_raqami=cargo.id,
                reys=cargo.flight_name,
                summa=total_amt,
                vazn=str(weight),
                payment_type="online",  # default
                payment_status="pending",
                paid_amount=0.0,
                total_amount=total_amt,
                remaining_amount=total_amt,
                payment_balance_difference=-total_amt,  # debt
                is_taken_away=False,
            )
            session.add(transaction)
            await session.flush()
            # Set transaction_id to the newly created transaction
            transaction_id = transaction.id

    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{transaction_id} raqamli tranzaksiya/yuk topilmadi.",
        )

    # Track whether transaction was already marked taken (e.g. via delivery request approval).
    # We still allow the warehouse worker to upload proof in that case — don't block them.
    already_taken = transaction.is_taken_away

    # Block duplicate proof submissions — one proof per transaction is enough.
    if await CargoDeliveryProofDAO.exists_for_transaction(session, transaction_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu tranzaksiya uchun isbot allaqachon yuborilgan.",
        )

    now = get_current_time()

    # --- Upload photos to S3 ---
    s3_keys: list[str] = []
    for idx, photo in enumerate(photos):
        # Validate content type before reading the full body.
        content_type = (photo.content_type or "").lower()
        if content_type not in _ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"{idx + 1}-rasm noto'g'ri fayl turi: {content_type!r}. "
                    f"Faqat JPEG, PNG, WebP, HEIC rasmlari qabul qilinadi."
                ),
            )

        raw_bytes = await photo.read()
        if not raw_bytes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{idx + 1}-rasm bo'sh. Qayta urinib ko'ring.",
            )
        if len(raw_bytes) > _MAX_PHOTO_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"{idx + 1}-rasm hajmi {len(raw_bytes) // (1024 * 1024)} MB — "
                    f"ruxsat etilgan maksimal hajm {_MAX_PHOTO_BYTES // (1024 * 1024)} MB."
                ),
            )
        try:
            s3_key = await _upload_proof_photo(
                raw_bytes=raw_bytes,
                original_filename=photo.filename or f"proof_{idx + 1}.jpg",
                transaction_id=transaction_id,
                idx=idx,
            )
            s3_keys.append(s3_key)
        except Exception as exc:
            logger.error(
                "S3 upload failed for proof photo %d (tx=%d): %s",
                idx + 1,
                transaction_id,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{idx + 1}-rasmni S3 ga yuklashda xatolik yuz berdi.",
            )

    # --- Persist proof record ---
    proof = await CargoDeliveryProofDAO.create(
        session=session,
        transaction_id=transaction_id,
        delivery_method=delivery_method,
        photo_s3_keys=s3_keys,
        marked_by_admin_id=admin.admin_id,
    )

    # --- Update transaction (only if not already taken) ---
    if not already_taken:
        transaction.is_taken_away = True
        transaction.taken_away_date = now
        session.add(transaction)

    # --- Audit log ---
    await AdminAuditLogDAO.log(
        session=session,
        action="WAREHOUSE_MARKED_TAKEN",
        admin_id=admin.admin_id,
        role_snapshot=admin.role_name,
        details={
            "transaction_id": transaction_id,
            "client_code": transaction.client_code,
            "flight_name": transaction.reys,
            "delivery_method": delivery_method,
            "photo_count": len(s3_keys),
            "proof_id": proof.id,
        },
    )

    await session.commit()

    # --- Telegram notification (DB already committed) ---
    client_obj = await ClientDAO.get_by_client_code(session, transaction.client_code)
    admin_label = await _resolve_warehouse_admin_label(session, admin)
    telegram_notified = await _send_taken_away_notification(
        transaction_id=transaction_id,
        client_code=transaction.client_code,
        client_full_name=client_obj.full_name if client_obj else None,
        flight_name=transaction.reys,
        remaining_amount=float(transaction.remaining_amount),
        payment_status=transaction.payment_status,
        delivery_method=delivery_method,
        admin_label=admin_label,
        s3_keys=s3_keys,
        event_time=now,
        comment=comment,
    )

    return MarkTakenAwayResponse(
        transaction_id=transaction_id,
        client_code=transaction.client_code,
        flight_name=transaction.reys,
        delivery_method=delivery_method,
        delivery_method_label=DELIVERY_METHOD_LABELS.get(
            delivery_method, delivery_method
        ),
        photo_count=len(s3_keys),
        proof=DeliveryProofResponse(
            proof_id=proof.id,
            transaction_id=proof.transaction_id,
            delivery_method=proof.delivery_method,
            photo_s3_keys=proof.photo_s3_keys,
            marked_by_admin_id=proof.marked_by_admin_id,
            created_at=proof.created_at,
        ),
        telegram_notified=telegram_notified,
        message="Yuk muvaffaqiyatli olib ketilgan deb belgilandi.",
    )




@router.get(
    "/transactions/search-grouped",
    response_model=WarehouseGroupedSearchResponse,
    summary="Mijozlar bo'yicha guruhlangan yuk qidiruvi (isbotlar bilan)",
)
async def search_transactions_grouped(
    code: Annotated[str | None, Query(max_length=50)] = None,
    phone: Annotated[str | None, Query(max_length=30)] = None,
    name: Annotated[str | None, Query(max_length=100)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    flight: Annotated[str | None, Query(max_length=50)] = None,
    payment_status: PaymentStatusFilter = "all",
    taken_status: TakenStatusFilter = "all",
    sort_order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 50,
    admin: AdminJWTPayload = Depends(require_permission("warehouse", "read")),
    session: AsyncSession = Depends(get_db),
) -> WarehouseGroupedSearchResponse:
    """
    Qidiruv natijalarini reyslar bo'yicha guruhlab qaytaradi.
    Har bir reys ichida Xitoydan yuklangan karobka rasmlari (FlightCargo) havolalari qo'shiladi.
    """
    from sqlalchemy import select, func
    from src.infrastructure.database.models.client_transaction import ClientTransaction
    import json

    # Normalize empty/whitespace query params (e.g. code="") to None.
    code = code.strip() if code and code.strip() else None
    phone = phone.strip() if phone and phone.strip() else None
    name = name.strip() if name and name.strip() else None
    q = q.strip() if q and q.strip() else None
    flight = flight.strip() if flight and flight.strip() else None

    if not any([code, phone, name, q, flight]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Kamida bitta qidiruv parametri kerak: code, phone, name, q yoki flight.",
        )

    # Build combined filter_type
    if taken_status == "taken":
        dao_filter_type = "taken"
    elif taken_status == "not_taken":
        dao_filter_type = "not_taken"
    else:
        dao_filter_type = payment_status

    use_client_filter = any([code, phone, name, q])
    client_code_filter: list[str] | None = None

    if use_client_filter:
        # Find matching clients.
        matched_clients, _ = await ClientDAO.search_clients_paginated(
            session, page=1, size=200, code=code, phone=phone, name=name, query=q
        )

        code_variants_set = set()
        for c in matched_clients:
            for attr in ("extra_code", "client_code", "legacy_code"):
                val = getattr(c, attr, None)
                if val:
                    code_variants_set.add(val)

        search_str = code or q
        if search_str:
            q_upper = f"%{search_str.upper()}%"
            direct_codes_stmt = select(ClientTransaction.client_code).where(
                func.upper(ClientTransaction.client_code).ilike(q_upper)
            ).distinct()

            direct_codes_result = await session.execute(direct_codes_stmt)
            for code_val in direct_codes_result.scalars():
                if code_val:
                    code_variants_set.add(code_val)

        if not code_variants_set:
            return WarehouseGroupedSearchResponse(
                items=[],
                total_count=0,
                page=page,
                size=size,
            )

        client_code_filter = list(code_variants_set)

    offset = (page - 1) * size

    # We need a way to group. First, fetch matching transactions.
    if client_code_filter is not None:
        db_transactions = await ClientTransactionDAO.get_filtered_transactions(
            session,
            client_code=client_code_filter,
            filter_type=dao_filter_type,
            sort_order=sort_order,
            limit=size,
            offset=offset,
            flight_code=flight,
        )

        total_count = await ClientTransactionDAO.count_filtered_transactions_by_client_code(
            session,
            client_code=client_code_filter,
            filter_type=dao_filter_type,
            flight_code=flight,
        )
    else:
        # Flight-only grouped search.
        db_transactions = await ClientTransactionDAO.get_transactions_by_flight_filtered(
            session,
            flight_name=flight,
            filter_type=dao_filter_type,
            sort_order=sort_order,
            limit=size,
            offset=offset,
        )
        total_count = await ClientTransactionDAO.count_transactions_by_flight_filtered(
            session,
            flight_name=flight,
            filter_type=dao_filter_type,
        )

    if not db_transactions:
        return WarehouseGroupedSearchResponse(
            items=[],
            total_count=total_count,
            page=page,
            size=size,
        )

    search_tx_ids = [tx.id for tx in db_transactions]
    proven_ids = await CargoDeliveryProofDAO.get_proven_transaction_ids(session, search_tx_ids)

    # Group transactions by client_code -> reys
    from collections import defaultdict
    grouped = {}

    for tx in db_transactions:
        c_code = (tx.client_code or "").upper()
        if c_code not in grouped:
            grouped[c_code] = defaultdict(list)
        grouped[c_code][tx.reys].append(tx)

    client_groups = []
    
    for c_code, flights_map in grouped.items():
        client_obj = await ClientDAO.get_by_client_code(session, c_code)
        
        wallet_balance = 0.0
        debt = 0.0
        if client_obj:
            balances = await ClientTransactionDAO.get_wallet_balances(session, client_obj.client_code)
            wallet_balance = balances.get("wallet_balance", 0.0)
            debt = balances.get("debt", 0.0)
        
        total_unpaid_amount = 0.0
        flight_groups = []

        for flight_name, txs in flights_map.items():
            f_total_weight = sum(float(tx.vazn) for tx in txs if tx.vazn and tx.vazn.replace('.', '', 1).isdigit())
            f_total_amount = sum(float(tx.summa) for tx in txs if tx.summa)
            f_remaining_amount = sum(float(tx.remaining_amount) for tx in txs if tx.remaining_amount)
            total_unpaid_amount += f_remaining_amount
            
            # Fetch FlightCargo to get photos
            cargo_photos = []
            flight_cargos_stmt = select(FlightCargo).where(
                func.upper(FlightCargo.client_id) == c_code,
                func.upper(FlightCargo.flight_name) == flight_name.upper()
            )
            flight_cargos = (await session.execute(flight_cargos_stmt)).scalars().all()
            
            for fc in flight_cargos:
                if fc.photo_file_ids:
                    try:
                        photo_list = json.loads(fc.photo_file_ids)
                        for s3_key in photo_list:
                            # Generate presigned URL for 2 hours
                            url = await s3_manager.generate_presigned_url(s3_key, expires_in=7200)
                            if url:
                                cargo_photos.append(url)
                    except json.JSONDecodeError:
                        pass
            
            tx_items = []
            for tx in txs:
                tx_items.append(GroupedTransactionItem(
                    id=tx.id,
                    qator_raqami=tx.qator_raqami,
                    vazn=tx.vazn,
                    summa=float(tx.summa),
                    payment_status=tx.payment_status,
                    remaining_amount=float(tx.remaining_amount),
                    is_taken_away=tx.is_taken_away,
                    taken_away_date=tx.taken_away_date,
                    comment=None, # Assuming no specific comment field mapped here
                    has_proof=(tx.id in proven_ids)
                ))
                
            flight_groups.append(FlightGroup(
                flight_name=flight_name,
                total_weight_kg=round(f_total_weight, 2),
                total_amount=round(f_total_amount, 2),
                total_remaining_amount=round(f_remaining_amount, 2),
                flight_cargo_photos=cargo_photos,
                transactions=tx_items
            ))

        client_groups.append(ClientGroup(
            client_code=c_code,
            full_name=client_obj.full_name if client_obj else None,
            phone=client_obj.phone if client_obj else None,
            wallet_balance=wallet_balance,
            debt=debt,
            total_unpaid_amount=total_unpaid_amount,
            flights=flight_groups
        ))

    return WarehouseGroupedSearchResponse(
        items=client_groups,
        total_count=total_count,
        page=page,
        size=size
    )

