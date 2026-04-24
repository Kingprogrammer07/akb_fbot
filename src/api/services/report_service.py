"""Report Service - Business logic for web report history with track code and payment enrichment."""
import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import config
from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
from src.infrastructure.database.dao.cargo_item import CargoItemDAO
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.expected_cargo import ExpectedFlightCargoDAO
from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.api.services.verification.utils import (
    get_usd_rate,
    get_extra_charge,
    parse_photo_file_ids,
)
from src.infrastructure.tools.s3_manager import s3_manager

logger = logging.getLogger(__name__)


class ReportService:
    """Service for fetching web report history with hybrid track code and payment resolution."""

    def __init__(self):
        self.sheets_checker = GoogleSheetsChecker(
            spreadsheet_id=config.google_sheets.SHEETS_ID,
            api_key=config.google_sheets.API_KEY
        )

    async def get_client_flights(
        self,
        session: AsyncSession,
        client_code: str,
        page: int = 1,
        size: int = 10
    ) -> list[str]:
        """
        Get paginated unique flight names where is_sent_web=True.

        Args:
            session: Database session
            client_code: Client code
            page: Page number (1-based)
            size: Page size

        Returns:
            List of flight name strings
        """
        offset = (page - 1) * size
        return await FlightCargoDAO.get_unique_flights_by_client_web(
            session, client_code, limit=size, offset=offset
        )

    async def get_client_history(
        self,
        session: AsyncSession,
        client_code: str,
        page: int = 1,
        flight_name: str | None = None,
        size: int = 10,
    ) -> list[dict]:
        """
        Get paginated web report history with enriched track codes and payment status.

        For each FlightCargo record (is_sent_web=True):
        1. Resolve track codes (Sheets -> DB -> fallback)
        2. Resolve payment status from ClientTransaction
        3. Calculate financials using current USD rate + extra charge

        Args:
            session: Database session
            client_code: Client code
            page: Page number (1-based)
            flight_name: Optional flight name filter
            size: Page size

        Returns:
            List of report dicts ready for ReportResponse serialization
        """
        offset = (page - 1) * size
        records = await FlightCargoDAO.get_web_reports_by_client(
            session, client_code, limit=size, offset=offset,
            flight_name=flight_name
        )

        if not records:
            return []

        # Pre-fetch rates once (not per record)
        usd_rate = await get_usd_rate(session)
        extra_charge = await get_extra_charge(session)

        # Process all records concurrently
        tasks = [
            self._enrich_record(session, record, client_code, usd_rate, extra_charge)
            for record in records
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_record(
        self,
        session: AsyncSession,
        record,
        client_code: str,
        usd_rate: float,
        extra_charge: float
    ) -> dict:
        """
        Enrich a single FlightCargo record with track codes, payment, and financials.

        Args:
            session: Database session
            record: FlightCargo ORM instance
            client_code: Client code
            usd_rate: Current USD to UZS rate
            extra_charge: Extra charge from static data

        Returns:
            Dict ready for ReportResponse serialization
        """
        # Resolve track codes and payment in parallel
        tracks_task = self._get_tracks(session, record.flight_name, client_code)
        payment_task = self._get_payment_info(session, client_code, record.flight_name)

        tracks, payment_info = await asyncio.gather(tracks_task, payment_task)

        # 1. Base calculations for pure informational fallback
        weight = float(record.weight_kg) if record.weight_kg else 0.0
        price_per_kg = float(record.price_per_kg) if record.price_per_kg else 0.0

        total_price_usd = round(weight * price_per_kg, 2)
        price_per_kg_uzs = price_per_kg * usd_rate
        calculated_total_uzs = round((weight * price_per_kg_uzs) + extra_charge, 2)

        # 2. STRICT DB Priority: Stop recalculating if DB has the truth
        if payment_info["exists"]:
            expected_amount = payment_info["total_amount"]
            paid_amount = payment_info["paid_amount"]
            display_total_uzs = payment_info["total_amount"]
        else:
            expected_amount = calculated_total_uzs
            paid_amount = 0.0
            display_total_uzs = calculated_total_uzs

        # Parse photo_file_ids from JSON string
        raw_photo_ids = parse_photo_file_ids(record.photo_file_ids)
        photo_ids = []

        for pid in raw_photo_ids:
            # Simple heuristic to distinguish S3 keys from Telegram file_ids
            if "/" in pid or "." in pid:
                url = await s3_manager.generate_presigned_url(pid)
                # If URL generation succeeds, use it. Otherwise fallback to raw key.
                photo_ids.append(url if url else pid)
            else:
                # Keep Telegram file_ids raw; frontend will resolve them via API
                photo_ids.append(pid)

        return {
            "flight_name": record.flight_name,
            "total_weight": weight,
            "total_price_usd": total_price_usd,
            "total_price_uzs": display_total_uzs,
            "is_sent_web_date": record.is_sent_web_date,
            "photo_file_ids": photo_ids,  # Now contains presigned URLs for S3 images!
            "track_codes": tracks,
            # Strict DB matching
            "payment_status": payment_info["payment_status"],
            "paid_amount": paid_amount,
            "expected_amount": expected_amount,
            "payment_date": payment_info["payment_date"],
        }

    async def _get_tracks(
        self,
        session: AsyncSession,
        flight_name: str,
        client_code: str
    ) -> list[str]:
        """
        Resolve track codes: Google Sheets first, DB fallback, then default.

        Args:
            session: Database session
            flight_name: Flight name
            client_code: Client code

        Returns:
            List of track code strings (never empty — returns ["Yo'q"] as last resort)
        """
        # 1. Try Google Sheets
        try:
            tracks = await self.sheets_checker.get_track_codes_by_flight_and_client(
                flight_name, client_code
            )
            if tracks:
                return tracks
        except Exception as e:
            logger.warning(f"Sheets lookup failed for {flight_name}/{client_code}: {e}")

        # 2. Fallback to CargoItemDAO
        db_tracks = await CargoItemDAO.get_track_codes_by_flight_and_client(
            session, flight_name, client_code
        )
        if db_tracks:
            return db_tracks

        # 3. Fallback to expected_flight_cargos (DB-sourced pre-arrival manifest)
        try:
            expected_tracks = await ExpectedFlightCargoDAO.get_track_codes_by_flight_and_client(
                session, flight_name, client_code
            )
            if expected_tracks:
                return expected_tracks
        except Exception as e:
            logger.warning(
                "Expected cargo track lookup failed for %s/%s: %s",
                flight_name, client_code, e
            )

        # 4. No tracks found at all
        return ["Yo'q"]

    @staticmethod
    async def _get_payment_info(
        session: AsyncSession,
        client_code: str,
        flight_name: str
    ) -> dict:
        """
        Resolve payment information from ClientTransaction.

        Args:
            session: Database session
            client_code: Client code
            flight_name: Flight name

        Returns:
            Dict with payment_status, paid_amount, remaining_amount, total_amount, payment_date, exists
        """
        transaction = await ClientTransactionDAO.get_by_client_code_flight(
            session, client_code, flight_name
        )

        if transaction:
            paid = float(transaction.paid_amount) if transaction.paid_amount is not None else 0.0
            remaining = float(transaction.remaining_amount) if transaction.remaining_amount is not None else 0.0
            # Fallback to paid + remaining if total_amount is somehow null
            total = float(transaction.total_amount) if transaction.total_amount is not None else (paid + remaining)

            return {
                "payment_status": transaction.payment_status or "paid",
                "paid_amount": paid,
                "remaining_amount": remaining,
                "total_amount": total,
                "payment_date": transaction.created_at,
                "exists": True,
            }

        return {
            "payment_status": "unpaid",
            "paid_amount": 0.0,
            "remaining_amount": 0.0,
            "total_amount": None,
            "payment_date": None,
            "exists": False,
        }
