"""Partner model — first-class entity for routing cargo reports.

A partner represents one logical cargo brand/owner whose clients share a
single-character ``client_code`` prefix (``A`` → AKB, ``P`` → Navo, …).

Routing rules:
* ``is_dm_partner=True`` → cargo reports are sent as **direct messages** to the
  client's personal Telegram account (only the bot owner — AKB).
* Otherwise the report is forwarded to ``group_chat_id`` (a Telegram group
  shared with the partner staff).  ``group_chat_id`` is required when
  ``is_dm_partner=False``.

The bot itself is operated by AKB; non-DM partners receive their data via
groups they control.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models.base import Base


class Partner(Base):
    __tablename__ = "partners"
    __table_args__ = (
        CheckConstraint(
            "char_length(prefix) BETWEEN 1 AND 8",
            name="ck_partner_prefix_len_range",
        ),
    )

    code: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    """Stable identifier used in URLs/API requests, e.g. ``AKB``, ``UZ``."""

    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    """Human-readable name shown in admin UI and logs."""

    prefix: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    """``client_code`` prefix used for partner resolution.

    Single character for the standard partners (``A``, ``P``, …) but up
    to eight characters to accommodate multi-letter routes such as
    ``GGX`` (AKB Xorazm filiali).  The resolver picks the **longest
    matching prefix** so multi-char prefixes always win over single-char
    ones (see :class:`PartnerResolver`).
    """

    group_chat_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="Telegram group ID. Required when is_dm_partner=False.",
    )

    is_dm_partner: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True when reports go to the user's DM (AKB only).",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    flight_aliases = relationship(
        "PartnerFlightAlias",
        back_populates="partner",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    payment_methods = relationship(
        "PartnerPaymentMethod",
        back_populates="partner",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    static_data = relationship(
        "PartnerStaticData",
        back_populates="partner",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="joined",
    )

    def __repr__(self) -> str:
        return (
            f"<Partner(id={self.id}, code={self.code!r}, "
            f"prefix={self.prefix!r}, is_dm={self.is_dm_partner})>"
        )
