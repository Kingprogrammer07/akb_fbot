"""Flight Cargo DAO for database operations."""

from datetime import datetime
import json
from sqlalchemy import select, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from decimal import Decimal

from src.infrastructure.database.models.flight_cargo import FlightCargo


class FlightCargoDAO:
    """Data Access Object for FlightCargo operations."""

    @staticmethod
    async def create(
        session: AsyncSession,
        flight_name: str,
        client_id: str,
        photo_file_ids: list[str],
        weight_kg: Optional[Decimal] = None,
        price_per_kg: Optional[Decimal] = None,
        comment: Optional[str] = None,
        is_sent_web: bool = False,
        is_sent_web_date: Optional[datetime] = None,
    ) -> FlightCargo:
        """
        Create a new flight cargo entry.

        Args:
            session: Database session
            flight_name: Flight/reys name (e.g., M123-2025)
            client_id: Client code (e.g., SS123)
            photo_file_ids: List of Telegram photo file IDs
            weight_kg: Weight in kilograms
            price_per_kg: Price per kilogram
            comment: Optional comment
            is_sent_web: Whether sent via web interface
            is_sent_web_date: Date/time when sent via web

        Returns:
            Created FlightCargo instance
        """
        cargo = FlightCargo(
            flight_name=flight_name.upper(),
            client_id=client_id.upper(),
            photo_file_ids=json.dumps(photo_file_ids),  # Serialize to JSON
            weight_kg=weight_kg,
            price_per_kg=price_per_kg,
            comment=comment,
            is_sent_web=is_sent_web,
            is_sent_web_date=is_sent_web_date,
        )
        session.add(cargo)
        await session.flush()
        await session.refresh(cargo)
        return cargo

    @staticmethod
    async def get_by_id(session: AsyncSession, cargo_id: int) -> Optional[FlightCargo]:
        """Get cargo by ID."""
        result = await session.execute(
            select(FlightCargo).where(FlightCargo.id == cargo_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_qator_raqami(
        session: AsyncSession, qator_raqami: int
    ) -> Optional[FlightCargo]:
        """Get cargo by qator raqami."""
        result = await session.execute(
            select(FlightCargo).where(FlightCargo.qator_raqami == qator_raqami)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_ids(session: AsyncSession, ids: list[int]):
        result = await session.execute(
            select(FlightCargo).where(FlightCargo.id.in_(ids))
        )
        return result.scalars().all()

    @staticmethod
    async def get_by_flight(
        session: AsyncSession,
        flight_name: str,
        limit: int = 1000,
        offset: int = 0,
        search: str | None = None,
    ) -> list[FlightCargo]:
        """
        Get cargo items for a specific flight, with optional client-ID search.

        Args:
            session:     Database session.
            flight_name: Flight name (case-insensitive; normalised to upper).
            limit:       Maximum number of results.
            offset:      Number of results to skip.
            search:      Optional partial match against ``client_id`` (case-insensitive).
                         Filters are applied BEFORE limit/offset so pagination
                         always reflects the filtered result set.

        Returns:
            List of FlightCargo instances ordered newest-first.
        """
        stmt = select(FlightCargo).where(FlightCargo.flight_name == flight_name.upper())

        if search:
            stmt = stmt.where(FlightCargo.client_id.ilike(f"%{search}%"))

        stmt = stmt.order_by(FlightCargo.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_client(
        session: AsyncSession,
        flight_name: str,
        client_id: str | list[str],
        limit: int = 100,
        offset: int = 0,
    ) -> list[FlightCargo]:
        """
        Get all cargo items for a specific client in a flight.

        Args:
            session: Database session
            flight_name: Flight name
            client_id: Client code or list of client codes
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of FlightCargo instances
        """
        if isinstance(client_id, list):
            client_ids_upper = [c.upper() for c in client_id if c]
            condition = func.upper(FlightCargo.client_id).in_(client_ids_upper)
        else:
            condition = func.upper(FlightCargo.client_id) == client_id.upper()

        result = await session.execute(
            select(FlightCargo)
            .where(
                func.upper(FlightCargo.flight_name) == flight_name.upper(), condition
            )
            .order_by(FlightCargo.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_registered_client_code(
        session: AsyncSession,
        flight_name: str,
        active_codes: list[str],
    ) -> str | None:
        """
        Returns the exact client_id stored in flight_cargos for this user + flight.

        This is the authoritative source for which code to use when creating a
        ClientTransaction. If a user has extra_code='STCH3' and client_code='SS9999',
        but their cargo was registered under 'SS9999', this method returns 'SS9999'.
        All transaction writes must use this value to stay consistent.

        Returns None when the user has no cargo in flight_cargos for this flight
        (e.g., legacy data or non-standard flows).
        """
        codes_upper = [c.upper() for c in active_codes if c]
        if not codes_upper:
            return None

        result = await session.execute(
            select(FlightCargo.client_id)
            .where(
                func.upper(FlightCargo.flight_name) == flight_name.upper(),
                func.upper(FlightCargo.client_id).in_(codes_upper),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_earliest_created_at(
        session: AsyncSession, flight_name: str, client_id: str, only_sent: bool = True
    ) -> datetime | None:
        """
        Get the earliest created_at date for a client's cargo in a flight.
        Used for calculating payment deadline (earliest cargo date + 15 days).

        Args:
            session: Database session
            flight_name: Flight name
            client_id: Client code
            only_sent: If True, only consider cargo where is_sent=True

        Returns:
            Earliest created_at datetime or None if no cargo found
        """
        query = select(func.min(FlightCargo.created_at)).where(
            FlightCargo.flight_name == flight_name.upper(),
            FlightCargo.client_id == client_id.upper(),
        )

        if only_sent:
            query = query.where(FlightCargo.is_sent == True)

        result = await session.execute(query)
        earliest = result.scalar_one_or_none()
        return earliest

    @staticmethod
    async def get_flight_data_by_flight_name_client_code(
        session: AsyncSession, flight_name: str, client_id: str, only_sent: bool = True
    ) -> datetime | None:
        """
        Get the transaction ID for a client's cargo in a flight.
        Used for calculating payment deadline (earliest cargo date + 15 days).

        Args:
            session: Database session
            flight_name: Flight name
            client_id: Client code
            only_sent: If True, only consider cargo where is_sent=True

        Returns:
            Earliest created_at datetime or None if no cargo found
        """
        result = await session.execute(
            select(FlightCargo).where(
                FlightCargo.client_id == client_id.upper(),
                FlightCargo.flight_name == flight_name.upper(),
                FlightCargo.is_sent == only_sent,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_by_client(
        session: AsyncSession,
        client_id: str | list[str],
        limit: int = 100,
        offset: int = 0,
    ) -> list[FlightCargo]:
        """
        Get all cargo items for a client across all flights.

        Args:
            session: Database session
            client_id: Client code or list of client codes
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of FlightCargo instances
        """
        if isinstance(client_id, list):
            client_ids_upper = [c.upper() for c in client_id if c]
            condition = func.upper(FlightCargo.client_id).in_(client_ids_upper)
        else:
            condition = func.upper(FlightCargo.client_id) == client_id.upper()

        result = await session.execute(
            select(FlightCargo)
            .where(condition)
            .order_by(FlightCargo.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_by_flight(
        session: AsyncSession,
        flight_name: str,
        search: str | None = None,
    ) -> int:
        """
        Count cargo items for a flight, applying the same search filter used
        by ``get_by_flight`` so that pagination totals stay consistent.
        """
        stmt = select(func.count(FlightCargo.id)).where(
            FlightCargo.flight_name == flight_name.upper()
        )
        if search:
            stmt = stmt.where(FlightCargo.client_id.ilike(f"%{search}%"))
        result = await session.execute(stmt)
        return result.scalar_one()

    @staticmethod
    async def count_unique_clients_by_flight(
        session: AsyncSession,
        flight_name: str,
        search: str | None = None,
    ) -> int:
        """
        Count unique clients in a flight, applying the same search filter used
        by ``get_by_flight`` so the ``unique_clients`` stat reflects the
        filtered result set when a search term is active.
        """
        stmt = select(func.count(func.distinct(FlightCargo.client_id))).where(
            FlightCargo.flight_name == flight_name.upper()
        )
        if search:
            stmt = stmt.where(FlightCargo.client_id.ilike(f"%{search}%"))
        result = await session.execute(stmt)
        return result.scalar_one()

    @staticmethod
    async def count_sent_by_flight(session: AsyncSession, flight_name: str) -> int:
        """Count all cargo items in a flight where is_sent=True (flight-wide, ignores pagination)."""
        result = await session.execute(
            select(func.count(FlightCargo.id)).where(
                FlightCargo.flight_name == flight_name.upper(),
                FlightCargo.is_sent == True,  # noqa: E712
            )
        )
        return result.scalar_one()

    @staticmethod
    async def count_unsent_by_flight(session: AsyncSession, flight_name: str) -> int:
        """Count all cargo items in a flight where is_sent=False (flight-wide, ignores pagination)."""
        result = await session.execute(
            select(func.count(FlightCargo.id)).where(
                FlightCargo.flight_name == flight_name.upper(),
                FlightCargo.is_sent == False,  # noqa: E712
            )
        )
        return result.scalar_one()

    @staticmethod
    async def delete_by_id(session: AsyncSession, cargo_id: int) -> bool:
        """
        Delete a cargo item by ID.

        Args:
            session: Database session
            cargo_id: Cargo ID

        Returns:
            True if deleted, False if not found
        """
        cargo = await FlightCargoDAO.get_by_id(session, cargo_id)
        if not cargo:
            return False

        await session.delete(cargo)
        await session.flush()
        return True

    @staticmethod
    async def delete_by_flight(session: AsyncSession, flight_name: str) -> int:
        """
        Delete all cargo items for a flight.

        Args:
            session: Database session
            flight_name: Flight name

        Returns:
            Number of deleted items
        """
        result = await session.execute(
            delete(FlightCargo).where(FlightCargo.flight_name == flight_name.upper())
        )
        await session.flush()
        return result.rowcount

    @staticmethod
    async def get_unsent_by_flight(
        session: AsyncSession, flight_name: str
    ) -> list[FlightCargo]:
        """
        Get all unsent cargo items for a flight (is_sent=False).

        Args:
            session: Database session
            flight_name: Flight name

        Returns:
            List of unsent FlightCargo objects
        """
        result = await session.execute(
            select(FlightCargo)
            .where(
                FlightCargo.flight_name == flight_name.upper(),
                FlightCargo.is_sent == False,
            )
            .order_by(FlightCargo.client_id, FlightCargo.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_unsent_web_by_flight(
        session: AsyncSession, flight_name: str
    ) -> list[FlightCargo]:
        """
        Get all cargo items not yet sent to web for a flight (is_sent_web=False).

        Args:
            session: Database session
            flight_name: Flight name

        Returns:
            List of FlightCargo objects not sent to web
        """
        result = await session.execute(
            select(FlightCargo)
            .where(
                FlightCargo.flight_name == flight_name.upper(),
                FlightCargo.is_sent_web == False,
            )
            .order_by(FlightCargo.client_id, FlightCargo.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def mark_as_sent(session: AsyncSession, cargo_ids: list[int]) -> int:
        """
        Mark multiple cargo items as sent (is_sent=True).

        Args:
            session: Database session
            cargo_ids: List of cargo IDs to mark as sent

        Returns:
            Number of updated rows
        """
        if not cargo_ids:
            return 0

        from sqlalchemy import text

        # Raw SQL ishlatiladi — ORM mapper is_sent_date ni taniy olmagan
        # serverlarda ham (migration apply qilinmagan bo'lsa) xavfsiz ishlaydi.
        # Ustun mavjud bo'lmasa faqat is_sent yangilanadi.
        try:
            result = await session.execute(
                text(
                    "UPDATE flight_cargos"
                    " SET is_sent = TRUE, is_sent_date = NOW()"
                    " WHERE id = ANY(:ids)"
                ),
                {"ids": cargo_ids},
            )
        except Exception:
            # is_sent_date ustuni mavjud bo'lmagan eski DB sxemalari uchun fallback
            result = await session.execute(
                text("UPDATE flight_cargos SET is_sent = TRUE WHERE id = ANY(:ids)"),
                {"ids": cargo_ids},
            )
        await session.flush()
        return result.rowcount

    @staticmethod
    async def mark_as_sent_web(session: AsyncSession, cargo_ids: list[int]) -> int:
        """
        Mark multiple cargo items as sent via web (is_sent_web=True).

        Sets is_sent_web=True and is_sent_web_date to the current timestamp.

        Args:
            session: Database session
            cargo_ids: List of cargo IDs to mark as sent via web

        Returns:
            Number of updated rows
        """
        if not cargo_ids:
            return 0

        result = await session.execute(
            update(FlightCargo)
            .where(FlightCargo.id.in_(cargo_ids))
            .values(is_sent_web=True, is_sent_web_date=datetime.now())
        )
        await session.flush()
        return result.rowcount

    @staticmethod
    async def get_sent_by_client(
        session: AsyncSession,
        client_id: str | list[str],
        flight_name: Optional[str] = None,
    ) -> list[FlightCargo]:
        """
        Get all sent cargo items for a client (is_sent=True).

        Args:
            session: Database session
            client_id: Client code or list of client codes (e.g., SS123)
            flight_name: Optional flight name filter

        Returns:
            List of sent FlightCargo objects
        """
        if isinstance(client_id, list):
            client_ids_upper = [c.upper() for c in client_id if c]
            client_condition = func.upper(FlightCargo.client_id).in_(client_ids_upper)
        else:
            client_condition = func.upper(FlightCargo.client_id) == client_id.upper()

        query = select(FlightCargo).where(client_condition, FlightCargo.is_sent == True)

        if flight_name:
            query = query.where(FlightCargo.flight_name == flight_name.upper())

        query = query.order_by(
            FlightCargo.flight_name.desc(), FlightCargo.created_at.desc()
        )

        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_export_data_by_flight(
        session: AsyncSession, flight_name: str
    ) -> list[dict]:
        """
        Get cargo data for Excel export (excludes photo_file_ids).

        Args:
            session: Database session
            flight_name: Flight name

        Returns:
            List of dictionaries with export-ready data
        """
        result = await session.execute(
            select(
                FlightCargo.id,
                FlightCargo.flight_name,
                FlightCargo.client_id,
                FlightCargo.weight_kg,
                FlightCargo.price_per_kg,
                FlightCargo.comment,
                FlightCargo.is_sent,
                FlightCargo.is_sent_web,
                FlightCargo.is_sent_web_date,
                FlightCargo.created_at,
                FlightCargo.updated_at,
            )
            .where(FlightCargo.flight_name == flight_name.upper())
            .order_by(FlightCargo.client_id, FlightCargo.created_at.desc())
        )
        rows = result.all()
        return [
            {
                "id": row.id,
                "flight_name": row.flight_name,
                "client_id": row.client_id,
                "weight_kg": float(row.weight_kg) if row.weight_kg else None,
                "price_per_kg": float(row.price_per_kg) if row.price_per_kg else None,
                "comment": row.comment,
                "is_sent": row.is_sent,
                "is_sent_web": row.is_sent_web,
                "is_sent_web_date": row.is_sent_web_date,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]

    @staticmethod
    async def get_unique_flights_by_client_sent(
        session: AsyncSession, client_id: str | list[str]
    ) -> list[str]:
        """
        Get unique flight names for a client's sent cargos.

        Args:
            session: Database session
            client_id: Client code or list of client codes

        Returns:
            List of unique flight names (sorted descending)
        """
        if isinstance(client_id, list):
            client_ids_upper = [c.upper() for c in client_id if c]
            client_condition = func.upper(FlightCargo.client_id).in_(client_ids_upper)
        else:
            client_condition = func.upper(FlightCargo.client_id) == client_id.upper()

        result = await session.execute(
            select(FlightCargo.flight_name)
            .where(client_condition, FlightCargo.is_sent == True)
            .distinct()
            .order_by(FlightCargo.flight_name.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_unique_flights_by_client_web(
        session: AsyncSession,
        client_id: str | list[str],
        limit: int = 10,
        offset: int = 0,
    ) -> list[str]:
        """
        Get unique flight names for a client where is_sent_web=True.

        Args:
            session: Database session
            client_id: Client code or list of client codes
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of unique flight names (sorted descending)
        """
        if isinstance(client_id, list):
            client_ids_upper = [c.upper() for c in client_id if c]
            client_condition = func.upper(FlightCargo.client_id).in_(client_ids_upper)
        else:
            client_condition = func.upper(FlightCargo.client_id) == client_id.upper()

        result = await session.execute(
            select(FlightCargo.flight_name)
            .where(client_condition, FlightCargo.is_sent_web == True)
            .distinct()
            .order_by(FlightCargo.flight_name.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_distinct_recent_flights(
        session: AsyncSession,
        limit: int = 40,
    ) -> list[str]:
        """
        Return distinct flight names ordered by the most-recently-added cargo first.

        Used by the flight-notify handler to populate the paginated flight-selection
        keyboard.  Sources from flight_cargos (not expected_flight_cargos) because
        that is the canonical set of processed flights with known client manifests.

        Args:
            session: Open async DB session.
            limit:   Maximum number of distinct flight names to return.

        Returns:
            List of flight name strings, newest-first.
        """
        result = await session.execute(
            select(FlightCargo.flight_name)
            .group_by(FlightCargo.flight_name)
            .order_by(func.max(FlightCargo.created_at).desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_distinct_client_ids_by_flight(
        session: AsyncSession,
        flight_name: str,
    ) -> list[str]:
        """
        Return all distinct ``client_id`` values present in a given flight.

        Note: the column is named ``client_id`` on the ORM model (it stores the
        client code string, e.g. "SS123").  All values are already stored in
        upper-case via the model's ``__init__`` normalisation.

        Args:
            session:     Open async DB session.
            flight_name: Flight name (case-insensitive; normalised internally).

        Returns:
            Alphabetically ordered list of distinct client-code strings.
        """
        result = await session.execute(
            select(func.distinct(FlightCargo.client_id))
            .where(FlightCargo.flight_name == flight_name.upper())
            .order_by(FlightCargo.client_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_web_reports_by_client(
        session: AsyncSession,
        client_id: str | list[str],
        limit: int = 10,
        offset: int = 0,
        flight_name: Optional[str] = None,
    ) -> list[FlightCargo]:
        """
        Get FlightCargo records where is_sent_web=True for a client.

        Args:
            session: Database session
            client_id: Client code or list of client codes
            limit: Maximum number of results
            offset: Number of results to skip
            flight_name: Optional flight name filter

        Returns:
            List of FlightCargo instances ordered by is_sent_web_date desc
        """
        if isinstance(client_id, list):
            client_ids_upper = [c.upper() for c in client_id if c]
            client_condition = func.upper(FlightCargo.client_id).in_(client_ids_upper)
        else:
            client_condition = func.upper(FlightCargo.client_id) == client_id.upper()

        query = select(FlightCargo).where(
            client_condition, FlightCargo.is_sent_web == True
        )

        if flight_name:
            query = query.where(
                func.upper(FlightCargo.flight_name) == flight_name.upper()
            )

        query = query.order_by(FlightCargo.is_sent_web_date.desc())
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        return list(result.scalars().all())
