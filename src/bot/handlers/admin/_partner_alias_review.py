"""Reusable building blocks for the per-partner mask review step.

Both ``bulk_cargo_sender`` and ``flight_notify`` need the same workflow:

1. Group the clients of a freshly-selected real flight by their owning
   partner (resolved from each ``client_code``'s prefix).
2. Auto-generate or fetch a mask alias for every partner that has at least
   one client in the flight.
3. Show an inline review keyboard so the admin can confirm or override
   each mask.
4. On confirmation, dispatch the actual send using the resolved partner +
   mask information.

Centralising the logic here keeps the flow consistent across handlers and
avoids duplicated state-machine boilerplate.
"""
from __future__ import annotations

import html as html_module
import logging
from dataclasses import dataclass
from typing import Iterable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.partner import Partner
from src.infrastructure.services.flight_mask import FlightMaskService
from src.infrastructure.services.partner_resolver import (
    PartnerNotFoundError,
    get_resolver,
)

logger = logging.getLogger(__name__)


@dataclass
class PartnerSegment:
    """One slice of a flight's clients that belongs to a single partner."""

    partner: Partner
    client_codes: list[str]
    real_flight_name: str
    mask_flight_name: str

    @property
    def client_count(self) -> int:
        return len(self.client_codes)


@dataclass
class FlightAliasReview:
    """Aggregate state shown in the review UI."""

    real_flight_name: str
    segments: list[PartnerSegment]
    unresolved: list[str]
    """Client codes whose prefix did not match any registered partner."""


# ---------------------------------------------------------------------------
# Building the review state
# ---------------------------------------------------------------------------

async def build_review(
    session: AsyncSession,
    real_flight_name: str,
    client_codes: Iterable[str],
) -> FlightAliasReview:
    """Resolve every client to its partner and ensure a mask alias exists.

    The function is idempotent — re-running it on the same flight returns
    the same masks.  Auto-generation only fires for partners that don't
    have an alias for ``real_flight_name`` yet.
    """
    resolver = get_resolver()
    grouped: dict[int, list[str]] = {}
    partner_index: dict[int, Partner] = {}
    unresolved: list[str] = []

    for raw_code in client_codes:
        code = (raw_code or "").strip()
        if not code:
            continue
        try:
            partner = await resolver.resolve_by_client_code(session, code)
        except PartnerNotFoundError:
            unresolved.append(code)
            continue
        grouped.setdefault(partner.id, []).append(code)
        partner_index[partner.id] = partner

    segments: list[PartnerSegment] = []
    for partner_id, codes in grouped.items():
        partner = partner_index[partner_id]
        alias = await FlightMaskService.ensure_mask(
            session,
            partner_id=partner.id,
            partner_code=partner.code,
            real_flight_name=real_flight_name,
        )
        segments.append(
            PartnerSegment(
                partner=partner,
                client_codes=sorted(set(codes)),
                real_flight_name=real_flight_name,
                mask_flight_name=alias.mask_flight_name,
            )
        )

    # Sort by partner code for stable display.
    segments.sort(key=lambda s: s.partner.code)
    return FlightAliasReview(
        real_flight_name=real_flight_name,
        segments=segments,
        unresolved=unresolved,
    )


# ---------------------------------------------------------------------------
# Rendering the review UI
# ---------------------------------------------------------------------------

def render_review_text(review: FlightAliasReview, *, header_emoji: str = "✈️") -> str:
    """Plain-text body for the review message (HTML parse mode)."""
    safe_real = html_module.escape(review.real_flight_name)
    lines: list[str] = [
        f"{header_emoji} <b>Reys nomini moslang</b>",
        "",
        f"<b>Haqiqiy reys:</b> <code>{safe_real}</code>",
        "",
        "<b>Partner bo'yicha taqsimot:</b>",
    ]
    if not review.segments:
        lines.append("• <i>Ushbu reysda hech qaysi partnerga tegishli mijoz topilmadi.</i>")
    else:
        for seg in review.segments:
            lines.append(
                f"• <b>{html_module.escape(seg.partner.display_name)}</b> "
                f"({seg.client_count} ta mijoz) → "
                f"<code>{html_module.escape(seg.mask_flight_name)}</code>"
            )
    if review.unresolved:
        sample = ", ".join(html_module.escape(c) for c in review.unresolved[:5])
        more = "" if len(review.unresolved) <= 5 else f" (+{len(review.unresolved) - 5})"
        lines.extend(
            [
                "",
                f"⚠️ <b>{len(review.unresolved)} ta noma'lum prefiks:</b> {sample}{more}",
            ]
        )
    lines.extend(
        [
            "",
            "Maska userlarga shu nom bilan yuboriladi. ",
            "Tahrirlash uchun partnerni bosing.",
        ]
    )
    return "\n".join(lines)


def render_review_keyboard(
    review: FlightAliasReview,
    *,
    edit_callback_prefix: str,
    proceed_callback: str,
    cancel_callback: str,
) -> InlineKeyboardMarkup:
    """Build the inline keyboard for the review screen.

    Each partner row has one ``[✏ Tahrirlash]`` button.  The terminal row
    has Proceed + Cancel.  Callback data layout::

        {edit_callback_prefix}:{partner_id}
        {proceed_callback}
        {cancel_callback}
    """
    rows: list[list[InlineKeyboardButton]] = []
    for seg in review.segments:
        label = f"✏ {seg.partner.code} → {seg.mask_flight_name}"
        # Telegram caps callback_data at 64 bytes; keep label safe by trimming.
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"{edit_callback_prefix}:{seg.partner.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="✅ Davom etish", callback_data=proceed_callback),
            InlineKeyboardButton(text="❌ Bekor", callback_data=cancel_callback),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
