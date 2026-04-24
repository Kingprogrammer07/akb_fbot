"""CargoDeliveryProof — immutable record of a warehouse take-away event.

Every time a warehouse worker marks a transaction as taken-away they must
supply a delivery method and one or more proof photos.  This table stores
the S3 keys for those photos alongside the delivery method so the evidence
can never be lost even if the transaction record is later modified.

Design decisions:
- No ``updated_at`` — delivery proofs are append-only evidence; mutating
  them would undermine their purpose.
- ``marked_by_admin_id`` uses SET NULL on delete so proof records survive
  even if the admin account is later removed.
- ``photo_s3_keys`` is a JSON array of S3 object keys, e.g.
  ``["warehouse/42/abc123.webp", "warehouse/42/def456.webp"]``.
"""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models.base import Base

if TYPE_CHECKING:
    from src.infrastructure.database.models.client_transaction import ClientTransaction
    from src.infrastructure.database.models.admin_account import AdminAccount


class CargoDeliveryProof(Base):
    """Immutable proof record for a warehouse take-away action."""

    __tablename__ = "cargo_delivery_proofs"

    transaction_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("client_transaction_data.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="The transaction (cargo row) that was taken away",
    )
    delivery_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Delivery method chosen by the warehouse worker: uzpost|bts|akb|yandex",
    )
    photo_s3_keys: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="JSON array of S3 object keys for proof photos",
    )
    marked_by_admin_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="AdminAccount that performed the take-away marking",
    )

    # Relationships (lazy by default — load explicitly when needed)
    transaction: Mapped["ClientTransaction"] = relationship(
        "ClientTransaction", foreign_keys=[transaction_id], lazy="select"
    )
    marked_by: Mapped["AdminAccount | None"] = relationship(
        "AdminAccount", foreign_keys=[marked_by_admin_id], lazy="select"
    )
