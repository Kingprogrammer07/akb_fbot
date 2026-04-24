"""Payment card model."""
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base


class PaymentCard(Base):
    """Payment card for receiving payments."""

    __tablename__ = "payment_cards"

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    card_number: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<PaymentCard(id={self.id}, card_number={self.card_number}, full_name={self.full_name})>"
