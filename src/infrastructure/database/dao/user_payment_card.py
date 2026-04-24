"""User Payment Card DAO."""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.user_payment_card import UserPaymentCard


class UserPaymentCardDAO:
    """Data Access Object for UserPaymentCard."""

    @staticmethod
    async def get_by_telegram_id(
        session: AsyncSession, telegram_id: int
    ) -> list[UserPaymentCard]:
        """Get all cards for a user."""
        result = await session.execute(
            select(UserPaymentCard)
            .where(UserPaymentCard.telegram_id == telegram_id)
            .order_by(UserPaymentCard.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_active_by_telegram_id(
        session: AsyncSession, telegram_id: int
    ) -> list[UserPaymentCard]:
        """Get only active cards for a user."""
        result = await session.execute(
            select(UserPaymentCard)
            .where(
                UserPaymentCard.telegram_id == telegram_id,
                UserPaymentCard.is_active == True
            )
            .order_by(UserPaymentCard.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(
        session: AsyncSession, card_id: int
    ) -> UserPaymentCard | None:
        """Get card by ID."""
        result = await session.execute(
            select(UserPaymentCard).where(UserPaymentCard.id == card_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession, data: dict
    ) -> UserPaymentCard:
        """Create a new user payment card."""
        card = UserPaymentCard(**data)
        session.add(card)
        await session.flush()
        await session.refresh(card)
        return card

    @staticmethod
    async def deactivate(
        session: AsyncSession, card_id: int
    ) -> UserPaymentCard | None:
        """Deactivate a card."""
        result = await session.execute(
            select(UserPaymentCard).where(UserPaymentCard.id == card_id)
        )
        card = result.scalar_one_or_none()
        if card:
            card.is_active = False
            await session.flush()
        return card

    @staticmethod
    async def delete(
        session: AsyncSession, card: UserPaymentCard
    ) -> None:
        """Delete a card."""
        await session.delete(card)
        await session.flush()

    @staticmethod
    async def count_active_by_telegram_id(
        session: AsyncSession, telegram_id: int
    ) -> int:
        """Count active cards for a user."""
        result = await session.execute(
            select(func.count(UserPaymentCard.id))
            .where(
                UserPaymentCard.telegram_id == telegram_id,
                UserPaymentCard.is_active == True
            )
        )
        return result.scalar_one()

    @staticmethod
    async def check_duplicate(
        session: AsyncSession, telegram_id: int, card_number: str
    ) -> bool:
        """Check if user already has this card number."""
        result = await session.execute(
            select(UserPaymentCard).where(
                UserPaymentCard.telegram_id == telegram_id,
                UserPaymentCard.card_number == card_number,
                UserPaymentCard.is_active == True
            )
        )
        return result.scalar_one_or_none() is not None
