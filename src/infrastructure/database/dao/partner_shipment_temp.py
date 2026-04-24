"""DAO for PartnerShipmentTemp."""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.partner_shipment_temp import PartnerShipmentTemp


class PartnerShipmentTempDAO:
    """Data Access Object for PartnerShipmentTemp."""

    @staticmethod
    async def create(session: AsyncSession, data: dict) -> PartnerShipmentTemp:
        """Create a new temporary shipment record."""
        record = PartnerShipmentTemp(**data)
        session.add(record)
        await session.flush()
        await session.refresh(record)
        return record

    @staticmethod
    async def get_by_track_code(
        session: AsyncSession, track_code: str
    ) -> Optional[PartnerShipmentTemp]:
        """Get a record by track code."""
        query = select(PartnerShipmentTemp).where(
            PartnerShipmentTemp.track_code == track_code
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(
        session: AsyncSession, limit: int = 50, offset: int = 0
    ) -> list[PartnerShipmentTemp]:
        """Get a list of all temporary shipment records."""
        query = (
            select(PartnerShipmentTemp)
            .order_by(PartnerShipmentTemp.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(query)
        return list(result.scalars().all())
