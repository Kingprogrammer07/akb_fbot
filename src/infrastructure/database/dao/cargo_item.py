"""Cargo Item DAO - Database access layer for cargo operations."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.cargo_item import CargoItem


class CargoItemDAO:
    """Data Access Object for CargoItem operations."""

    @staticmethod
    async def get_by_track_code(
        session: AsyncSession, track_code: str
    ) -> list[CargoItem]:
        """
        Get all cargo items by track code (case-insensitive).

        Args:
            session: Database session
            track_code: Track code to search for

        Returns:
            List of CargoItem objects matching the track code
        """
        result = await session.execute(
            select(CargoItem)
            .where(CargoItem.track_code.ilike(track_code))
            .order_by(CargoItem.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_track_code_and_status(
        session: AsyncSession, track_code: str, status: str
    ) -> list[CargoItem]:
        """
        Get cargo items by track code and checkin status.

        Args:
            session: Database session
            track_code: Track code to search for
            status: Checkin status ('pre' for China, 'post' for Uzbekistan)

        Returns:
            List of CargoItem objects matching criteria
        """
        result = await session.execute(
            select(CargoItem)
            .where(
                CargoItem.track_code.ilike(track_code),
                CargoItem.checkin_status == status
            )
            .order_by(CargoItem.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_client_id(
        session: AsyncSession, client_id: str
    ) -> list[CargoItem]:
        """
        Get all cargo items for a specific client.

        Args:
            session: Database session
            client_id: Client's unique identifier (e.g., SS123)

        Returns:
            List of CargoItem objects for this client
        """
        result = await session.execute(
            select(CargoItem)
            .where(CargoItem.client_id.ilike(client_id))
            .order_by(CargoItem.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_flight_name(
        session: AsyncSession, flight_name: str
    ) -> list[CargoItem]:
        """
        Get all cargo items for a specific flight.

        Args:
            session: Database session
            flight_name: Flight/shipment batch name

        Returns:
            List of CargoItem objects for this flight
        """
        result = await session.execute(
            select(CargoItem)
            .where(CargoItem.flight_name.ilike(flight_name))
            .order_by(CargoItem.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_by_client_and_status(
        session: AsyncSession, client_id: str, status: str
    ) -> int:
        """
        Count cargo items for a client by status.

        Args:
            session: Database session
            client_id: Client's unique identifier
            status: Checkin status

        Returns:
            Count of items
        """
        from sqlalchemy import func

        result = await session.execute(
            select(func.count(CargoItem.id))
            .where(
                CargoItem.client_id.ilike(client_id),
                CargoItem.checkin_status == status
            )
        )
        return result.scalar_one()

    @staticmethod
    async def get_by_flight_and_client(
        session: AsyncSession,
        flight_name: str,
        client_id: str,
        only_unused: bool = False
    ) -> list[CargoItem]:
        """
        Get cargo items by flight and client.

        Args:
            session: Database session
            flight_name: Flight/shipment batch name
            client_id: Client's unique identifier
            only_unused: If True, only return items where is_used=False

        Returns:
            List of CargoItem objects
        """
        query = select(CargoItem).where(
            CargoItem.flight_name.ilike(flight_name),
            CargoItem.client_id.ilike(client_id)
        )

        if only_unused:
            query = query.where(CargoItem.is_used == False)

        query = query.order_by(CargoItem.created_at.desc())

        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_client_flight_summaries(
        session: AsyncSession, client_id: str
    ) -> list[tuple]:
        """
        Get flight summaries for a client.

        Args:
            session: Database session
            client_id: Client's unique identifier

        Returns:
            List of tuples (flight_name, total_count, total_weight, last_update)
        """
        from sqlalchemy import func, cast, Float, case, desc

        # Safely handle weights. If the string contains a hyphen or is empty, treat as 0.0.
        # This prevents PostgreSQL from throwing "invalid input syntax for type double precision".
        clean_weight_expr = case(
            (CargoItem.weight_kg == "-", 0.0),
            (CargoItem.weight_kg == "", 0.0),
            (CargoItem.weight_kg.is_(None), 0.0),
            else_=cast(func.replace(CargoItem.weight_kg, ",", "."), Float)
        )

        stmt = (
            select(
                CargoItem.flight_name,
                func.count(func.distinct(CargoItem.track_code)).label("total_count"),
                func.sum(clean_weight_expr).label("total_weight"),
                func.max(CargoItem.created_at).label("last_update")
            )
            .where(CargoItem.client_id.ilike(client_id))
            .group_by(CargoItem.flight_name)
            .order_by(desc("last_update"))
        )

        result = await session.execute(stmt)
        return result.all()

    @staticmethod
    async def get_items_by_client_and_flight(
        session: AsyncSession,
        client_id: str,
        flight_name: str,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[list[CargoItem], int]:
        """
        Get detailed items for a client and flight with pagination.

        Args:
            session: Database session
            client_id: Client's unique identifier
            flight_name: Flight name
            limit: Number of items per page
            offset: Offset for pagination

        Returns:
            Tuple of (list of CargoItem, total count)
        """
        from sqlalchemy import func

        # Base filter
        filters = [
            CargoItem.client_id.ilike(client_id),
            # Handle case where flight_name might be None in DB vs requested
            # If flight_name is explicitly passed, we match it.
            # If flight_name is "None" string or empty, we match Is None?
            # User requirement says "view detailed cargo items for a selected flight".
            # Usually flight_name is present.
            CargoItem.flight_name.ilike(flight_name)
        ]

        # Total count query
        count_stmt = select(func.count(CargoItem.id)).where(*filters)
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()

        # Items query
        stmt = (
            select(CargoItem)
            .where(*filters)
            .order_by(CargoItem.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    @staticmethod
    async def get_track_codes_by_flight_and_client(
        session: AsyncSession,
        flight_name: str,
        client_id: str
    ) -> list[str]:
        """
        Get distinct track codes for a client in a specific flight.

        Args:
            session: Database session
            flight_name: Flight/shipment batch name
            client_id: Client's unique identifier

        Returns:
            List of distinct track code strings
        """
        from sqlalchemy import func

        result = await session.execute(
            select(func.distinct(CargoItem.track_code))
            .where(
                CargoItem.flight_name.ilike(flight_name),
                CargoItem.client_id.ilike(client_id),
                CargoItem.track_code.isnot(None),
                CargoItem.track_code != ""
            )
            .order_by(CargoItem.track_code)
        )
        return list(result.scalars().all())
