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
    
    # Admin who booked this payment.
    #
    # ID NAMESPACE — this column holds an ``admin_accounts.id`` (the AdminAccount
    # DB primary key), NOT a Telegram ID.  Every reader depends on this:
    # ``ClientPaymentEventDAO`` filters the cashier log with
    # ``approved_by_admin_id == AdminJWTPayload.admin_id``, and both
    # ``GET /payments/cashier-log`` and ``GET /payments/all-cashier-logs``
    # surface the value as ``cashier_id``.
    #
    # WRITERS must supply a verified identity:
    #   • HTTP  — ``AdminJWTPayload.admin_id`` from ``require_permission(...)``.
    #             Never a value taken from a request body.
    #   • Bot   — ``resolve_admin_pk_by_telegram_id()`` maps the aiogram
    #             ``from_user.id`` to the AdminAccount PK; it returns ``None``
    #             when the Telegram user has no admin account, and NULL is
    #             stored rather than a foreign-namespace id.
    #
    # NULL means "no AdminAccount owns this payment".  That is a real case, not
    # a defect: ``is_admin_by_telegram_id`` also grants bot admin rights via
    # ``config.telegram.ADMIN_ACCESS_IDs`` and via legacy ``clients.role``,
    # neither of which requires an ``admin_accounts`` row.  For those operators
    # the identity is preserved in ``approved_by_telegram_id`` below, so a NULL
    # here never means "unknown actor".
    #
    # Revision ``a1c2e3f4b5d6`` guarantees the invariant for historical rows:
    # every value is either an ``admin_accounts.id`` or NULL.  Nothing else.
    #
    # BigInteger (not Integer) is kept deliberately: it is the existing column
    # type, it still fits the PK range, and narrowing it would need a table
    # rewrite for no functional gain.
    #
    # There is intentionally no FK to ``admin_accounts``: admin accounts are hard
    # deleted (``DELETE /system-admins/admin-accounts/{id}``), so a FK would
    # either block that deletion or, with ON DELETE SET NULL, erase attribution
    # from what is meant to be an immutable ledger.  Integrity is enforced at the
    # write sites listed above.
    approved_by_admin_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment=(
            "AdminAccount DB primary key (admin_accounts.id) of the admin who "
            "booked this payment. NOT a Telegram ID. NULL = no admin account; "
            "see approved_by_telegram_id."
        ),
    )

    # Raw Telegram id of the operator, for bot-initiated payments.
    #
    # Companion to ``approved_by_admin_id``, deliberately a separate column
    # rather than a second meaning for the same one — that overloading is the
    # bug revision ``a1c2e3f4b5d6`` exists to undo.
    #
    # Populated by the aiogram handlers, which know ``from_user.id`` but may not
    # have an ``admin_accounts`` row to map it to.  It is what keeps a cash
    # payment attributable to a human when ``approved_by_admin_id`` is NULL.
    # NULL for HTTP-booked payments, where the JWT already yields the
    # AdminAccount PK and no Telegram identity is involved.
    #
    # Not an access-control field and never used for filtering: the cashier log
    # keys on the AdminAccount PK.  This column exists so the audit trail
    # survives an operator who was never enrolled in RBAC.
    approved_by_telegram_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment=(
            "Telegram user ID of the operator who booked this payment via the "
            "bot. NULL for HTTP-booked payments. Audit-only, never filtered on."
        ),
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

