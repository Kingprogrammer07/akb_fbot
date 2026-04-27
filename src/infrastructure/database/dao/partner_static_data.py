"""Data access for ``partner_static_data``.

The row is auto-created at partner creation time (via the seeding migration
or admin endpoint).  ``get_or_create`` is provided for defensive lookups
from runtime code paths that should never fail when a partner exists but
its static data row is missing for any reason.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.partner_static_data import PartnerStaticData


class PartnerStaticDataDAO:
    @staticmethod
    async def get_for_partner(
        session: AsyncSession, partner_id: int
    ) -> PartnerStaticData | None:
        result = await session.execute(
            select(PartnerStaticData).where(
                PartnerStaticData.partner_id == partner_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_or_create(
        session: AsyncSession, partner_id: int
    ) -> PartnerStaticData:
        existing = await PartnerStaticDataDAO.get_for_partner(session, partner_id)
        if existing is not None:
            return existing
        record = PartnerStaticData(partner_id=partner_id, foto_hisobot="")
        session.add(record)
        await session.flush()
        await session.refresh(record)
        return record

    @staticmethod
    async def update_foto_hisobot(
        session: AsyncSession, partner_id: int, foto_hisobot: str
    ) -> PartnerStaticData:
        record = await PartnerStaticDataDAO.get_or_create(session, partner_id)
        record.foto_hisobot = foto_hisobot
        await session.flush()
        await session.refresh(record)
        return record
