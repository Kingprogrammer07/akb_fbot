"""Partner-specific flight name alias (mask).

The DB always stores the *real* flight name (e.g. ``M200``) on
``flight_cargos.flight_name`` and ``client_transactions.reys``.  When a
report is delivered to a partner's clients, the real name is replaced by
the partner-specific mask (e.g. AKB → ``AKB150``, Uztez → ``UZTEZ-101``)
to keep the underlying flight identity confidential.

This table is the single source of truth for the bidirectional mapping:

* ``mask_to_real(partner_id, mask)`` — when a user/cashier types a mask name.
* ``real_to_mask(partner_id, real)`` — when rendering a message to a user.

Both columns are unique within a partner so each direction is a true
function (no ambiguity).
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models.base import Base


class PartnerFlightAlias(Base):
    __tablename__ = "partner_flight_aliases"
    __table_args__ = (
        UniqueConstraint(
            "partner_id", "real_flight_name",
            name="uq_pfa_partner_real",
        ),
        UniqueConstraint(
            "partner_id", "mask_flight_name",
            name="uq_pfa_partner_mask",
        ),
        Index("ix_pfa_partner_mask", "partner_id", "mask_flight_name"),
        Index("ix_pfa_partner_real", "partner_id", "real_flight_name"),
    )

    partner_id: Mapped[int] = mapped_column(
        ForeignKey("partners.id", ondelete="CASCADE"),
        nullable=False,
    )

    real_flight_name: Mapped[str] = mapped_column(String(100), nullable=False)
    """Authoritative flight name as stored in flight_cargos / Sheets."""

    mask_flight_name: Mapped[str] = mapped_column(String(100), nullable=False)
    """Partner-facing mask shown to end users."""

    partner = relationship("Partner", back_populates="flight_aliases")

    def __repr__(self) -> str:
        return (
            f"<PartnerFlightAlias(partner_id={self.partner_id}, "
            f"real={self.real_flight_name!r}, mask={self.mask_flight_name!r})>"
        )
