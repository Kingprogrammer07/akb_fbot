"""DAO for ExpectedFlightCargo — pre-arrival cargo manifest queries.

All methods are pure async SQLAlchemy operations; zero business logic lives
here.  Each method receives an open AsyncSession and returns ORM objects or
scalar values as documented.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, distinct, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.expected_cargo import ExpectedFlightCargo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Small value objects returned by write operations (avoid bare tuple returns)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SummaryStats:
    """Aggregate totals for the entire expected_flight_cargos table."""

    total_records: int
    total_unique_flights: int
    total_unique_clients: int


@dataclass(frozen=True)
class FlightStat:
    """Per-flight aggregated statistics row."""

    flight_name: str
    client_count: int
    track_code_count: int


@dataclass(frozen=True)
class ClientStat:
    """Per-client aggregated statistics row."""

    client_code: str
    flight_count: int
    track_code_count: int


@dataclass(frozen=True)
class BulkCreateResult:
    """Result of a bulk-insert operation."""

    created_count: int
    duplicate_track_codes: list[str]


@dataclass(frozen=True)
class ReplaceResult:
    """Result of a replace-all operation for one flight+client."""

    deleted_count: int
    created_count: int


# ---------------------------------------------------------------------------
# DAO
# ---------------------------------------------------------------------------


class ExpectedFlightCargoDAO:
    """Data Access Object for the expected_flight_cargos table."""

    # -------------------------------------------------------------------
    # Read operations
    # -------------------------------------------------------------------

    @staticmethod
    async def paginated_search(
        session: AsyncSession,
        page: int,
        size: int,
        flight_name: str | None = None,
        client_code: str | None = None,
        track_code: str | None = None,
    ) -> tuple[list[ExpectedFlightCargo], int]:
        """
        Return a paginated, optionally-filtered list of expected cargo records.

        Filter logic:
          • If flight_name is provided → primary filter is flight; client_code
            and track_code act as secondary refinements within that flight.
          • If flight_name is NOT provided → global search by client_code
            and/or track_code across all flights.

        Args:
            session:     Open async DB session.
            page:        1-based page number.
            size:        Number of records per page.
            flight_name: Optional exact flight name filter.
            client_code: Optional exact client code filter.
            track_code:  Optional partial track code filter (case-insensitive).

        Returns:
            Tuple of (records for current page, total matching count).
        """
        # Placeholder rows are sentinels for empty-flight registration; they
        # must never surface through the search endpoint.
        conditions: list = [ExpectedFlightCargo.is_placeholder == False]  # noqa: E712

        if flight_name:
            conditions.append(
                func.lower(ExpectedFlightCargo.flight_name) == flight_name.strip().lower()
            )
        if client_code:
            conditions.append(
                func.lower(ExpectedFlightCargo.client_code) == client_code.strip().lower()
            )
        if track_code:
            conditions.append(
                ExpectedFlightCargo.track_code.ilike(f"%{track_code.strip()}%")
            )

        base_query = select(ExpectedFlightCargo).where(*conditions)

        count_result = await session.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total: int = count_result.scalar_one()

        records_result = await session.execute(
            base_query
            .order_by(
                ExpectedFlightCargo.flight_name,
                ExpectedFlightCargo.client_code,
                ExpectedFlightCargo.created_at,
            )
            .offset((page - 1) * size)
            .limit(size)
        )
        records = list(records_result.scalars().all())

        return records, total

    @staticmethod
    async def get_all_for_export(
        session: AsyncSession,
        flight_name: str | None = None,
    ) -> list[ExpectedFlightCargo]:
        """
        Fetch all records ordered for Excel export (flight → client → created_at).

        Args:
            session:     Open async DB session.
            flight_name: Optional filter.  If None, returns the entire table.

        Returns:
            Ordered list of ExpectedFlightCargo records.
        """
        query = select(ExpectedFlightCargo).where(
            ExpectedFlightCargo.is_placeholder == False  # noqa: E712
        )
        if flight_name:
            query = query.where(
                func.lower(ExpectedFlightCargo.flight_name) == flight_name.strip().lower()
            )
        query = query.order_by(
            ExpectedFlightCargo.flight_name,
            ExpectedFlightCargo.client_code,
            ExpectedFlightCargo.created_at,
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_track_codes_by_flight_and_client(
        session: AsyncSession,
        flight_name: str,
        client_code: str,
    ) -> list[str]:
        """
        Return all track codes belonging to a specific client within a flight.

        Used by the bulk cargo sender as the preferred source for track codes,
        replacing Google Sheets lookups when expected-cargo data is available.

        Args:
            session:     Open async DB session.
            flight_name: Exact flight name (case-insensitive).
            client_code: Client code to scope the lookup (case-insensitive).

        Returns:
            Ordered list of track_code strings (oldest first).  Empty list if
            no records exist for this flight + client combination.
        """
        result = await session.execute(
            select(ExpectedFlightCargo.track_code)
            .where(
                ExpectedFlightCargo.is_placeholder == False,  # noqa: E712
                func.lower(ExpectedFlightCargo.flight_name) == flight_name.strip().lower(),
                func.upper(ExpectedFlightCargo.client_code) == client_code.strip().upper(),
            )
            .order_by(ExpectedFlightCargo.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_distinct_flights_for_client(
        session: AsyncSession,
        client_codes: list[str],
    ) -> list[str]:
        """
        Return distinct flight names that have expected cargo for any of the given client codes.

        Used by the payment flow to discover flights originating from the DB
        (i.e. not visible in Google Sheets) so they can be offered for payment.

        Args:
            session:      Open async DB session.
            client_codes: List of client codes to look up (case-insensitive).

        Returns:
            Alphabetically ordered list of distinct flight names.  Empty list
            when no expected cargo records exist for the given codes.
        """
        if not client_codes:
            return []
        upper_codes = [c.strip().upper() for c in client_codes if c]
        if not upper_codes:
            return []
        result = await session.execute(
            select(func.distinct(ExpectedFlightCargo.flight_name))
            .where(
                ExpectedFlightCargo.is_placeholder == False,  # noqa: E712
                func.upper(ExpectedFlightCargo.client_code).in_(upper_codes),
            )
            .order_by(ExpectedFlightCargo.flight_name)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_track_codes_grouped_by_flight(
        session: AsyncSession,
        flight_name: str,
    ) -> dict[str, list[str]]:
        """
        Return all track codes for a flight, grouped by client code.

        Executes a single query and builds the mapping in Python to avoid
        N+1 lookups when processing every client in a flight during bulk sends.

        The primary use-case is the ``flight_notify`` sender: it pre-fetches
        this dict once, then resolves each ``ClientNotifyData.track_codes``
        without hitting the DB again per client.

        Args:
            session:     Open async DB session.
            flight_name: Exact flight name (case-insensitive).

        Returns:
            Dict mapping upper-cased client codes to their ordered track-code lists.
            Example: {"SS123": ["TRK001", "TRK002"], "AD456": ["TRK003"]}
        """
        result = await session.execute(
            select(ExpectedFlightCargo.client_code, ExpectedFlightCargo.track_code)
            .where(
                ExpectedFlightCargo.is_placeholder == False,  # noqa: E712
                func.lower(ExpectedFlightCargo.flight_name) == flight_name.strip().lower(),
            )
            .order_by(ExpectedFlightCargo.client_code, ExpectedFlightCargo.created_at)
        )
        grouped: dict[str, list[str]] = {}
        for client_code, track_code in result.all():
            grouped.setdefault(client_code.upper(), []).append(track_code)
        return grouped

    @staticmethod
    async def find_by_track_code(
        session: AsyncSession,
        track_code: str,
        flight_name: str | None = None,
    ) -> ExpectedFlightCargo | None:
        """
        Look up a single expected cargo record by track code.

        Args:
            session:     Open async DB session.
            track_code:  Exact track code to find (case-insensitive).
            flight_name: Optional additional constraint to narrow the lookup.

        Returns:
            The matching record or None if not found.
        """
        conditions = [
            ExpectedFlightCargo.is_placeholder == False,  # noqa: E712
            func.lower(ExpectedFlightCargo.track_code) == track_code.strip().lower(),
        ]
        if flight_name:
            conditions.append(
                func.lower(ExpectedFlightCargo.flight_name) == flight_name.strip().lower()
            )

        result = await session.execute(
            select(ExpectedFlightCargo).where(*conditions).limit(1)
        )
        return result.scalar_one_or_none()

    # -------------------------------------------------------------------
    # Write operations
    # -------------------------------------------------------------------

    @staticmethod
    async def create_empty_flight(
        session: AsyncSession,
        flight_name: str,
    ) -> bool:
        """Register a placeholder row marking an otherwise-empty flight.

        A single row is inserted with the sentinel client code
        (``ExpectedFlightCargo.PLACEHOLDER_CLIENT_CODE``) and a deterministic
        sentinel track code so the flight appears in listings even though it
        holds no real cargo yet.  All read/stat/export queries filter rows
        where ``is_placeholder = True`` so the sentinel is invisible in normal
        responses.

        Behaviour:
          * Idempotent — if a placeholder (or any other row) already exists for
            the same ``flight_name``, no row is inserted and ``False`` is
            returned.
          * Uses ``INSERT ... ON CONFLICT DO NOTHING`` on the unique track_code
            column so two concurrent callers never double-insert.

        Args:
            session:     Open async DB session (caller commits).
            flight_name: Target flight name.

        Returns:
            True when a placeholder row was freshly inserted, False when the
            flight was already known to the table.
        """
        flight_name_norm = flight_name.strip()
        if not flight_name_norm:
            raise ValueError("flight_name must be non-empty")

        # Short-circuit: if any non-placeholder row already exists, the flight
        # is already "known" and no placeholder is needed.
        existing_real = await session.execute(
            select(func.count(ExpectedFlightCargo.id)).where(
                func.lower(ExpectedFlightCargo.flight_name) == flight_name_norm.lower(),
                ExpectedFlightCargo.is_placeholder == False,  # noqa: E712
            )
        )
        if existing_real.scalar_one() > 0:
            return False

        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(ExpectedFlightCargo)
            .values(
                flight_name=flight_name_norm,
                client_code=ExpectedFlightCargo.PLACEHOLDER_CLIENT_CODE,
                track_code=ExpectedFlightCargo.make_placeholder_track_code(flight_name_norm),
                is_placeholder=True,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["track_code"])
            .returning(ExpectedFlightCargo.id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def delete_placeholder(
        session: AsyncSession,
        flight_name: str,
    ) -> int:
        """Remove any placeholder rows for ``flight_name``.

        Called whenever the first *real* track code is inserted for a flight
        so the sentinel never lingers alongside genuine data.  Safe to call
        unconditionally — returns 0 when no placeholder exists.
        """
        result = await session.execute(
            delete(ExpectedFlightCargo)
            .where(
                func.lower(ExpectedFlightCargo.flight_name) == flight_name.strip().lower(),
                ExpectedFlightCargo.is_placeholder == True,  # noqa: E712
            )
            .returning(ExpectedFlightCargo.id)
        )
        return len(result.fetchall())

    @staticmethod
    async def bulk_create(
        session: AsyncSession,
        flight_name: str,
        client_code: str,
        track_codes: list[str],
    ) -> BulkCreateResult:
        """
        Atomically insert multiple track codes for one flight + client combination.

        Uses PostgreSQL INSERT … ON CONFLICT DO NOTHING RETURNING so the entire
        operation is a single round-trip with no SELECT-then-INSERT race window.
        Any track_code that conflicts with the UNIQUE constraint is silently
        skipped; only the codes actually written are returned via RETURNING.

        Args:
            session:     Open async DB session (caller must commit).
            flight_name: Target flight name.
            client_code: Target client code.
            track_codes: List of tracking codes to insert.

        Returns:
            BulkCreateResult with created_count and duplicate_track_codes.
        """
        if not track_codes:
            return BulkCreateResult(created_count=0, duplicate_track_codes=[])

        normalised_codes = [tc.strip().upper() for tc in track_codes if tc.strip()]
        if not normalised_codes:
            return BulkCreateResult(created_count=0, duplicate_track_codes=[])

        now = datetime.now(timezone.utc)

        # Remove any placeholder sentinel for this flight before inserting real
        # cargo.  Keeping it would waste an index slot and confuse the
        # "is this flight empty?" check performed by create_empty_flight.
        await ExpectedFlightCargoDAO.delete_placeholder(session, flight_name)

        stmt = (
            pg_insert(ExpectedFlightCargo)
            .values([
                {
                    "flight_name": flight_name.strip(),
                    "client_code": client_code.strip().upper(),
                    "track_code": code,
                    "is_placeholder": False,
                    "created_at": now,
                    "updated_at": now,
                }
                for code in normalised_codes
            ])
            .on_conflict_do_nothing(index_elements=["track_code"])
            .returning(ExpectedFlightCargo.track_code)
        )
        result = await session.execute(stmt)
        inserted_codes: set[str] = {row.track_code for row in result.fetchall()}
        duplicates = [code for code in normalised_codes if code not in inserted_codes]

        logger.debug(
            "bulk_create: flight=%r client=%r inserted=%d duplicates=%d",
            flight_name,
            client_code,
            len(inserted_codes),
            len(duplicates),
        )
        return BulkCreateResult(
            created_count=len(inserted_codes),
            duplicate_track_codes=duplicates,
        )

    @staticmethod
    async def replace_client_track_codes(
        session: AsyncSession,
        flight_name: str,
        client_code: str,
        new_track_codes: list[str],
    ) -> ReplaceResult:
        """
        Atomically replace all track codes for a flight + client pair.

        Executes DELETE then bulk-INSERT inside the same transaction so the
        table is never left in a half-replaced state.  The caller is responsible
        for committing (or rolling back on error).

        Args:
            session:        Open async DB session.
            flight_name:    Target flight.
            client_code:    Target client.
            new_track_codes: Full replacement list of tracking codes.

        Returns:
            ReplaceResult with deleted_count and created_count.
        """
        normalised_flight = flight_name.strip()
        normalised_client = client_code.strip().upper()

        # Step 1: delete all existing records for this flight + client.
        delete_result = await session.execute(
            delete(ExpectedFlightCargo).where(
                func.lower(ExpectedFlightCargo.flight_name) == normalised_flight.lower(),
                func.upper(ExpectedFlightCargo.client_code) == normalised_client,
            ).returning(ExpectedFlightCargo.id)
        )
        deleted_count = len(delete_result.fetchall())

        # Step 2: insert the new set (normalise codes consistently).
        normalised_codes = list({tc.strip().upper() for tc in new_track_codes if tc.strip()})
        new_records = [
            ExpectedFlightCargo(
                flight_name=normalised_flight,
                client_code=normalised_client,
                track_code=code,
            )
            for code in normalised_codes
        ]
        if new_records:
            session.add_all(new_records)
            await session.flush()

        logger.debug(
            "replace_client_track_codes: flight=%r client=%r deleted=%d created=%d",
            flight_name,
            client_code,
            deleted_count,
            len(new_records),
        )
        return ReplaceResult(deleted_count=deleted_count, created_count=len(new_records))

    @staticmethod
    async def rename_flight(
        session: AsyncSession,
        old_flight_name: str,
        new_flight_name: str,
    ) -> int:
        """
        Rename all records that belong to old_flight_name to new_flight_name.

        Args:
            session:         Open async DB session.
            old_flight_name: Current flight name.
            new_flight_name: Replacement flight name.

        Returns:
            Number of rows updated.
        """
        result = await session.execute(
            update(ExpectedFlightCargo)
            .where(
                func.lower(ExpectedFlightCargo.flight_name) == old_flight_name.strip().lower()
            )
            .values(flight_name=new_flight_name.strip())
            .returning(ExpectedFlightCargo.id)
        )
        updated_count = len(result.fetchall())
        logger.debug(
            "rename_flight: %r → %r, updated %d rows",
            old_flight_name,
            new_flight_name,
            updated_count,
        )
        return updated_count

    @staticmethod
    async def rename_client_code(
        session: AsyncSession,
        flight_name: str,
        old_client_code: str,
        new_client_code: str,
    ) -> int:
        """
        Rename client_code for all records within a specific flight.

        Args:
            session:         Open async DB session.
            flight_name:     Target flight — only records in this flight are touched.
            old_client_code: Current client code to find.
            new_client_code: Replacement client code value.

        Returns:
            Number of rows updated.
        """
        result = await session.execute(
            update(ExpectedFlightCargo)
            .where(
                func.lower(ExpectedFlightCargo.flight_name) == flight_name.strip().lower(),
                func.lower(ExpectedFlightCargo.client_code) == old_client_code.strip().lower(),
            )
            .values(client_code=new_client_code.strip())
            .returning(ExpectedFlightCargo.id)
        )
        updated_count = len(result.fetchall())
        logger.debug(
            "rename_client_code: flight=%r, %r → %r, updated %d rows",
            flight_name,
            old_client_code,
            new_client_code,
            updated_count,
        )
        return updated_count

    @staticmethod
    async def dynamic_delete(
        session: AsyncSession,
        flight_name: str | None,
        client_code: str | None,
    ) -> int:
        """
        Delete records according to the provided filter combination.

        Behaviour matrix:
          • flight_name only   → delete ALL records for that flight.
          • flight_name + client_code → delete that client's records in that flight.
          • client_code only   → global delete: remove all records for this client
                                 across every flight.
          • neither provided   → raises ValueError (caller should return HTTP 400).

        Args:
            session:     Open async DB session.
            flight_name: Optional flight name filter.
            client_code: Optional client code filter.

        Returns:
            Number of rows deleted.

        Raises:
            ValueError: If neither flight_name nor client_code is provided.
        """
        if not flight_name and not client_code:
            raise ValueError(
                "At least one of flight_name or client_code must be provided."
            )

        conditions: list = []
        if flight_name:
            conditions.append(
                func.lower(ExpectedFlightCargo.flight_name) == flight_name.strip().lower()
            )
        if client_code:
            conditions.append(
                func.upper(ExpectedFlightCargo.client_code) == client_code.strip().upper()
            )

        result = await session.execute(
            delete(ExpectedFlightCargo)
            .where(*conditions)
            .returning(ExpectedFlightCargo.id)
        )
        deleted_count = len(result.fetchall())
        logger.debug(
            "dynamic_delete: flight=%r client=%r deleted %d rows",
            flight_name,
            client_code,
            deleted_count,
        )
        return deleted_count

    # -------------------------------------------------------------------
    # Statistics queries
    # -------------------------------------------------------------------

    @staticmethod
    async def get_summary_stats(session: AsyncSession) -> SummaryStats:
        """
        Return aggregate totals for the entire table in a single query.

        Returns:
            SummaryStats with total_records, total_unique_flights,
            total_unique_clients.
        """
        result = await session.execute(
            select(
                func.count(ExpectedFlightCargo.id).label("total_records"),
                func.count(distinct(ExpectedFlightCargo.flight_name)).label("total_unique_flights"),
                func.count(distinct(ExpectedFlightCargo.client_code)).label("total_unique_clients"),
            ).where(ExpectedFlightCargo.is_placeholder == False)  # noqa: E712
        )
        row = result.one()
        return SummaryStats(
            total_records=row.total_records,
            total_unique_flights=row.total_unique_flights,
            total_unique_clients=row.total_unique_clients,
        )

    @staticmethod
    async def get_stats_by_flight(
        session: AsyncSession,
        page: int,
        size: int,
        client_code: str | None = None,
    ) -> tuple[list[FlightStat], int]:
        """
        Return per-flight statistics, optionally scoped to one client.

        Each row contains: flight_name, how many distinct clients are in
        that flight, and the total number of track codes.

        Args:
            session:     Open async DB session.
            page:        1-based page number.
            size:        Rows per page.
            client_code: Optional filter — restricts output to flights that
                         contain this client.

        Returns:
            Tuple of (list of FlightStat, total matching flight count).
        """
        base_filter: list = [ExpectedFlightCargo.is_placeholder == False]  # noqa: E712
        if client_code:
            base_filter.append(
                func.upper(ExpectedFlightCargo.client_code) == client_code.strip().upper()
            )

        # Subquery: group by flight_name (with optional client filter)
        grouped = (
            select(
                ExpectedFlightCargo.flight_name,
                func.count(distinct(ExpectedFlightCargo.client_code)).label("client_count"),
                func.count(ExpectedFlightCargo.id).label("track_code_count"),
            )
            .where(*base_filter)
            .group_by(ExpectedFlightCargo.flight_name)
            .subquery()
        )

        total_result = await session.execute(
            select(func.count()).select_from(grouped)
        )
        total: int = total_result.scalar_one()

        rows_result = await session.execute(
            select(
                grouped.c.flight_name,
                grouped.c.client_count,
                grouped.c.track_code_count,
            )
            .order_by(grouped.c.track_code_count.desc())
            .offset((page - 1) * size)
            .limit(size)
        )

        stats = [
            FlightStat(
                flight_name=row.flight_name,
                client_count=row.client_count,
                track_code_count=row.track_code_count,
            )
            for row in rows_result.all()
        ]
        return stats, total

    @staticmethod
    async def get_stats_by_client(
        session: AsyncSession,
        page: int,
        size: int,
        flight_name: str | None = None,
    ) -> tuple[list[ClientStat], int]:
        """
        Return per-client statistics, optionally scoped to one flight.

        Each row contains: client_code, how many distinct flights this
        client appears in, and the total number of their track codes.

        Args:
            session:     Open async DB session.
            page:        1-based page number.
            size:        Rows per page.
            flight_name: Optional filter — restricts output to clients
                         present in this specific flight.

        Returns:
            Tuple of (list of ClientStat, total matching client count).
        """
        base_filter: list = [ExpectedFlightCargo.is_placeholder == False]  # noqa: E712
        if flight_name:
            base_filter.append(
                func.lower(ExpectedFlightCargo.flight_name) == flight_name.strip().lower()
            )

        grouped = (
            select(
                ExpectedFlightCargo.client_code,
                func.count(distinct(ExpectedFlightCargo.flight_name)).label("flight_count"),
                func.count(ExpectedFlightCargo.id).label("track_code_count"),
            )
            .where(*base_filter)
            .group_by(ExpectedFlightCargo.client_code)
            .subquery()
        )

        total_result = await session.execute(
            select(func.count()).select_from(grouped)
        )
        total: int = total_result.scalar_one()

        rows_result = await session.execute(
            select(
                grouped.c.client_code,
                grouped.c.flight_count,
                grouped.c.track_code_count,
            )
            .order_by(grouped.c.track_code_count.desc())
            .offset((page - 1) * size)
            .limit(size)
        )

        stats = [
            ClientStat(
                client_code=row.client_code,
                flight_count=row.flight_count,
                track_code_count=row.track_code_count,
            )
            for row in rows_result.all()
        ]
        return stats, total

    @staticmethod
    async def get_clients_summary_by_flight(
        session: AsyncSession,
        flight_name: str,
        page: int,
        size: int,
    ) -> tuple[list[ClientStat], int]:
        """
        Return each client's track code count within a specific flight.

        Designed for the frontend's collapsed list view: each row tells you
        "client X has N track codes in this flight" without loading all the
        individual codes.  flight_name is required — this query is meaningless
        without it.

        Args:
            session:     Open async DB session.
            flight_name: The flight to scope the query to (required).
            page:        1-based page number.
            size:        Rows per page.

        Returns:
            Tuple of (list of ClientStat, total client count in this flight).
        """
        grouped = (
            select(
                ExpectedFlightCargo.client_code,
                # flight_count is always 1 here (scoped to one flight),
                # but we reuse ClientStat to keep the return type consistent.
                func.count(ExpectedFlightCargo.id).label("track_code_count"),
            )
            .where(
                ExpectedFlightCargo.is_placeholder == False,  # noqa: E712
                func.lower(ExpectedFlightCargo.flight_name) == flight_name.strip().lower(),
            )
            .group_by(ExpectedFlightCargo.client_code)
            .subquery()
        )

        total_result = await session.execute(
            select(func.count()).select_from(grouped)
        )
        total: int = total_result.scalar_one()

        rows_result = await session.execute(
            select(
                grouped.c.client_code,
                grouped.c.track_code_count,
            )
            .order_by(grouped.c.track_code_count.desc())
            .offset((page - 1) * size)
            .limit(size)
        )

        stats = [
            ClientStat(
                client_code=row.client_code,
                flight_count=1,
                track_code_count=row.track_code_count,
            )
            for row in rows_result.all()
        ]
        return stats, total

    @staticmethod
    async def get_distinct_flights(
        session: AsyncSession,
        limit: int | None = None,
    ) -> list[FlightStat]:
        """
        Return distinct flight names with their aggregate counts.

        Args:
            session: Open async DB session.
            limit:   When provided, returns only the *most recently updated*
                     flights (ordered by MAX(created_at) DESC and then capped).
                     When None, returns all flights ordered alphabetically.

        Returns:
            List of FlightStat (flight_name, client_count, track_code_count).
        """
        last_added = func.max(ExpectedFlightCargo.created_at).label("last_added")

        # Pure-placeholder flights (no real cargo yet) must still appear in the
        # listing so admins can pick them, but their counts must ignore the
        # placeholder sentinel row — hence conditional COUNT(... FILTER WHERE).
        non_placeholder = ExpectedFlightCargo.is_placeholder == False  # noqa: E712

        query = (
            select(
                ExpectedFlightCargo.flight_name,
                func.count(distinct(ExpectedFlightCargo.client_code))
                    .filter(non_placeholder)
                    .label("client_count"),
                func.count(ExpectedFlightCargo.id)
                    .filter(non_placeholder)
                    .label("track_code_count"),
                last_added,
            )
            .group_by(ExpectedFlightCargo.flight_name)
        )

        if limit is not None:
            # Most-recently-touched flights first so the admin sees current work
            query = query.order_by(last_added.desc()).limit(limit)
        else:
            query = query.order_by(ExpectedFlightCargo.flight_name)

        rows_result = await session.execute(query)

        return [
            FlightStat(
                flight_name=row.flight_name,
                client_count=row.client_count,
                track_code_count=row.track_code_count,
            )
            for row in rows_result.all()
        ]
