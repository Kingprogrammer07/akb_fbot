"""Utility functions for Client Verification API."""

import json
import httpx
from typing import Optional
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
from src.bot.utils.currency_converter import currency_converter
from src.config import config

# Default USD to UZS rate fallback
DEFAULT_USD_RATE = 12000.0
from src.infrastructure.tools.money_utils import money


def get_usd_rate_sync() -> float:
    """Fallback if needed."""
    return DEFAULT_USD_RATE


async def get_usd_rate(session: AsyncSession) -> float:
    """
    Get current USD to UZS exchange rate asynchronously.

    Returns:
        USD to UZS rate, fallback to DEFAULT_USD_RATE on error
    """
    try:
        return await currency_converter.get_rate_async(session, "USD", "UZS")
    except Exception:
        return DEFAULT_USD_RATE


async def get_extra_charge(session: AsyncSession) -> int:
    """
    Get extra charge amount from static_data table.

    Args:
        session: Database session

    Returns:
        Extra charge amount (default 0 if not found)
    """
    static_data = await StaticDataDAO.get_by_id(session, 1)
    return static_data.extra_charge if static_data else 0


async def get_price_per_kg_default(session: AsyncSession) -> float:
    """
    Get default price per kg from static_data table.

    Args:
        session: Database session

    Returns:
        Default price per kg (9.5 if not found)
    """
    static_data = await StaticDataDAO.get_by_id(session, 1)
    return static_data.price_per_kg if static_data else 9.5


async def calculate_cargo_amount(
    weight_kg: Optional[Decimal], price_per_kg: Optional[Decimal], session: AsyncSession
) -> tuple[float, float, float, float]:
    """
    Calculate total payment amount for cargo.

    Formula: weight_kg * price_per_kg * usd_rate + extra_charge

    Args:
        weight_kg: Cargo weight in kg
        price_per_kg: Price per kg in USD
        session: Database session

    Returns:
        Tuple of (total_amount_uzs, usd_rate, extra_charge, price_per_kg_uzs)
    """
    weight = float(weight_kg) if weight_kg else 0.0
    price = float(price_per_kg) if price_per_kg else 0.0

    if weight <= 0 or price <= 0:
        return 0.0, 0.0, 0.0, 0.0

    usd_rate = await get_usd_rate(session)
    extra_charge = await get_extra_charge(session)
    price_per_kg_uzs = price * usd_rate

    total_amount = weight * price_per_kg_uzs + extra_charge

    return total_amount, usd_rate, float(extra_charge), price_per_kg_uzs


async def calculate_expected_payment(
    weight: float, price_per_kg: float, session: AsyncSession
) -> dict:
    """
    Calculate expected payment details for cargo.

    Args:
        weight: Weight in kg
        price_per_kg: Price per kg in USD
        session: Database session

    Returns:
        Dict with calculation details:
        {
            "total_payment": float,
            "price_per_kg_usd": float,
            "price_per_kg_uzs": float,
            "usd_rate": float,
            "extra_charge": float
        }
    """
    usd_rate = await get_usd_rate(session)
    extra_charge = await get_extra_charge(session)
    price_per_kg_uzs = price_per_kg * usd_rate
    total_payment = weight * price_per_kg_uzs + extra_charge

    return {
        "total_payment": total_payment,
        "price_per_kg_usd": price_per_kg,
        "price_per_kg_uzs": price_per_kg_uzs,
        "usd_rate": usd_rate,
        "extra_charge": float(extra_charge),
    }


