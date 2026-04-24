"""User payment card model."""
from sqlalchemy import String, Boolean, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base


class UserPaymentCard(Base):
    """User's saved payment card for refunds."""

    __tablename__ = "user_payment_cards"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )
    card_number: Mapped[str] = mapped_column(
        String(19), nullable=False
    )
    holder_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    def __repr__(self) -> str:
        last4 = self.card_number[-4:] if self.card_number else "????"
        return f"<UserPaymentCard(id={self.id}, telegram_id={self.telegram_id}, card=****{last4})>"
