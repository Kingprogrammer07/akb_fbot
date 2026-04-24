"""Payment Card Service."""
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.payment_card import PaymentCardDAO
from src.infrastructure.database.models.payment_card import PaymentCard


class PaymentCardService:
    """Service layer for PaymentCard operations."""

    async def get_random_active_card(
        self, session: AsyncSession
    ) -> PaymentCard | None:
        """Get a random active payment card for user payments."""
        return await PaymentCardDAO.get_random_active(session)

    async def get_all_active_cards(
        self, session: AsyncSession
    ) -> list[PaymentCard]:
        """Get all active payment cards."""
        return await PaymentCardDAO.get_all_active(session)

    async def create_card(
        self, session: AsyncSession, full_name: str, card_number: str
    ) -> PaymentCard:
        """Create a new payment card."""
        data = {
            "full_name": full_name,
            "card_number": card_number,
            "is_active": True
        }
        return await PaymentCardDAO.create(session, data)

    async def toggle_card_status(
        self, session: AsyncSession, card_id: int
    ) -> PaymentCard | None:
        """Toggle card active status."""
        card = await PaymentCardDAO.get_by_id(session, card_id)
        if not card:
            return None
        return await PaymentCardDAO.update(
            session, card, {"is_active": not card.is_active}
        )
