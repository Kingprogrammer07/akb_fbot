"""Client Payment Event database model."""
from sqlalchemy import String, Numeric, BigInteger, Integer, ForeignKey, Index, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

from src.infrastructure.database.models.base import Base
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.tools.datetime_utils import get_current_time


class ClientPaymentEvent(Base):
    """
    Client Payment Event model.
    
    Tracks individual payment events (online or cash) for a transaction.
    Each payment creates one event, preserving full payment history.
    
    This is an IMMUTABLE ledger - events are never updated, only created.
    Therefore, we exclude updated_at from the model.
    """
    
    __tablename__ = "client_payment_events"
    
    # Override created_at to ensure it's properly set
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=get_current_time,
        nullable=False,
        comment="Timestamp when payment event was created"
    )
    
    # Exclude updated_at - this is an immutable ledger
    # We do this by not mapping it (it's not in the table schema)
    __mapper_args__ = {
        "exclude_properties": ["updated_at"]
    }
    
    # Foreign key to transaction
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("client_transaction_data.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Foreign key to client_transaction_data.id"
    )
    
    # Payment type (DEPRECATED: use payment_provider instead)
    # Kept for backward compatibility only
    payment_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default='online',
        comment="DEPRECATED: Legacy field. Use payment_provider instead."
    )
    
    # Payment amount
    amount: Mapped[float] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=False,
        comment="Payment amount"
    )
    
    # Admin who approved (nullable for cash payments that may not need approval)
    approved_by_admin_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="Telegram ID of admin who approved this payment"
    )

    # Payment provider (PRIMARY SOURCE OF TRUTH)
    # This is the authoritative field for payment classification
    payment_provider: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default='cash',
        comment="Payment provider: 'cash', 'click', 'payme' (REQUIRED)"
    )
    
    # Which company card the client paid to (NULL for cash/wallet payments)
    payment_card_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("payment_cards.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Company card this payment was received on. NULL for cash/wallet.",
    )

    # Relationship to transaction
    transaction: Mapped["ClientTransaction"] = relationship(
        "ClientTransaction",
        back_populates="payment_events"
    )

    # Indexes for efficient queries
    __table_args__ = (
        Index('ix_client_payment_events_transaction_id', 'transaction_id'),
        Index('ix_client_payment_events_created_at', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return f"<ClientPaymentEvent(id={self.id}, transaction_id={self.transaction_id}, type={self.payment_type}, amount={self.amount})>"

