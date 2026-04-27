"""Per-partner static configuration.

The global ``StaticData`` singleton (``static_data`` table) keeps values
that are uniform across all partners — ``extra_charge``, ``price_per_kg``,
USD rate overrides, and so on.  A few values, however, must vary per
partner so that each partner's branding/footnote is delivered correctly.

For Phase 1 the only per-partner override is ``foto_hisobot`` — the
free-form footer text appended to every cargo report message.  Future
extensions can add columns here without touching the global ``StaticData``.

The row is created together with the partner; a small one-to-one
relationship via ``partner_id`` PK keeps lookups trivial and avoids the
need for a separate id column.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models.base import Base
from src.infrastructure.tools.datetime_utils import get_current_time


class PartnerStaticData(Base):
    __tablename__ = "partner_static_data"

    # The Base id column is unused here — partner_id is the natural PK.
    # We keep Base.id for consistency but enforce uniqueness on partner_id.
    partner_id: Mapped[int] = mapped_column(
        ForeignKey("partners.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    foto_hisobot: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="Footer text appended to bulk cargo report messages.",
    )

    updated_at: Mapped[datetime] = mapped_column(  # type: ignore[assignment]
        TIMESTAMP(timezone=True),
        default=get_current_time,
        onupdate=get_current_time,
        nullable=False,
    )

    partner = relationship("Partner", back_populates="static_data")

    def __repr__(self) -> str:
        preview = (self.foto_hisobot or "")[:40]
        return f"<PartnerStaticData(partner_id={self.partner_id}, foto_hisobot={preview!r})>"
