"""Payment Card DAO."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
import random

from src.infrastructure.database.models.payment_card import PaymentCard


class PaymentCardDAO:
    """Data Access Object for PaymentCard."""

    @staticmethod
    async def get_all(session: AsyncSession) -> list[PaymentCard]:
        """Get all payment cards sorted by id ASC."""
        result = await session.execute(
            select(PaymentCard).order_by(PaymentCard.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_all_active(session: AsyncSession) -> list[PaymentCard]:
        """Get all active payment cards."""
        result = await session.execute(
            select(PaymentCard).where(PaymentCard.is_active == True)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_random_active(session: AsyncSession) -> PaymentCard | None:
        """Get a random active payment card."""
        active_cards = await PaymentCardDAO.get_all_active(session)
        if not active_cards:
            return None
        return random.choice(active_cards)

    @staticmethod
    async def get_by_id(session: AsyncSession, card_id: int) -> PaymentCard | None:
        """Get payment card by ID."""
        result = await session.execute(
            select(PaymentCard).where(PaymentCard.id == card_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(session: AsyncSession, data: dict) -> PaymentCard:
        """Create a new payment card."""
        card = PaymentCard(**data)
        session.add(card)
        await session.flush()
        await session.refresh(card)
        return card

    @staticmethod
    async def update(
        session: AsyncSession, card: PaymentCard, data: dict
    ) -> PaymentCard:
        """Update existing payment card."""
        for key, value in data.items():
            if hasattr(card, key):
                setattr(card, key, value)
        await session.flush()
        await session.refresh(card)
        return card

    @staticmethod
    async def delete(session: AsyncSession, card: PaymentCard) -> None:
        """Delete a payment card."""
        await session.delete(card)
        await session.flush()

    @staticmethod
    async def get_all_with_balance(session: AsyncSession) -> list[dict]:
        """
        Return all cards (active and inactive) with their collected balance.

        Balance = SUM(client_payment_events.amount) WHERE payment_card_id = card.id.
        Uses a LEFT JOIN so cards with zero payments are included (balance = 0).
        """
        from src.infrastructure.database.models.client_payment_event import ClientPaymentEvent

        query = (
            select(
                PaymentCard.id,
                PaymentCard.card_number,
                PaymentCard.full_name,
                PaymentCard.is_active,
                PaymentCard.created_at,
                func.coalesce(func.sum(ClientPaymentEvent.amount), 0).label("total_collected"),
                func.count(ClientPaymentEvent.id).label("payment_count"),
            )
            .outerjoin(ClientPaymentEvent, ClientPaymentEvent.payment_card_id == PaymentCard.id)
            .group_by(PaymentCard.id)
            .order_by(PaymentCard.is_active.desc(), PaymentCard.id.asc())
        )
        rows = (await session.execute(query)).all()
        return [
            {
                "id": row.id,
                "card_number": row.card_number,
                "full_name": row.full_name,
                "is_active": row.is_active,
                "created_at": row.created_at,
                "total_collected": float(row.total_collected),
                "payment_count": row.payment_count,
            }
            for row in rows
        ]
