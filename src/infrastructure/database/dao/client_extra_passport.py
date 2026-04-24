"""Client Extra Passport DAO."""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.client_extra_passport import ClientExtraPassport


class ClientExtraPassportDAO:
    """Data Access Object for Client Extra Passports."""

    @staticmethod
    async def create(
        session: AsyncSession,
        data: dict
    ) -> ClientExtraPassport:
        """Create a new extra passport entry."""
        extra_passport = ClientExtraPassport(**data)
        session.add(extra_passport)
        await session.flush()
        await session.refresh(extra_passport)
        return extra_passport

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        passport_id: int
    ) -> ClientExtraPassport | None:
        """Get extra passport by ID."""
        result = await session.execute(
            select(ClientExtraPassport).where(ClientExtraPassport.id == passport_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_telegram_id(
        session: AsyncSession,
        telegram_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> list[ClientExtraPassport]:
        """Get all extra passports for a user with pagination."""
        result = await session.execute(
            select(ClientExtraPassport)
            .where(ClientExtraPassport.telegram_id == telegram_id)
            .order_by(ClientExtraPassport.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_by_telegram_id(
        session: AsyncSession,
        telegram_id: int
    ) -> int:
        """Count total extra passports for a user."""
        result = await session.execute(
            select(func.count(ClientExtraPassport.id))
            .where(ClientExtraPassport.telegram_id == telegram_id)
        )
        return result.scalar_one()

    @staticmethod
    async def count_by_client_code(
        session: AsyncSession,
        client_code: str
    ) -> int:
        """Count total extra passports for a client code."""
        result = await session.execute(
            select(func.count(ClientExtraPassport.id))
            .where(ClientExtraPassport.client_code == client_code)
        )
        return result.scalar_one()

    @staticmethod
    async def delete(
        session: AsyncSession,
        passport: ClientExtraPassport
    ) -> None:
        """Delete an extra passport."""
        await session.delete(passport)
        await session.flush()

    @staticmethod
    async def check_duplicate_passport(
        session: AsyncSession,
        passport_series: str,
        pinfl: str,
        telegram_id: int
    ) -> dict[str, bool]:
        """
        Check if passport_series or pinfl already exists for this user.

        Returns:
            dict with 'passport_series' and 'pinfl' keys indicating if duplicates exist
        """
        # Check in client_extra_passports table
        result = await session.execute(
            select(ClientExtraPassport)
            .where(
                ClientExtraPassport.telegram_id == telegram_id,
                (ClientExtraPassport.passport_series == passport_series) |
                (ClientExtraPassport.pinfl == pinfl)
            )
        )
        existing = result.scalar_one_or_none()

        conflicts = {
            'passport_series': False,
            'pinfl': False
        }

        if existing:
            if existing.passport_series == passport_series:
                conflicts['passport_series'] = True
            if existing.pinfl == pinfl:
                conflicts['pinfl'] = True

        return conflicts

    @staticmethod
    async def check_duplicate_in_main_passport(
        session: AsyncSession,
        passport_series: str,
        pinfl: str,
        telegram_id: int
    ) -> dict[str, bool]:
        """
        Check if passport_series or pinfl exists in main Client table.

        Returns:
            dict with 'passport_series' and 'pinfl' keys indicating if duplicates exist
        """
        from src.infrastructure.database.models.client import Client

        result = await session.execute(
            select(Client).where(
                Client.telegram_id == telegram_id,
                (Client.passport_series == passport_series) |
                (Client.pinfl == pinfl)
            )
        )
        existing = result.scalar_one_or_none()

        conflicts = {
            'passport_series': False,
            'pinfl': False
        }

        if existing:
            if existing.passport_series == passport_series:
                conflicts['passport_series'] = True
            if existing.pinfl == pinfl:
                conflicts['pinfl'] = True

        return conflicts
