"""Data access for ``partner_payment_methods``."""
from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.partner_payment_method import (
    PartnerPaymentMethod,
    PartnerPaymentMethodType,
)


class PartnerPaymentMethodDAO:
    @staticmethod
    async def get_by_id(
        session: AsyncSession, method_id: int
    ) -> PartnerPaymentMethod | None:
        return await session.get(PartnerPaymentMethod, method_id)

    @staticmethod
    async def list_for_partner(
        session: AsyncSession,
        partner_id: int,
        only_active: bool = False,
    ) -> list[PartnerPaymentMethod]:
        stmt = (
            select(PartnerPaymentMethod)
            .where(PartnerPaymentMethod.partner_id == partner_id)
            .order_by(
                PartnerPaymentMethod.method_type.asc(),
                PartnerPaymentMethod.id.asc(),
            )
        )
        if only_active:
            stmt = stmt.where(PartnerPaymentMethod.is_active.is_(True))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_random_active_card(
        session: AsyncSession, partner_id: int
    ) -> PartnerPaymentMethod | None:
        """Weighted random pick across active *card* methods for ``partner_id``."""
        cards = [
            m
            for m in await PartnerPaymentMethodDAO.list_for_partner(
                session, partner_id, only_active=True
            )
            if m.method_type == PartnerPaymentMethodType.CARD.value
        ]
        if not cards:
            return None
        weights = [max(1, m.weight) for m in cards]
        return random.choices(cards, weights=weights, k=1)[0]

    @staticmethod
    async def list_active_links(
        session: AsyncSession, partner_id: int
    ) -> list[PartnerPaymentMethod]:
        return [
            m
            for m in await PartnerPaymentMethodDAO.list_for_partner(
                session, partner_id, only_active=True
            )
            if m.method_type == PartnerPaymentMethodType.LINK.value
        ]

    @staticmethod
    async def create(session: AsyncSession, data: dict) -> PartnerPaymentMethod:
        method = PartnerPaymentMethod(**data)
        session.add(method)
        await session.flush()
        await session.refresh(method)
        return method

    @staticmethod
    async def update(
        session: AsyncSession, method: PartnerPaymentMethod, data: dict
    ) -> PartnerPaymentMethod:
        for key, value in data.items():
            if hasattr(method, key):
                setattr(method, key, value)
        await session.flush()
        await session.refresh(method)
        return method

    @staticmethod
    async def delete(
        session: AsyncSession, method: PartnerPaymentMethod
    ) -> None:
        await session.delete(method)
        await session.flush()
