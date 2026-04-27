"""Pydantic schemas for the Partner admin API.

Covers four resource groups:

* Partner core (read + patch).
* Per-partner payment methods (CRUD).
* Per-partner foto_hisobot (read + put).
* Per-partner flight aliases (read + patch + delete).

Schemas are split per request/response so the OpenAPI docs stay precise
and the frontend can rely on minimal payloads for PATCH operations.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

# ---------------------------------------------------------------------------
# Partner core
# ---------------------------------------------------------------------------


class PartnerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    display_name: str
    prefix: str
    group_chat_id: int | None
    is_dm_partner: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PartnerUpdate(BaseModel):
    """Partial update — only supplied fields are applied."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    group_chat_id: int | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Payment methods
# ---------------------------------------------------------------------------


PaymentMethodType = Literal["card", "link"]


class PaymentMethodRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    partner_id: int
    method_type: PaymentMethodType
    card_number: str | None
    card_holder: str | None
    link_label: str | None
    link_url: str | None
    is_active: bool
    weight: int
    created_at: datetime
    updated_at: datetime


class PaymentMethodCreate(BaseModel):
    """Create a card *or* link in one shape, validated by ``method_type``."""

    model_config = ConfigDict(extra="forbid")

    method_type: PaymentMethodType
    card_number: str | None = Field(default=None, max_length=20)
    card_holder: str | None = Field(default=None, max_length=128)
    link_label: str | None = Field(default=None, max_length=64)
    link_url: HttpUrl | None = None
    is_active: bool = True
    weight: int = Field(default=1, ge=1, le=100)

    @field_validator("card_number")
    @classmethod
    def _strip_card_number(cls, v: str | None) -> str | None:
        if v is None:
            return v
        cleaned = v.replace(" ", "").replace("-", "")
        if not cleaned.isdigit():
            raise ValueError("card_number must contain digits only")
        return cleaned

    def assert_consistent(self) -> None:
        """Ensure the supplied fields match the declared ``method_type``."""
        if self.method_type == "card":
            if not self.card_number or not self.card_holder:
                raise ValueError("card_number and card_holder are required for cards")
            if self.link_label or self.link_url:
                raise ValueError("link_* fields must be omitted for cards")
        else:  # link
            if not self.link_label or not self.link_url:
                raise ValueError("link_label and link_url are required for links")
            if self.card_number or self.card_holder:
                raise ValueError("card_* fields must be omitted for links")


class PaymentMethodUpdate(BaseModel):
    """Patch existing method.  ``method_type`` cannot be changed; create a
    new method instead.  Only supplied fields are written."""

    model_config = ConfigDict(extra="forbid")

    card_number: str | None = Field(default=None, max_length=20)
    card_holder: str | None = Field(default=None, max_length=128)
    link_label: str | None = Field(default=None, max_length=64)
    link_url: HttpUrl | None = None
    is_active: bool | None = None
    weight: int | None = Field(default=None, ge=1, le=100)


# ---------------------------------------------------------------------------
# foto_hisobot
# ---------------------------------------------------------------------------


class PartnerFotoHisobotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    partner_id: int
    foto_hisobot: str
    updated_at: datetime


class PartnerFotoHisobotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    foto_hisobot: str = Field(default="", max_length=4000)


# ---------------------------------------------------------------------------
# Flight aliases
# ---------------------------------------------------------------------------


class FlightAliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    partner_id: int
    real_flight_name: str
    mask_flight_name: str
    created_at: datetime


class FlightAliasUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mask_flight_name: str = Field(min_length=1, max_length=100)
