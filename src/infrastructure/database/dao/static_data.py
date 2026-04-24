"""Static Data DAO - Database access layer for static data operations.

This DAO handles the singleton static_data table that must always contain
exactly one row with id=1.
"""
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from src.infrastructure.database.models.static_data import StaticData


class StaticDataDAO:
    """Data Access Object for StaticData operations.

    The static_data table is a singleton - it must always contain exactly
    one row with id=1. Use get_or_create_singleton() to safely access it.
    """

    @staticmethod
    async def get_or_create_singleton(session: AsyncSession) -> StaticData:
        """
        Get the singleton configuration row, creating it if it doesn't exist.

        This is the preferred method for accessing static_data. It ensures
        exactly one row with id=1 exists, using ON CONFLICT DO NOTHING for
        race condition safety.

        Args:
            session: Database session

        Returns:
            The singleton StaticData row (id=1) with default values
        """
        # Try to get existing row first
        result = await session.execute(
            select(StaticData).where(StaticData.id == 1)
        )
        instance = result.scalar_one_or_none()

        if instance is None:
            # Insert with ON CONFLICT DO NOTHING for race condition safety
            stmt = insert(StaticData).values(
                id=1,
                foto_hisobot='',
                extra_charge=100,
                price_per_kg=9.5,
                notification=False,
                notification_period=1,
                custom_usd_rate=None,
                use_custom_rate=False
            ).on_conflict_do_nothing(index_elements=['id'])
            await session.execute(stmt)
            await session.commit()

            # Fetch the row (either we inserted it or someone else did)
            result = await session.execute(
                select(StaticData).where(StaticData.id == 1)
            )
            instance = result.scalar_one()

        return instance

    @staticmethod
    async def get_by_id(session: AsyncSession, data_id: int) -> StaticData | None:
        """
        Get static data by ID.

        Args:
            session: Database session
            data_id: Static data ID

        Returns:
            StaticData object or None if not found
        """
        result = await session.execute(
            select(StaticData).where(StaticData.id == data_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(session: AsyncSession) -> list[StaticData]:
        """
        Get all static data entries.

        Args:
            session: Database session

        Returns:
            List of all StaticData objects
        """
        result = await session.execute(select(StaticData))
        return list(result.scalars().all())

    @staticmethod
    async def create(
        session: AsyncSession,
        foto_hisobot: str | None = None,
        extra_charge: int | None = None,
        price_per_kg: float | None = None,
        notification: bool = False,
        notification_period: int | None = None,
        custom_usd_rate: float | None = None,
        use_custom_rate: bool = False,
        ostatka_daily_notifications: bool = False,
        ostatka_daily_flight_names: str | None = None,
    ) -> StaticData:
        """
        Create new static data entry.

        Args:
            session: Database session
            foto_hisobot: Photo report template text
            extra_charge: Extra charge amount
            price_per_kg: Price per kilogram
            notification: Whether notifications are enabled
            notification_period: Notification period in days
            custom_usd_rate: Override for USD to UZS rate
            use_custom_rate: Whether to use the custom rate

        Returns:
            Created StaticData object
        """
        data = StaticData(
            foto_hisobot=foto_hisobot,
            extra_charge=extra_charge,
            price_per_kg=price_per_kg,
            notification=notification,
            notification_period=notification_period,
            custom_usd_rate=custom_usd_rate,
            use_custom_rate=use_custom_rate,
            ostatka_daily_notifications=ostatka_daily_notifications,
            ostatka_daily_flight_names=ostatka_daily_flight_names or '[]',
        )
        session.add(data)
        await session.flush()
        await session.refresh(data)
        return data

    @staticmethod
    async def update(
        session: AsyncSession,
        data_id: int,
        foto_hisobot: str | None = None,
        extra_charge: int | None = None,
        price_per_kg: float | None = None,
        notification: bool | None = None,
        notification_period: int | None = None,
        custom_usd_rate: float | None = None,
        use_custom_rate: bool | None = None,
        ostatka_daily_notifications: bool | None = None,
        ostatka_daily_flight_names: str | None = None,
    ) -> StaticData | None:
        """
        Update static data entry.

        Args:
            session: Database session
            data_id: Static data ID
            foto_hisobot: New photo report template text (optional)
            extra_charge: New extra charge amount (optional)
            price_per_kg: New price per kilogram (optional)
            notification: Whether notifications are enabled (optional)
            notification_period: Notification period in days (optional)
            custom_usd_rate: New USD override rate (optional)
            use_custom_rate: Whether to use the custom rate (optional)

        Returns:
            Updated StaticData object or None if not found
        """
        data = await StaticDataDAO.get_by_id(session, data_id)
        if not data:
            return None

        if foto_hisobot is not None:
            data.foto_hisobot = foto_hisobot
        if extra_charge is not None:
            data.extra_charge = extra_charge
        if price_per_kg is not None:
            data.price_per_kg = price_per_kg
        if notification is not None:
            data.notification = notification
        if notification_period is not None:
            data.notification_period = notification_period
        if custom_usd_rate is not None:
            data.custom_usd_rate = custom_usd_rate
        if use_custom_rate is not None:
            data.use_custom_rate = use_custom_rate
        if ostatka_daily_notifications is not None:
            data.ostatka_daily_notifications = ostatka_daily_notifications
        if ostatka_daily_flight_names is not None:
            data.ostatka_daily_flight_names = ostatka_daily_flight_names

        await session.flush()
        await session.refresh(data)
        return data

    @staticmethod
    async def delete(session: AsyncSession, data_id: int) -> bool:
        """
        Delete static data entry.

        Args:
            session: Database session
            data_id: Static data ID

        Returns:
            True if deleted, False if not found
        """
        data = await StaticDataDAO.get_by_id(session, data_id)
        if not data:
            return False

        await session.delete(data)
        await session.flush()
        return True

    @staticmethod
    async def get_first(session: AsyncSession) -> StaticData | None:
        """
        Get the first static data entry (most commonly used for singleton pattern).

        Args:
            session: Database session

        Returns:
            First StaticData object or None if table is empty
        """
        result = await session.execute(
            select(StaticData).order_by(StaticData.id).limit(1)
        )
        return result.scalar_one_or_none()
