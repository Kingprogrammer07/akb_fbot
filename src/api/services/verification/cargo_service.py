"""Cargo service for unpaid cargo and cargo details."""
import json
from typing import Optional, Literal
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.services.flight_cargo import FlightCargoService as BotFlightCargoService

from src.api.schemas.verification import (
    UnpaidCargoItem,
    UnpaidCargoListResponse,
    CargoDetail,
    CargoPhoto,
    CargoListResponse,
    FlightPaymentSummary,
    SortOrder,
    CargoImageSchema,
    TransactionCargoImagesResponse,
)
from .utils import (
    get_unpaid_cargo_items,
    get_cargo_details,
    get_usd_rate,
    get_extra_charge,
    parse_photo_file_ids,
    resolve_telegram_file_urls,
)


class CargoService:
    """Service for cargo-related operations."""

    @staticmethod
    async def get_unpaid_cargo_list(
        client_code: str | list[str],
        session: AsyncSession,
        filter_type: Literal["all", "pending"],
        sort_order: SortOrder,
        limit: int,
        offset: int,
        flight_filter: Optional[str] = None
    ) -> UnpaidCargoListResponse:
        """
        Get paginated list of unpaid cargo items for a client.

        BUSINESS RULE (NEW - Source of Truth):
        Unpaid cargo = flight_cargo.is_sent=True (no transaction dependency).

        All filter parameters are REQUIRED - no defaults.

        Args:
            client_code: Client code
            session: Database session
            filter_type: Filter type (required) - 'all' or 'pending'
            sort_order: Sort order (required) - 'asc' or 'desc'
            limit: Items per page (required)
            offset: Offset for pagination (required)
            flight_filter: Optional flight name filter

        Returns:
            UnpaidCargoListResponse with paginated items
        """
        # Get unpaid items (filter applied at source: 'all' includes partial, 'pending' excludes it)
        all_unpaid = await get_unpaid_cargo_items(
            client_code, session, flight_filter, filter_type
        )

        # Sort by flight_name
        reverse = sort_order == "desc"
        all_unpaid.sort(key=lambda x: x["flight_name"], reverse=reverse)

        total_count = len(all_unpaid)
        total_pages = max(1, (total_count + limit - 1) // limit)

        # Paginate
        page_items = all_unpaid[offset:offset + limit]

        # Convert to schema
        items = [
            UnpaidCargoItem(
                cargo_id=item["cargo_id"],
                flight_name=item["flight_name"],
                row_number=item["row_number"],
                weight=item["weight"],
                price_per_kg=item["price_per_kg"],
                total_payment=item["total_payment"],
                currency="UZS",
                payment_status=item["payment_status"],
                created_at=item["created_at"]
            )
            for item in page_items
        ]

        return UnpaidCargoListResponse(
            items=items,
            total_count=total_count,
            limit=limit,
            offset=offset,
            total_pages=total_pages,
            filter_type=filter_type,
            sort_order=sort_order,
            flight_filter=flight_filter
        )

    @staticmethod
    async def get_cargo_by_id(
        cargo_id: int,
        session: AsyncSession
    ) -> Optional[dict]:
        """
        Get cargo details by ID.

        Args:
            cargo_id: FlightCargo.id
            session: Database session

        Returns:
            Cargo details dict or None
        """
        return await get_cargo_details(cargo_id, session)

    @staticmethod
    async def get_transaction_cargos(
        transaction_id: int,
        session: AsyncSession
    ) -> CargoListResponse:
        """
        Get cargos associated with a transaction.

        Args:
            transaction_id: Transaction ID
            session: Database session

        Returns:
            CargoListResponse with cargo details and photos
        """
        # Get transaction
        transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)
        if not transaction:
            return CargoListResponse(cargos=[], total_count=0)

        flight_name = transaction.reys
        client_code = transaction.client_code

        # Get cargos for this flight and client
        result = await BotFlightCargoService.get_client_cargos(
            session,
            flight_name=flight_name,
            client_id=client_code
        )

        cargos_raw = result.get('cargos', [])

        cargos = []
        for cargo in cargos_raw:
            # Parse photo file IDs
            photos = []
            try:
                photo_file_ids = json.loads(cargo.photo_file_ids) if cargo.photo_file_ids else []
                if isinstance(photo_file_ids, str):
                    photo_file_ids = [photo_file_ids]
                photos = [CargoPhoto(file_id=fid) for fid in photo_file_ids]
            except (json.JSONDecodeError, TypeError):
                if cargo.photo_file_ids:
                    photos = [CargoPhoto(file_id=cargo.photo_file_ids)]

            cargos.append(CargoDetail(
                id=cargo.id,
                flight_name=cargo.flight_name,
                client_id=cargo.client_id,
                weight_kg=float(cargo.weight_kg) if cargo.weight_kg else None,
                price_per_kg=float(cargo.price_per_kg) if cargo.price_per_kg else None,
                comment=cargo.comment,
                is_sent=cargo.is_sent,
                photos=photos,
                created_at=cargo.created_at
            ))

        return CargoListResponse(
            cargos=cargos,
            total_count=len(cargos)
        )

    @staticmethod
    async def get_unpaid_flights(
        client_code: str | list[str],
        session: AsyncSession
    ) -> list[str]:
        """
        Get list of flights with unpaid cargo for a client.

        Args:
            client_code: Client code or list of all active aliases
            session: Database session

        Returns:
            List of flight names
        """
        return await FlightCargoDAO.get_unique_flights_by_client_sent(
            session, client_code
        )

    @staticmethod
    async def calculate_flight_payment(
        client_code: str | list[str],
        flight_name: str,
        session: AsyncSession
    ) -> Optional[FlightPaymentSummary]:
        """
        Calculate payment summary for ALL cargos of a specific client in a specific flight.

        Only cargos with is_sent=True are included.

        Args:
            client_code: Client code
            flight_name: Flight name
            session: Database session

        Returns:
            FlightPaymentSummary with totals, or None if no cargos found
        """
        # Get sent cargos for this client and flight
        cargos = await FlightCargoDAO.get_sent_by_client(
            session, client_code, flight_name
        )

        if not cargos:
            return None

        usd_rate = get_usd_rate()
        extra_charge = await get_extra_charge(session)

        total_weight = 0.0
        total_payment = 0.0
        track_codes = []
        price_per_kg_usd = 0.0

        for cargo in cargos:
            weight = float(cargo.weight_kg) if cargo.weight_kg else 0.0
            price = float(cargo.price_per_kg) if cargo.price_per_kg else 0.0

            if weight > 0 and price > 0:
                total_weight += weight
                price_per_kg_usd = price  # Assume same price for all cargos in flight
                price_uzs = price * usd_rate
                total_payment += weight * price_uzs + extra_charge

            # Collect track codes if available
            if cargo.comment:
                track_codes.append(cargo.comment)

        if total_weight <= 0:
            return None

        return FlightPaymentSummary(
            total_weight=total_weight,
            price_per_kg_usd=price_per_kg_usd,
            price_per_kg_uzs=price_per_kg_usd * usd_rate,
            extra_charge=float(extra_charge),
            total_payment=total_payment,
            track_codes=track_codes
        )

    @staticmethod
    async def get_cargo_images_by_transaction_id(
        transaction_id: int,
        session: AsyncSession,
        cargo_type: Literal["unpaid"] = None
    ) -> TransactionCargoImagesResponse:
        """
        Get cargo images for a transaction (or direct cargo ID) with resolved Telegram URLs.
        """
        cargo = None
        # 1. Cargo obyektini topish
        if cargo_type == "unpaid":
            # Agar unpaid bo'lsa, transaction_id aslida cargo_id hisoblanadi
            cargo = await FlightCargoDAO.get_by_id(session, cargo_id=transaction_id)
        else:
            # Aks holda tranzaksiya orqali topamiz
            transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)
            if transaction:
                cargo = await FlightCargoDAO.get_flight_data_by_flight_name_client_code(
                    session, 
                    flight_name=transaction.reys or "", 
                    client_id=transaction.client_code
                )

        # 2. Agar Cargo topilmasa, bo'sh javob qaytaramiz
        if not cargo:
            return TransactionCargoImagesResponse(
                transaction_id=transaction_id,
                flight="Unknown",
                cargo_id=None,
                images=[],
                total_count=0
            )

        # 3. Rasmlarni qayta ishlash (Umumiy logika)
        file_ids = parse_photo_file_ids(cargo.photo_file_ids)
        resolved_images = []

        if file_ids:
            resolved_images = await resolve_telegram_file_urls(file_ids)

        # 4. Javobni shakllantirish
        images = [
            CargoImageSchema(
                file_id=img["file_id"],
                telegram_url=img["telegram_url"]
            )
            for img in resolved_images
        ]

        return TransactionCargoImagesResponse(
            transaction_id=transaction_id,
            flight=cargo.flight_name,
            cargo_id=cargo.id,
            images=images,
            total_count=len(images)
        )