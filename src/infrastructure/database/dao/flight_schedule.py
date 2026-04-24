"""DAO for FlightSchedule — manager-maintained flight calendar queries.

All methods are pure async SQLAlchemy operations; zero business logic lives here.
"""
import logging
from datetime import date

from sqlalchemy import extract, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.flight_schedule import FlightSchedule

logger = logging.getLogger(__name__)


class FlightScheduleDAO:
    """Data Access Object for the flight_schedules table."""

    @staticmethod
    async def get_by_year(
        session: AsyncSession,
        year: int,
    ) -> list[FlightSchedule]:
        """
        Return all schedule entries for a given calendar year, ordered by date ascending.

        Args:
            session: Open async DB session.
            year:    Four-digit calendar year (e.g. 2025).

        Returns:
            Ordered list of FlightSchedule records for that year.
        """
        result = await session.execute(
            select(FlightSchedule)
            .where(extract("year", FlightSchedule.flight_date) == year)
            .order_by(FlightSchedule.flight_date.asc(), FlightSchedule.flight_name.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        schedule_id: int,
    ) -> FlightSchedule | None:
        """Fetch a single schedule entry by primary key."""
        result = await session.execute(
            select(FlightSchedule).where(FlightSchedule.id == schedule_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        flight_name: str,
        flight_date: date,
        type_: str,
        status: str,
        notes: str | None,
    ) -> FlightSchedule:
        """
        Insert a new flight schedule entry.

        Args:
            session:     Open async DB session (caller must commit).
            flight_name: Shipment batch name.
            flight_date: Planned date.
            type_:       'avia' or 'aksiya'.
            status:      'scheduled', 'delayed', or 'arrived'.
            notes:       Optional free-form manager notes.

        Returns:
            The freshly inserted FlightSchedule ORM object.
        """
        entry = FlightSchedule(
            flight_name=flight_name.strip(),
            flight_date=flight_date,
            type=type_,
            status=status,
            notes=notes,
        )
        session.add(entry)
        await session.flush()
        await session.refresh(entry)
        logger.debug("flight_schedule.create: id=%d flight=%r", entry.id, entry.flight_name)
        return entry

    @staticmethod
    async def update(
        session: AsyncSession,
        entry: FlightSchedule,
        flight_name: str | None,
        flight_date: date | None,
        type_: str | None,
        status: str | None,
        notes: str | None,
    ) -> FlightSchedule:
        """
        Apply a partial update to an existing entry.

        Only non-None fields are written so callers can send sparse PATCH-style
        payloads without accidentally clearing untouched columns.

        Args:
            session:     Open async DB session (caller must commit).
            entry:       The loaded ORM object to mutate.
            flight_name: New name, or None to leave unchanged.
            flight_date: New date, or None to leave unchanged.
            type_:       New type, or None to leave unchanged.
            status:      New status, or None to leave unchanged.
            notes:       New notes, or None to leave unchanged.  Pass an empty
                         string ``""`` to explicitly clear notes.

        Returns:
            The mutated (unflushed) FlightSchedule object.
        """
        if flight_name is not None:
            entry.flight_name = flight_name.strip()
        if flight_date is not None:
            entry.flight_date = flight_date
        if type_ is not None:
            entry.type = type_
        if status is not None:
            entry.status = status
        if notes is not None:
            entry.notes = notes or None
        await session.flush()
        await session.refresh(entry)
        return entry

    @staticmethod
    async def delete(
        session: AsyncSession,
        entry: FlightSchedule,
    ) -> None:
        """
        Delete a schedule entry.

        Args:
            session: Open async DB session (caller must commit).
            entry:   The loaded ORM object to remove.
        """
        await session.delete(entry)
        await session.flush()
        logger.debug("flight_schedule.delete: id=%d", entry.id)
