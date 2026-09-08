"""Additional ``client_code`` prefixes owned by a partner.

``partners.prefix`` holds one **primary** prefix per partner, which is what
``PartnerResolver`` matched against for a long time.  Reality outgrew that:
a partner can accumulate several code families over its lifetime (a rebrand,
a merged route, a second China-side operator) while still being one brand —
one Telegram group, one card set, one ``foto_hisobot`` and, crucially, one
flight-mask namespace derived from ``partners.code``.

Every row here is an *extra* prefix routed to the same partner as its primary
one.  Resolution stays longest-prefix-match over primaries and aliases
together, so a longer alias correctly beats a shorter primary of another
partner.

A prefix that duplicates another partner's primary prefix is ambiguous and is
rejected at write time; :class:`PartnerResolver` additionally logs and ignores
such a row so a bad migration can never silently re-route live traffic.
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models.base import Base


class PartnerPrefixAlias(Base):
    __tablename__ = "partner_prefix_aliases"
    __table_args__ = (
        CheckConstraint(
            "char_length(prefix) BETWEEN 1 AND 8",
            name="ck_partner_prefix_alias_len_range",
        ),
    )

    partner_id: Mapped[int] = mapped_column(
        ForeignKey("partners.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    prefix: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    """Upper-cased ``client_code`` prefix routed to this partner."""

    partner = relationship("Partner", back_populates="prefix_aliases")

    def __repr__(self) -> str:
        return (
            f"<PartnerPrefixAlias(partner_id={self.partner_id}, "
            f"prefix={self.prefix!r})>"
        )
