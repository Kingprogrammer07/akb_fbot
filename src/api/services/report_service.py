"""Report Service - Business logic for web report history with track code and payment enrichment."""
import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import config
from src.infrastructure.database.dao.client import ClientDAO
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
from src.infrastructure.services.flight_display import (
    FlightDisplay,
    resolve_partner_for_codes,
)
from src.infrastructure.services.flight_mask import FlightMaskService
from src.infrastructure.tools.s3_manager import s3_manager

logger = logging.getLogger(__name__)


class ReportService:
    """Service for fetching web report history with hybrid track code and payment resolution."""

    def __init__(self):
        self.sheets_checker = GoogleSheetsChecker(
            spreadsheet_id=config.google_sheets.SHEETS_ID,
            api_key=config.google_sheets.API_KEY
        )

    async def _resolve_codes(
        self, session: AsyncSession, client_code: str
    ) -> list[str]:
        """Return every code variant that maps to the same client.

        ``flight_cargos.client_id`` was written under whatever code the
        scan tooling knew at the time (legacy ``AKB570`` or pre-Phase-4e
        ``AKB01-2/14``).  After Phase 4e conversion the URL caller uses
        the new short form (``A02-14``) which would not match the
        archived rows by string equality.  Looking up the client and
        returning ``active_codes`` lets the downstream DAO filter on the
        full set of aliases.
        """
        primary = (client_code or "").strip().upper()
        if not primary:
            return []
        client = await ClientDAO.get_by_client_code(session, primary)
        if not client:
            return [primary]
        codes = list(dict.fromkeys(c.upper() for c in client.active_codes if c))
        if primary not in codes:
            codes.append(primary)
        return codes

    async def get_client_flights(
        self,
        session: AsyncSession,
        client_code: str,
        page: int = 1,
        size: int = 10
    ) -> list[str]:
        """
        Get paginated unique flight names where is_sent_web=True.

        Each real flight name is replaced with the partner-specific mask
        before returning so the user only ever sees their alias.
        """
        offset = (page - 1) * size
        codes = await self._resolve_codes(session, client_code)
        real_flights = await FlightCargoDAO.get_unique_flights_by_client_web(
            session, codes, limit=size, offset=offset
        )
        return await self._mask_flights(session, client_code, real_flights)

    async def _resolve_partner(self, session: AsyncSession, client_code: str):
        """Best-effort partner lookup for masking; returns ``None`` on miss."""
        client = await ClientDAO.get_by_client_code(session, client_code)
        return await resolve_partner_for_codes(
            session, client.active_codes if client else client_code
        )

    async def _mask_flights(
        self,
        session: AsyncSession,
        client_code: str,
        real_flights: list[str],
    ) -> list[str]:
        """Translate each real flight name to its partner-specific mask.

        A flight with no resolvable mask degrades to an ordinal placeholder
        rather than to the real name.
        """
        if not real_flights:
            return real_flights
        display = FlightDisplay(await self._resolve_partner(session, client_code))
        return [
            await display.label(session, real, ordinal=i)
            for i, real in enumerate(real_flights, start=1)
        ]

    async def _normalize_flight_input(
        self, session: AsyncSession, client_code: str, flight_query: str | None
    ) -> str | None:
        """Translate a possibly-masked flight name to its real value for DB lookup."""
        if not flight_query:
            return None
        partner = await self._resolve_partner(session, client_code)
        if partner is None:
            return flight_query
        return await FlightMaskService.normalize_flight_input(
            session, partner.id, flight_query
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

        # Caller may pass either the real flight name or the partner mask.
        # Normalise to real before hitting the DAO so cargo rows are found.
        real_flight_filter = await self._normalize_flight_input(
            session, client_code, flight_name
        )

        # Resolve to every code variant the client has so older
        # flight_cargos rows (written under the pre-Phase-4e code) still
        # match the URL's new short code.
        codes = await self._resolve_codes(session, client_code)
        records = await FlightCargoDAO.get_web_reports_by_client(
            session, codes, limit=size, offset=offset,
            flight_name=real_flight_filter
        )

        if not records:
            return []

        # Pre-fetch rates once (not per record)
        usd_rate = await get_usd_rate(session)
        extra_charge = await get_extra_charge(session)

        # Process all records concurrently
        tasks = [
            self._enrich_record(session, record, client_code, codes, usd_rate, extra_charge)
            for record in records
        ]
        enriched = await asyncio.gather(*tasks)

        # Replace real flight names with masks before returning to the API.
        # No mask -> placeholder; the real name never reaches the response.
        display = FlightDisplay(await self._resolve_partner(session, client_code))
        for item in enriched:
            if not item.get("flight_name"):
                continue
            item["flight_name"] = await display.label(session, item["flight_name"])
        return enriched

    async def _enrich_record(
        self,
        session: AsyncSession,
        record,
        client_code: str,
        active_codes: list[str],
        usd_rate: float,
        extra_charge: float
    ) -> dict:
        """
        Enrich a single FlightCargo record with track codes, payment, and financials.

        ``client_code`` is the URL identifier (used for sheets / display);
        ``active_codes`` is the full list of historical aliases used for
        DB lookups so legacy flight_cargos rows are not missed.
        """
        # Resolve track codes and payment in parallel
        tracks_task = self._get_tracks(session, record.flight_name, active_codes)
        payment_task = self._get_payment_info(session, active_codes, record.flight_name)

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
        active_codes: list[str] | str
    ) -> list[str]:
        """
        Resolve track codes across every alias the client owns.  Sheets
        is queried with the full alias list (it accepts ``list[str]``);
        DB DAOs are iterated per-code and the union returned.
        """
        raw_codes = [active_codes] if isinstance(active_codes, str) else list(active_codes)
        codes: list[str] = []
        for c in raw_codes:
            if isinstance(c, list):
                codes.extend([str(item) for item in c if item])
            elif c:
                codes.append(str(c))
                
        if not codes:
            return ["Yo'q"]

        # 1. Try Google Sheets first — it already accepts a list of codes.
        try:
            tracks = await self.sheets_checker.get_track_codes_by_flight_and_client(
                flight_name, codes
            )
            if tracks:
                return tracks
        except Exception as e:
            logger.warning(f"Sheets lookup failed for {flight_name}/{codes}: {e}")

        # 2. Fallback to CargoItemDAO — single-code API, so iterate aliases.
        for code in codes:
            db_tracks = await CargoItemDAO.get_track_codes_by_flight_and_client(
                session, flight_name, code
            )
            if db_tracks:
                return db_tracks

        # 3. Fallback to expected_flight_cargos (already accepts a list).
        try:
            expected_tracks = await ExpectedFlightCargoDAO.get_track_codes_by_flight_and_client(
                session, flight_name, codes
            )
            if expected_tracks:
                return expected_tracks
        except Exception as e:
            logger.warning(
                "Expected cargo track lookup failed for %s/%s: %s",
                flight_name, codes, e,
            )

        # 4. No tracks found at all
        return ["Yo'q"]

    @staticmethod
    async def _get_payment_info(
        session: AsyncSession,
        client_code: list[str] | str,
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