async def get_unpaid_cargo_items(
    client_code: str | list[str],
    session: AsyncSession,
    flight_filter: Optional[str] = None,
) -> list[dict]:
    """
    Get unpaid cargo items for a client.

    BUSINESS RULE (NEW - SOURCE OF TRUTH):
    An "UNPAID cargo" is defined as:
    - Any record in flight_cargo table where is_sent = TRUE
    - NO dependency on client_transaction_data
    - Payments are stored separately and should NOT be used to determine unpaid cargo

    Args:
        client_code: Client code
        session: Database session
        flight_filter: Optional flight name to filter by

    Returns:
        List of unpaid cargo dicts with keys:
        - cargo_id, flight_name, row_number, total_payment, weight,
          price_per_kg, price_per_kg_uzs, usd_rate, extra_charge,
          payment_status, created_at
    """
    # Get all sent cargos for this client
    sent_cargos = await FlightCargoDAO.get_sent_by_client(
        session, client_code, flight_filter
    )

    if not sent_cargos:
        return []

    # Fetch ALL transactions for this client to avoid N+1 queries
    existing_transactions = await ClientTransactionDAO.get_by_client_code(
        session, client_code
    )

    # Create a map of processed cargo IDs (qator_raqami) to their payment status
    cargo_status_map = {}
    for tx in existing_transactions:
        # If flight filter is applied, only consider transactions for that flight
        if flight_filter and tx.reys.upper() != flight_filter.upper():
            continue
        # Only consider valid qator_raqami
        if tx.qator_raqami and tx.qator_raqami > 0:
            cargo_status_map[tx.qator_raqami] = tx.payment_status

    unpaid_items = []

    # Get rates once
    usd_rate = await get_usd_rate(session)
    extra_charge = await get_extra_charge(session)

    for cargo in sent_cargos:
        # Check if this specific cargo has a transaction that is fully paid
        status = cargo_status_map.get(cargo.id)

        # If the cargo has a transaction that is "paid" or "partial", skip it for POS bulk logic.
        # "partial" transactions should be completed via the existing transactions API, not bulk POS.
        if status in ("paid", "partial"):
            continue
        # Calculate payment amount from cargo data
        weight = float(cargo.weight_kg) if cargo.weight_kg else 0.0
        price_per_kg = float(cargo.price_per_kg) if cargo.price_per_kg else 0.0

        # Skip if invalid cargo (no weight or price)
        if weight <= 0 or price_per_kg <= 0:
            continue

        price_per_kg_uzs = price_per_kg * usd_rate
        total_amount = weight * price_per_kg_uzs + extra_charge

        unpaid_item = {
            "cargo_id": cargo.id,
            "flight_name": cargo.flight_name,
            "row_number": cargo.id,  # qator_raqami = cargo.id
            "total_payment": total_amount,
            "weight": weight,
            "payment_status": "pending",
            "price_per_kg": price_per_kg,
            "price_per_kg_uzs": price_per_kg_uzs,
            "usd_rate": usd_rate,
            "extra_charge": extra_charge,
            "created_at": cargo.created_at,
        }

        unpaid_items.append(unpaid_item)

    return unpaid_items


async def get_cargo_details(cargo_id: int, session: AsyncSession) -> Optional[dict]:
    """
    Get cargo details by ID for payment processing.

    Args:
        cargo_id: FlightCargo.id
        session: Database session

    Returns:
        Dict with cargo details or None if not found
    """
    cargo = await FlightCargoDAO.get_by_id(session, cargo_id)
    if not cargo:
        return None

    weight = float(cargo.weight_kg) if cargo.weight_kg else 0.0
    price_per_kg = float(cargo.price_per_kg) if cargo.price_per_kg else 0.0

    usd_rate = await get_usd_rate(session)
    extra_charge = await get_extra_charge(session)
    price_per_kg_uzs = price_per_kg * usd_rate
    total_amount = weight * price_per_kg_uzs + extra_charge

    return {
        "cargo_id": cargo.id,
        "flight_name": cargo.flight_name,
        "client_id": cargo.client_id,
        "weight": weight,
        "price_per_kg": price_per_kg,
        "price_per_kg_uzs": price_per_kg_uzs,
        "usd_rate": usd_rate,
        "extra_charge": float(extra_charge),
        "total_amount": total_amount,
        "is_sent": cargo.is_sent,
        "photo_file_ids": cargo.photo_file_ids,
        "comment": cargo.comment,
        "created_at": cargo.created_at,
    }


