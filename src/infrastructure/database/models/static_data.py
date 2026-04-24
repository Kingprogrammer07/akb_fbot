"""Static data model for admin settings and templates.

This is a SINGLETON table - it must always contain exactly one row with id=1.
"""
from sqlalchemy import Column, Text, Integer, Float, Boolean
from src.infrastructure.database.models.base import Base


class StaticData(Base):
    """
    Static data model for storing admin templates and configurable settings.

    This is a SINGLETON table - must always contain exactly one row with id=1.
    Use get_or_create_singleton() to safely access the configuration.

    Attributes:
        id: Always 1 (singleton)
        created_at: Creation timestamp (Asia/Tashkent)
        updated_at: Last update timestamp (Asia/Tashkent)
        foto_hisobot: Photo report template/message text
        extra_charge: Extra charge amount (integer)
        price_per_kg: Price per kilogram
        notification: Whether leftover cargo notifications are enabled
        notification_period: How often (in days) notifications are sent
        custom_usd_rate: Override for USD to UZS exchange rate
        use_custom_rate: Whether to use the custom rate over the API rate
    """
    __tablename__ = "static_data"

    # id, created_at, updated_at inherited from Base

    foto_hisobot = Column(
        Text,
        nullable=False,
        default='',
        server_default='',
        comment="Photo report template text"
    )

    extra_charge = Column(
        Integer,
        nullable=False,
        default=100,
        server_default='100',
        comment="Extra charge amount"
    )

    price_per_kg = Column(
        Float,
        nullable=False,
        default=9.5,
        server_default='9.5',
        comment="Price per kilogram (e.g., 9.2, 10.4)"
    )

    notification = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default='false',
        comment="Whether leftover cargo notifications are enabled"
    )

    notification_period = Column(
        Integer,
        nullable=False,
        default=1,
        server_default='1',
        comment="How often (in DAYS) notifications are sent (1-15 days)"
    )

    custom_usd_rate = Column(
        Float,
        nullable=True,
        comment="Custom USD to UZS rate override"
    )

    use_custom_rate = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default='false',
        comment="Whether to use the custom rate instead of API rate"
    )

    ostatka_daily_notifications = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default='false',
        comment="Whether to post daily ostatka (A-) leftover statistics to AKB_OSTATKA_GROUP_ID"
    )

    ostatka_daily_flight_names = Column(
        Text,
        nullable=False,
        default='[]',
        server_default="'[]'",
        comment="JSON array of A- flight names selected for daily auto-send"
    )

    def __repr__(self):
        return f"<StaticData(id={self.id}, extra_charge={self.extra_charge}, price_per_kg={self.price_per_kg}, use_custom_rate={self.use_custom_rate}, custom_usd_rate={self.custom_usd_rate})>"

    @classmethod
    async def get_or_create_singleton(cls, session) -> "StaticData":
        """
        Get the singleton configuration row, creating it if it doesn't exist.

        This ensures exactly one row with id=1 exists in the table.

        Args:
            session: AsyncSession instance

        Returns:
            The singleton StaticData row
        """
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert

        # Try to get existing row
        result = await session.execute(select(cls).where(cls.id == 1))
        instance = result.scalar_one_or_none()

        if instance is None:
            # Insert with ON CONFLICT DO NOTHING for race condition safety
            stmt = insert(cls).values(id=1).on_conflict_do_nothing(index_elements=['id'])
            await session.execute(stmt)
            await session.commit()

            # Fetch the row (either we inserted it or someone else did)
            result = await session.execute(select(cls).where(cls.id == 1))
            instance = result.scalar_one()

        return instance
