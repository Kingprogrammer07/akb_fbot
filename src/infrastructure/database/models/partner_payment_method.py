"""Partner payment method — card or online payment link.

Each partner can have any number of active payment methods.  Two flavours
are supported and selected via ``method_type``:

* ``card`` — physical/virtual card.  ``card_number`` + ``card_holder`` required.
* ``link`` — online payment URL (Click, Payme, …).  ``link_label`` (display
  name) + ``link_url`` (HTTPS URL) required.

The fields for the unused flavour stay ``NULL``; a CHECK constraint enforces
that exactly the right pair is populated.

The optional ``weight`` column allows weighted random selection when
multiple cards are configured (higher weight → picked more often).
"""
from __future__ import annotations

from enum import Enum

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models.base import Base


class PartnerPaymentMethodType(str, Enum):
    CARD = "card"
    LINK = "link"


class PartnerPaymentMethod(Base):
    __tablename__ = "partner_payment_methods"
    __table_args__ = (
        CheckConstraint(
            "method_type IN ('card', 'link')",
            name="ck_ppm_method_type",
        ),
        CheckConstraint(
            "(method_type = 'card' AND card_number IS NOT NULL "
            "AND card_holder IS NOT NULL "
            "AND link_label IS NULL AND link_url IS NULL) "
            "OR (method_type = 'link' AND link_label IS NOT NULL "
            "AND link_url IS NOT NULL "
            "AND card_number IS NULL AND card_holder IS NULL)",
            name="ck_ppm_fields_match_type",
        ),
        CheckConstraint(
            "weight >= 1",
            name="ck_ppm_weight_positive",
        ),
    )

    partner_id: Mapped[int] = mapped_column(
        ForeignKey("partners.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    method_type: Mapped[str] = mapped_column(String(8), nullable=False)

    # Card fields
    card_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    card_holder: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Link fields
    link_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    weight: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    partner = relationship("Partner", back_populates="payment_methods")

    @property
    def is_card(self) -> bool:
        return self.method_type == PartnerPaymentMethodType.CARD.value

    @property
    def is_link(self) -> bool:
        return self.method_type == PartnerPaymentMethodType.LINK.value

    def __repr__(self) -> str:
        target = self.card_number if self.is_card else self.link_url
        return (
            f"<PartnerPaymentMethod(partner_id={self.partner_id}, "
            f"type={self.method_type}, target={target!r}, active={self.is_active})>"
        )