def validate_cargo_ownership(
    cargo_data: dict, client_code: str, flight_name: str, client_obj=None
) -> tuple[bool, Optional[str]]:
    """
    Validate that cargo belongs to client and flight.

    Args:
        cargo_data: Cargo details dict
        client_code: Expected client code (from request)
        flight_name: Expected flight name
        client_obj: Optional Client object. If provided, checks against all valid codes of the client.

    Returns:
        Tuple of (is_valid, error_message)
    """
    cargo_client_id = cargo_data["client_id"].upper()

    if client_obj:
        valid_codes = []
        if getattr(client_obj, "client_code", None):
            valid_codes.append(client_obj.client_code.upper())
        if getattr(client_obj, "extra_code", None):
            valid_codes.append(client_obj.extra_code.upper())
        if getattr(client_obj, "legacy_code", None):
            valid_codes.append(client_obj.legacy_code.upper())

        if cargo_client_id not in valid_codes:
            return False, "Cargo does not belong to this client"
    else:
        if cargo_client_id != client_code.upper():
            return False, "Cargo does not belong to this client"

    if cargo_data["flight_name"].upper() != flight_name.upper():
        return False, "Cargo does not match the specified flight"

    if not cargo_data["is_sent"]:
        return False, "Cargo has not been sent yet"

    if cargo_data["total_amount"] <= 0:
        return False, "Cannot calculate cargo amount"

    return True, None


def validate_paid_amount(
    paid_amount: float, expected_amount: float
) -> tuple[bool, Optional[str]]:
    """
    Validate paid amount against expected amount.

    Rules:
    - paid_amount must be > 0
    - paid_amount cannot exceed expected_amount * 2 (anti-error guard)

    Args:
        paid_amount: Amount paid by client
        expected_amount: Calculated expected payment

    Returns:
        Tuple of (is_valid, error_message)
    """
    if paid_amount <= 0:
        return False, "paid_amount must be greater than 0"

    # Use money() for safe comparison
    safe_paid = money(paid_amount)
    safe_expected = money(expected_amount)

    max_allowed = safe_expected * 2
    if safe_paid > max_allowed:
        return (
            False,
            f"paid_amount ({paid_amount}) exceeds maximum allowed ({max_allowed})",
        )

    return True, None


def calculate_payment_balance_difference(
    paid_amount: float, expected_amount: float
) -> Decimal:
    """
    Calculate payment balance difference.

    Formula: paid_amount - expected_amount

    Interpretation:
    - Negative: client is in debt
    - Positive: client overpaid
    - Zero: exact payment

    Args:
        paid_amount: Actual amount paid
        expected_amount: Calculated expected payment

    Returns:
        Balance difference
    """
    return money(paid_amount) - money(expected_amount)


# ============================================================================
# Telegram File URL Resolution
# ============================================================================


async def resolve_telegram_file_url(file_id: str) -> Optional[str]:
    """
    Resolve Telegram file_id to a downloadable URL.

    Steps:
    1. Call Telegram getFile API with file_id
    2. Extract file_path from response
    3. Build download URL

    Args:
        file_id: Telegram file_id string

    Returns:
        Full URL to download the file, or None if resolution fails
    """
    bot_token = config.telegram.TOKEN.get_secret_value()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1: Call getFile API
            get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile"
            response = await client.get(get_file_url, params={"file_id": file_id})

            if response.status_code != 200:
                return None

            data = response.json()

            if not data.get("ok"):
                return None

            # Step 2: Extract file_path
            file_path = data.get("result", {}).get("file_path")
            if not file_path:
                return None

            # Step 3: Build download URL
            download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
            return download_url

    except Exception:
        return None


async def resolve_telegram_file_urls(file_ids: list[str]) -> list[dict]:
    """
    Resolve multiple Telegram file_ids to downloadable URLs.

    Args:
        file_ids: List of Telegram file_id strings

    Returns:
        List of dicts with file_id and telegram_url (url may be None on failure)
    """
    results = []

    for file_id in file_ids:
        telegram_url = await resolve_telegram_file_url(file_id)
        results.append({"file_id": file_id, "telegram_url": telegram_url})

    return results


def parse_photo_file_ids(photo_file_ids_json: Optional[str]) -> list[str]:
    """
    Parse photo_file_ids JSON string to list of file_ids.

    Args:
        photo_file_ids_json: JSON string (list of file_ids) or None

    Returns:
        List of file_id strings
    """
    if not photo_file_ids_json:
        return []

    try:
        file_ids = json.loads(photo_file_ids_json)
        if isinstance(file_ids, str):
            return [file_ids]
        if isinstance(file_ids, list):
            return [fid for fid in file_ids if isinstance(fid, str)]
        return []
    except (json.JSONDecodeError, TypeError):
        # If not valid JSON, treat as single file_id
        return [photo_file_ids_json]
