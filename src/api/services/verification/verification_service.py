"""Verification service for client search and info retrieval."""

import json
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.verification import (
    BalanceStatus,
    ClientFullInfo,
    ClientSearchResult,
    ClientStats,
    FlightListResponse,
    FlightMatch,
)
from src.api.services.verification.transaction_view_service import TransactionViewService
from src.bot.bot_instance import bot
from src.bot.handlers.user.delivery_request import UZBEKISTAN_REGIONS
from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.config import BASE_DIR, config
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
from src.infrastructure.services.client import ClientService


class VerificationService:
    """Service for client verification operations."""

    @staticmethod
    def is_admin(client, admin_ids: list[int]) -> bool:
        """
        Check if client is an admin.

        Admin is identified by:
        1. clients.role in ['admin', 'super-admin']
        2. telegram_id in config.telegram.admin_ids
        """
        if client.role in ["admin", "super-admin"]:
            return True
        if client.telegram_id and client.telegram_id in admin_ids:
            return True
        return False

    @staticmethod
    async def calculate_client_balance(
        client_code: str | list[str],
        session: AsyncSession,
    ) -> tuple[float, BalanceStatus]:
        """
        Calculate the true net wallet balance for a client.

        Delegates to get_wallet_balances() - the same source of truth used by
        GET /wallet/balance - so the figure shown in the admin panel is always
        consistent with what the client sees in their own wallet view.
        """
        balances = await ClientTransactionDAO.get_wallet_balances(session, client_code)
        net_balance = balances["wallet_balance"] + balances["debt"]

        if net_balance < 0:
            balance_status: BalanceStatus = "debt"
        elif net_balance > 0:
            balance_status = "overpaid"
        else:
            balance_status = "balanced"

        return net_balance, balance_status

    @staticmethod
    async def search_client(
        query: str,
        session: AsyncSession,
    ) -> Optional[ClientSearchResult]:
        """Search for a client by code or phone number."""
        query = query.strip()
        digits_only = "".join(c for c in query if c.isdigit())
        is_phone_query = len(digits_only) >= 7

        client = None
        if is_phone_query:
            client = await ClientDAO.search_by_client_code_or_phone(session, query)
        else:
            client_service = ClientService()
            client = await client_service.get_client_by_code(query.upper(), session)
        if not client:
            return None

        canonical_code = client.primary_code
        active_codes = client.active_codes

        total_payments = await ClientTransactionDAO.count_by_client_code(
            session,
            active_codes,
        )
        taken_away_count = await ClientTransactionDAO.count_taken_away_by_client_code(
            session,
            active_codes,
        )

        db_flights = await ClientTransactionDAO.get_unique_flights_by_client_code(
            session,
            active_codes,
        )
        sheets_flights = await VerificationService._get_sheets_flights(canonical_code)
        all_flights = list(set(db_flights + sheets_flights))
        all_flights.sort(reverse=True)

        admin_ids = (
            config.telegram.admin_ids if hasattr(config.telegram, "admin_ids") else []
        )
        is_admin = VerificationService.is_admin(client, admin_ids)

        client_balance, client_balance_status = (
            await VerificationService.calculate_client_balance(active_codes, session)
        )

        return ClientSearchResult(
            id=client.id,
            client_code=canonical_code,
            full_name=client.full_name,
            telegram_id=client.telegram_id,
            phone=client.phone,
            is_admin=is_admin,
            stats=ClientStats(
                total_payments=total_payments,
                cargo_taken=taken_away_count,
            ),
            flights=all_flights,
            client_balance=client_balance,
            client_balance_status=client_balance_status,
        )

    @staticmethod
    async def get_client_full_info(
        client_code: str,
        session: AsyncSession,
    ) -> Optional[ClientFullInfo]:
        """
        Get full client information by client code.

        Looks up the client by searching all code columns (extra_code, client_code,
        legacy_code) and uses the resolved primary_code for all downstream queries.
        """
        client_service = ClientService()
        client = await client_service.get_client_by_code(client_code, session)
        if not client:
            return None

        canonical_code = client.primary_code
        active_codes = client.active_codes

        transaction_count = await ClientTransactionDAO.count_by_client_code(
            session,
            active_codes,
        )
        latest_tx = await ClientTransactionDAO.get_latest_by_client_code(
            session,
            active_codes,
        )

        latest_transaction = None
        if latest_tx:
            status_context = await TransactionViewService.get_status_context(
                session,
                latest_tx,
                active_codes,
            )
            latest_transaction = TransactionViewService.build_transaction_summary(
                latest_tx,
                status_context,
            )

        extra_passports_count = await client_service.count_extra_passports_by_client_code(
            canonical_code,
            session,
        )
        referral_count = await client_service.count_referrals_by_client_code(
            canonical_code,
            session,
        )

        passport_image_file_ids = []
        if client.passport_images:
            try:
                file_ids = json.loads(client.passport_images)
                if not isinstance(file_ids, list):
                    file_ids = [file_ids]

                from src.infrastructure.tools.passport_image_resolver import (
                    resolve_passport_items,
                )

                passport_image_file_ids = await resolve_passport_items(file_ids)
            except (json.JSONDecodeError, TypeError) as exc:
                import logging

                logger = logging.getLogger(__name__)
                logger.error(
                    "Failed to parse passport_images JSON for client_id=%s: %s",
                    client.id,
                    exc,
                    exc_info=True,
                )
                passport_image_file_ids = []

        admin_ids = (
            config.telegram.admin_ids if hasattr(config.telegram, "admin_ids") else []
        )
        is_admin = VerificationService.is_admin(client, admin_ids)
        client_balance, client_balance_status = (
            await VerificationService.calculate_client_balance(active_codes, session)
        )

        if client.language_code == "ru":
            district_file = BASE_DIR / "locales" / "district_ru.json"
            with open(district_file, "r", encoding="utf-8") as handle:
                district_map = json.load(handle).get("districts", {}).get(client.region, {})
        else:
            district_file = BASE_DIR / "locales" / "district_uz.json"
            with open(district_file, "r", encoding="utf-8") as handle:
                district_map = json.load(handle).get("districts", {}).get(client.region, {})

        district_name = district_map.get(client.district, client.district)
        full_address = f"{district_name}, {client.address}"

        return ClientFullInfo(
            id=client.id,
            client_code=canonical_code,
            full_name=client.full_name,
            telegram_id=client.telegram_id,
            phone=client.phone,
            passport_series=client.passport_series,
            pinfl=client.pinfl,
            date_of_birth=client.date_of_birth,
            region=UZBEKISTAN_REGIONS.get(client.region, client.region)
            if client.region
            else None,
            district=client.district,
            address=full_address or None,
            is_admin=is_admin,
            referral_count=referral_count,
            extra_passports_count=extra_passports_count,
            passport_image_file_ids=passport_image_file_ids,
            created_at=client.created_at,
            transaction_count=transaction_count,
            latest_transaction=latest_transaction,
            client_balance=client_balance,
            client_balance_status=client_balance_status,
        )

    @staticmethod
    async def get_client_flights(
        client_code: str,
        session: AsyncSession,
        include_sheets: bool,
        include_database: bool,
    ) -> FlightListResponse:
        """Get all flights for a client."""
        client_service = ClientService()
        client = await client_service.get_client_by_code(client_code, session)
        active_codes = client.active_codes if client else [client_code.upper()]
        canonical_code = client.primary_code if client else client_code.upper()

        db_flights: list[str] = []
        cargo_flights: list[str] = []
        sheets_flights: list[str] = []

        if include_database:
            db_flights = await ClientTransactionDAO.get_unique_flights_by_client_code(
                session,
                active_codes,
            )
            cargo_flights = await FlightCargoDAO.get_unique_flights_by_client_sent(
                session,
                active_codes,
            )

        if include_sheets:
            sheets_flights = await VerificationService._get_sheets_flights(canonical_code)

        all_flights = list(set(db_flights + cargo_flights + sheets_flights))
        all_flights.sort(reverse=True)

        if include_sheets and include_database:
            source = "combined"
        elif include_sheets:
            source = "sheets"
        else:
            source = "database"

        return FlightListResponse(flights=all_flights, source=source)

    @staticmethod
    async def _get_sheets_flights(client_code: str) -> list[str]:
        """Get flights from Google Sheets for a client."""
        sheets_flights: list[str] = []
        try:
            checker = GoogleSheetsChecker(
                spreadsheet_id=config.google.SPREADSHEET_ID,
                api_key=config.google.API_KEY,
            )
            result = await checker.find_client_group(client_code, reverse=True)

            if result.get("found") and result.get("matches"):
                for match in result["matches"]:
                    flight_name = match.get("flight_name", "")
                    if flight_name and flight_name not in sheets_flights:
                        sheets_flights.append(flight_name)
        except Exception:
            pass

        return sheets_flights

    @staticmethod
    async def get_sheets_matches(client_code: str) -> list[FlightMatch]:
        """Get detailed flight matches from Google Sheets."""
        matches: list[FlightMatch] = []
        try:
            checker = GoogleSheetsChecker(
                spreadsheet_id=config.google.SPREADSHEET_ID,
                api_key=config.google.API_KEY,
            )
            result = await checker.find_client_group(client_code, reverse=True)

            if result.get("found") and result.get("matches"):
                for match in result["matches"]:
                    matches.append(
                        FlightMatch(
                            flight_name=match.get("flight_name", ""),
                            row_number=match.get("row_number", 0),
                            client_code=match.get("client_code", client_code),
                            track_codes=match.get("track_codes", []),
                        )
                    )
        except Exception:
            pass

        return matches
