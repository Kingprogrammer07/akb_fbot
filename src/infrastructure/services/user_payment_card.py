"""User Payment Card Service."""
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.user_payment_card import UserPaymentCardDAO
from src.infrastructure.database.models.user_payment_card import UserPaymentCard


class UserPaymentCardService:
    """Service layer for user payment card operations."""

    @staticmethod
    async def get_user_cards(
        telegram_id: int, session: AsyncSession
    ) -> list[UserPaymentCard]:
        """Get all active cards for a user."""
        return await UserPaymentCardDAO.get_active_by_telegram_id(session, telegram_id)

    @staticmethod
    async def create_card(
        telegram_id: int,
        card_number: str,
        holder_name: str | None,
        session: AsyncSession
    ) -> UserPaymentCard:
        """Create a new user card."""
        return await UserPaymentCardDAO.create(session, {
            'telegram_id': telegram_id,
            'card_number': card_number,
            'holder_name': holder_name,
            'is_active': True,
        })

    @staticmethod
    async def deactivate_card(
        card_id: int, telegram_id: int, session: AsyncSession
    ) -> UserPaymentCard | None:
        """Deactivate a card with ownership check."""
        card = await UserPaymentCardDAO.get_by_id(session, card_id)
        if card and card.telegram_id == telegram_id:
            return await UserPaymentCardDAO.deactivate(session, card_id)
        return None

    @staticmethod
    async def delete_card(
        card_id: int, telegram_id: int, session: AsyncSession
    ) -> bool:
        """Delete a card with ownership check."""
        card = await UserPaymentCardDAO.get_by_id(session, card_id)
        if card and card.telegram_id == telegram_id:
            await UserPaymentCardDAO.delete(session, card)
            return True
        return False
