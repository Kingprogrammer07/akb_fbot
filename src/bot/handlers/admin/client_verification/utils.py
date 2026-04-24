"""Utility functions for client verification module."""
import hashlib
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.bot.handlers.admin.settings import extra_charge_edit_handler
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.services.client_transaction import ClientTransactionService
from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.bot.utils.currency_converter import currency_converter


# Global context storage for admin sessions
VERIFICATION_CONTEXT: dict[int, dict] = {}


async def safe_answer_callback(
    callback,
    text: str = "",
    show_alert: bool = False
) -> None:
    """Safely answer callback query without raising exceptions."""
    try:
        if callback.bot:
            await callback.bot.answer_callback_query(
                callback_query_id=callback.id,
                text=text,
                show_alert=show_alert
            )
    except Exception as e:
        print(f"Failed to answer callback safely: {e}")


def encode_flight_code(flight_code: str) -> str:
    """Encode flight code to short hash (8 chars) to fit in callback_data."""
    if not flight_code or flight_code == "none":
        return "none"
    hash_obj = hashlib.md5(flight_code.encode('utf-8'))
    return hash_obj.hexdigest()[:8]


async def decode_flight_code(
    flight_hash: str,
    client_code: str | list[str],
    session: AsyncSession,
    transaction_service: ClientTransactionService
) -> str | None:
    """Decode flight hash back to flight code by looking up in user's transactions.

    Accepts a single code or the full list of active codes so that flights stored
    under any of the client's aliases (extra_code, client_code, legacy_code) are found.
    """
    if not flight_hash or flight_hash == "none":
        return None
    flights = await transaction_service.get_unique_flights_by_client_code(client_code, session)
    for flight in flights:
        if encode_flight_code(flight) == flight_hash:
            return flight
    return None


async def decode_flight_code_from_cargo(
    flight_hash: str,
    client_code: str | list[str],
    session: AsyncSession
) -> str | None:
    """Decode flight hash back to flight code by looking up in client's sent cargos.

    Accepts a single code or the full list of active codes so that cargos stored
    under any of the client's aliases are found.
    """
    if not flight_hash or flight_hash == "none":
        return None
    flights = await FlightCargoDAO.get_unique_flights_by_client_sent(session, client_code)
    for flight in flights:
        if encode_flight_code(flight) == flight_hash:
            return flight
    return None


async def get_unpaid_payments_for_client(
    client_code: str | list[str],
    session: AsyncSession,
    redis: Redis,  # Kept for signature compatibility but not used
    flight_filter: str | None = None
) -> list[dict]:
    """
    Get unpaid cargo items for a client.

    BUSINESS RULE (SOURCE OF TRUTH):
    An "UNPAID cargo" is defined as:
    1. Exists in table: flight_cargo
    2. flight_cargo.is_sent = TRUE
    3. There is NO row in client_transaction_data for:
       (client_code, flight_name=reys, qator_raqami=cargo.id)

    Amount is calculated from flight_cargo: weight_kg * price_per_kg

    Args:
        client_code: Client code
        session: Database session
        redis: Redis client (kept for API compatibility, not used)
        flight_filter: Optional flight name to filter by

    Returns:
        List of unpaid cargo dicts with:
        - cargo_id: int (flight_cargo.id)
        - flight_name: str
        - row_number: int (equals cargo_id for transaction matching)
        - total_payment: float (weight_kg * price_per_kg)
        - weight: float
        - has_cargo: bool (always True for valid items)
        - existing_tx_id: None (no transaction exists)
        - paid_amount: 0.0
        - remaining_amount: float (same as total_payment)
        - payment_status: 'pending'
        - price_per_kg: float
        - created_at: datetime
    """
    # Get all sent cargos for this client
    sent_cargos = await FlightCargoDAO.get_sent_by_client(
        session, client_code, flight_filter
    )

    if not sent_cargos:
        return []

    unpaid_payments = []

    static_data = await StaticDataDAO.get_by_id(session, 1)
    extra_charge = static_data.extra_charge if static_data else 0
    try:
        usd_rate = await currency_converter.get_rate_async(session, "USD", "UZS")
    except Exception:
        await session.rollback()
        usd_rate = 12000

    for cargo in sent_cargos:
        # Check if payment exists for this cargo
        # Key matching: qator_raqami = cargo.id, reys = flight_name
        existing_tx = await ClientTransactionDAO.get_by_client_code_flight_row(
            session,
            client_code,
            cargo.flight_name,
            cargo.id  # cargo.id is the row_number (qator_raqami)
        )

        # If transaction exists, this cargo is NOT unpaid - skip it
        if existing_tx is not None:
            continue

        # Calculate payment amount from cargo data
        weight = float(cargo.weight_kg) if cargo.weight_kg else 0.0
        price_per_kg = float(cargo.price_per_kg) if cargo.price_per_kg else 0.0
        total_amount = weight * price_per_kg * usd_rate + extra_charge

        # Skip if we can't calculate amount (no weight or price)
        if total_amount <= 0:
            continue

        unpaid_item = {
            "cargo_id": cargo.id,
            "flight_name": cargo.flight_name,
            "row_number": cargo.id,  # qator_raqami = cargo.id
            "total_payment": total_amount,
            "weight": weight,
            "has_cargo": True,
            "existing_tx_id": None,
            "paid_amount": 0.0,
            "remaining_amount": total_amount,
            "payment_status": "pending",
            "price_per_kg": price_per_kg,
            "created_at": cargo.created_at
        }

        unpaid_payments.append(unpaid_item)

    return unpaid_payments


async def get_cargo_by_id(
    cargo_id: int,
    session: AsyncSession
) -> dict | None:
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
    total_amount = weight * price_per_kg

    return {
        "cargo_id": cargo.id,
        "flight_name": cargo.flight_name,
        "client_id": cargo.client_id,
        "weight": weight,
        "price_per_kg": price_per_kg,
        "total_amount": total_amount,
        "is_sent": cargo.is_sent,
        "created_at": cargo.created_at
    }
