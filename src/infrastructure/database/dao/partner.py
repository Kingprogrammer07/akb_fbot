"""Data access for the Partner table.

All methods are static + session-scoped to keep ergonomics consistent with
the rest of the project (see ``payment_card.py``).  No global state.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.partner import Partner


class PartnerDAO:
    """Lookup + CRUD helpers for ``Partner``."""

    @staticmethod
    async def get_all_active(session: AsyncSession) -> list[Partner]:
        """All active partners ordered by ``code`` for stable display."""
        result = await session.execute(
            select(Partner).where(Partner.is_active.is_(True)).order_by(Partner.code.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_all(session: AsyncSession) -> list[Partner]:
        result = await session.execute(select(Partner).order_by(Partner.code.asc()))
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(session: AsyncSession, partner_id: int) -> Partner | None:
        return await session.get(Partner, partner_id)

    @staticmethod
    async def get_by_code(session: AsyncSession, code: str) -> Partner | None:
        result = await session.execute(
            select(Partner).where(Partner.code == code.strip().upper())
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_prefix(session: AsyncSession, prefix: str) -> Partner | None:
        if not prefix:
            return None
        result = await session.execute(
            select(Partner).where(Partner.prefix == prefix.strip().upper())
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(session: AsyncSession, data: dict) -> Partner:
        partner = Partner(**data)
        session.add(partner)
        await session.flush()
        await session.refresh(partner)
        return partner

    @staticmethod
    async def update(session: AsyncSession, partner: Partner, data: dict) -> Partner:
        for key, value in data.items():
            if hasattr(partner, key):
                setattr(partner, key, value)
        await session.flush()
        await session.refresh(partner)
        return partner

    @staticmethod
    async def delete(session: AsyncSession, partner: Partner) -> None:
        await session.delete(partner)
        await session.flush()
