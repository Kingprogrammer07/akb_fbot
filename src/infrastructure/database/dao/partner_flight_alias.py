"""Data access for ``partner_flight_aliases``.

The DAO stays narrow on purpose: callers go through
``services.flight_mask.FlightMaskService`` for any business logic
(uniqueness checks, auto-generation, validation).  Direct DAO use is
acceptable in admin tooling and migrations.
"""
from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.partner_flight_alias import PartnerFlightAlias


class PartnerFlightAliasDAO:
    @staticmethod
    async def get_by_id(
        session: AsyncSession, alias_id: int
    ) -> PartnerFlightAlias | None:
        return await session.get(PartnerFlightAlias, alias_id)

    @staticmethod
    async def get_by_real(
        session: AsyncSession, partner_id: int, real_flight_name: str
    ) -> PartnerFlightAlias | None:
        result = await session.execute(
            select(PartnerFlightAlias).where(
                PartnerFlightAlias.partner_id == partner_id,
                PartnerFlightAlias.real_flight_name == real_flight_name,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_mask(
        session: AsyncSession, partner_id: int, mask_flight_name: str
    ) -> PartnerFlightAlias | None:
        result = await session.execute(
            select(PartnerFlightAlias).where(
                PartnerFlightAlias.partner_id == partner_id,
                PartnerFlightAlias.mask_flight_name == mask_flight_name,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_real_names(
        session: AsyncSession,
        partner_ids: Collection[int],
        real_flight_names: Collection[str],
    ) -> list[PartnerFlightAlias]:
        """Batch-load the aliases of many partners for many real flights.

        The real name is compared case-insensitively because ``reys`` values
        come from Sheets and are not guaranteed to share the alias's casing.
        """
        if not partner_ids or not real_flight_names:
            return []
        upper_names = {name.upper() for name in real_flight_names}
        result = await session.execute(
            select(PartnerFlightAlias).where(
                PartnerFlightAlias.partner_id.in_(partner_ids),
                func.upper(PartnerFlightAlias.real_flight_name).in_(upper_names),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def find_by_mask_any_case(
        session: AsyncSession,
        mask_flight_name: str,
        partner_id: int | None = None,
    ) -> list[PartnerFlightAlias]:
        """Case-insensitive mask lookup, across every partner when ``partner_id`` is None."""
        stmt = select(PartnerFlightAlias).where(
            func.upper(PartnerFlightAlias.mask_flight_name) == mask_flight_name.upper()
        )
        if partner_id is not None:
            stmt = stmt.where(PartnerFlightAlias.partner_id == partner_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_for_partner(
        session: AsyncSession, partner_id: int, limit: int | None = None
    ) -> list[PartnerFlightAlias]:
        stmt = (
            select(PartnerFlightAlias)
            .where(PartnerFlightAlias.partner_id == partner_id)
            .order_by(PartnerFlightAlias.id.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def count_for_partner(session: AsyncSession, partner_id: int) -> int:
        result = await session.execute(
            select(func.count(PartnerFlightAlias.id)).where(
                PartnerFlightAlias.partner_id == partner_id
            )
        )
        return int(result.scalar() or 0)

    @staticmethod
    async def create(
        session: AsyncSession,
        partner_id: int,
        real_flight_name: str,
        mask_flight_name: str,
    ) -> PartnerFlightAlias:
        alias = PartnerFlightAlias(
            partner_id=partner_id,
            real_flight_name=real_flight_name,
            mask_flight_name=mask_flight_name,
        )
        session.add(alias)
        await session.flush()
        await session.refresh(alias)
        return alias

    @staticmethod
    async def update_mask(
        session: AsyncSession,
        alias: PartnerFlightAlias,
        new_mask: str,
    ) -> PartnerFlightAlias:
        alias.mask_flight_name = new_mask
        await session.flush()
        await session.refresh(alias)
        return alias

    @staticmethod
    async def delete(session: AsyncSession, alias: PartnerFlightAlias) -> None:
        await session.delete(alias)
        await session.flush()
