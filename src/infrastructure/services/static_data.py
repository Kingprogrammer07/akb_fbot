"""Static Data Service - Business logic layer for static data operations."""
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.database.models.static_data import StaticData


class StaticDataService:
    """Service layer for static data operations."""

    async def get_settings(self, session: AsyncSession) -> dict:
        """
        Get current settings (first row or default values).

        Args:
            session: Database session

        Returns:
            Dictionary with:
                - found: bool
                - foto_hisobot: str | None
                - extra_charge: int | None
                - price_per_kg: float | None
        """
        data = await StaticDataDAO.get_first(session)

        if not data:
            return {
                'found': False,
                'foto_hisobot': None,
                'extra_charge': None,
                'price_per_kg': None
            }

        return {
            'found': True,
            'foto_hisobot': data.foto_hisobot,
            'extra_charge': data.extra_charge,
            'price_per_kg': data.price_per_kg
        }

    async def update_settings(
        self,
        session: AsyncSession,
        foto_hisobot: str | None = None,
        extra_charge: int | None = None,
        price_per_kg: float | None = None,
        custom_usd_rate: float | None = None,
        use_custom_rate: bool | None = None,
        ostatka_daily_notifications: bool | None = None,
        ostatka_daily_flight_names: str | None = None,
    ) -> dict:
        """
        Update settings (first row, create if not exists).

        Args:
            session: Database session
            foto_hisobot: New photo report template text
            extra_charge: New extra charge amount
            price_per_kg: New price per kilogram
            custom_usd_rate: Override rate
            use_custom_rate: Enable override flag

        Returns:
            Dictionary with:
                - success: bool
                - message: str
                - data: StaticData object
        """
        # Get existing settings or create new
        data = await StaticDataDAO.get_first(session)

        if data:
            # Update existing
            updated_data = await StaticDataDAO.update(
                session,
                data_id=data.id,
                foto_hisobot=foto_hisobot,
                extra_charge=extra_charge,
                price_per_kg=price_per_kg,
                custom_usd_rate=custom_usd_rate,
                use_custom_rate=use_custom_rate,
                ostatka_daily_notifications=ostatka_daily_notifications,
                ostatka_daily_flight_names=ostatka_daily_flight_names,
            )
            await session.commit()

            return {
                'success': True,
                'message': 'Settings updated successfully',
                'data': updated_data
            }
        else:
            # Create new
            new_data = await StaticDataDAO.create(
                session,
                foto_hisobot=foto_hisobot,
                extra_charge=extra_charge,
                price_per_kg=price_per_kg,
                custom_usd_rate=custom_usd_rate,
                use_custom_rate=use_custom_rate,
                ostatka_daily_notifications=(ostatka_daily_notifications or False),
                ostatka_daily_flight_names=(ostatka_daily_flight_names or '[]'),
            )
            await session.commit()

            return {
                'success': True,
                'message': 'Settings created successfully',
                'data': new_data
            }

    async def get_foto_hisobot(self, session: AsyncSession) -> str | None:
        """
        Get photo report template text.

        Args:
            session: Database session

        Returns:
            Template text or None
        """
        data = await StaticDataDAO.get_first(session)
        return data.foto_hisobot if data else None

    async def get_extra_charge(self, session: AsyncSession) -> int | None:
        """
        Get extra charge amount.

        Args:
            session: Database session

        Returns:
            Extra charge amount or None
        """
        data = await StaticDataDAO.get_first(session)
        return data.extra_charge if data else None

    async def update_foto_hisobot(
        self,
        session: AsyncSession,
        foto_hisobot: str
    ) -> dict:
        """
        Update only foto_hisobot field.

        Args:
            session: Database session
            foto_hisobot: New photo report template text

        Returns:
            Dictionary with success status and message
        """
        return await self.update_settings(
            session,
            foto_hisobot=foto_hisobot
        )

    async def update_extra_charge(
        self,
        session: AsyncSession,
        extra_charge: int
    ) -> dict:
        """
        Update only extra_charge field.

        Args:
            session: Database session
            extra_charge: New extra charge amount

        Returns:
            Dictionary with success status and message
        """
        return await self.update_settings(
            session,
            extra_charge=extra_charge
        )

    async def get_price_per_kg(self, session: AsyncSession) -> float | None:
        """
        Get price per kilogram.

        Args:
            session: Database session

        Returns:
            Price per kg or None
        """
        data = await StaticDataDAO.get_first(session)
        return data.price_per_kg if data else None

    async def update_price_per_kg(
        self,
        session: AsyncSession,
        price_per_kg: float
    ) -> dict:
        """
        Update only price_per_kg field.

        Args:
            session: Database session
            price_per_kg: New price per kilogram

        Returns:
            Dictionary with success status and message
        """
        return await self.update_settings(
            session,
            price_per_kg=price_per_kg
        )

    async def update_usd_rate_mode(
        self,
        session: AsyncSession,
        use_custom_rate: bool
    ) -> dict:
        """
        Update the USD rate mode.

        Args:
            session: Database session
            use_custom_rate: Whether to use custom rate

        Returns:
            Dictionary with success status and message
        """
        return await self.update_settings(
            session,
            use_custom_rate=use_custom_rate
        )

    async def update_custom_usd_rate(
        self,
        session: AsyncSession,
        custom_usd_rate: float
    ) -> dict:
        """
        Update the custom USD rate override. Also automatically enables it.

        Args:
            session: Database session
            custom_usd_rate: New USD to UZS rate

        Returns:
            Dictionary with success status and message
        """
        return await self.update_settings(
            session,
            custom_usd_rate=custom_usd_rate,
            use_custom_rate=True
        )

    async def update_ostatka_daily_notifications(
        self,
        session: AsyncSession,
        enabled: bool,
    ) -> dict:
        """Toggle the daily ostatka digest flag on the singleton row."""
        return await self.update_settings(
            session,
            ostatka_daily_notifications=enabled,
        )

    async def update_ostatka_daily_flight_names(
        self,
        session: AsyncSession,
        flight_names: list[str],
    ) -> dict:
        """Persist the list of A- flights selected for daily auto-send."""
        import json

        return await self.update_settings(
            session,
            ostatka_daily_flight_names=json.dumps(flight_names),
        )
