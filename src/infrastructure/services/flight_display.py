"""Render a flight name for one client without leaking the real identifier.

``real_to_mask(session, 1, flight)`` used to be copy-pasted across the
payment, delivery and approval flows.  It was wrong twice over:

* ``partner_id=1`` is AKB, so a Triton (``SYT`` / ``Q``) or Navo client was
  looked up in **AKB's** alias slice and practically never matched;
* the ``or flight_name`` fallback then rendered the REAL flight name — the
  exact string the whole mask layer exists to hide.

This module is the single place that answers "which string may *this*
client see for *this* flight?".  The policy, applied everywhere a flight
name reaches an end user:

1. Resolve the client's partner from any of its ``active_codes``
   (``client_code`` / ``extra_code`` / ``legacy_code``) — an archived row
   may carry a different alias than the one the caller passed in.
2. Return the configured mask when one exists.
3. Otherwise return ``None``.  Callers then render
   :data:`FLIGHT_PLACEHOLDER` / an ordinal, or drop the flight clause
   entirely.

Step 3 never returns the real name.  That is the whole point: a missing
mask is a rendering problem, not a licence to leak.

**Rendering never writes.**  Auto-generating the missing alias here
(``FlightMaskService.ensure_mask``, as the admin review screen and
``flight_notify`` do) was tried and rejected: it turns every page view into
a write, and the flight name reaching these functions is not always a real
one.  ``normalize_flight_input`` returns unknown input unchanged, so a
user-supplied string (a payment submit body, a delivery request, a
``select_flight:`` callback) would have been persisted as a "real flight
name"; a track code shared from another partner's cargo would have written
that partner's confidential flight name into *this* partner's alias slice;
and because the generated mask is ``max(N)+1``, the value handed back would
tell a caller whether a guessed flight name already existed.  Minting stays
in the admin-initiated send flows that own their transaction and only ever
see real names — ``_partner_alias_review.build_review`` (bulk send) and
``FlightNotifySender.initialize``.  A partner whose flights predate those
flows shows placeholders until an admin creates the aliases (the alias
review screen, or ``POST /admin/partners/{id}/aliases``).

Admin-facing surfaces (the alias editor, cashier tooling) deliberately do
**not** use this module — staff work with real flight names.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.partner import Partner
from src.infrastructure.services.flight_mask import FlightMaskService
from src.infrastructure.services.partner_resolver import (
    PartnerNotFoundError,
    get_resolver,
)

logger = logging.getLogger(__name__)

FLIGHT_PLACEHOLDER = "—"
"""Inline stand-in, for sentences that already name the field ("Reys: —")."""

FLIGHT_ORDINAL_PREFIX = "Reys"
"""List entries degrade to ``Reys #1``, ``Reys #2`` … so they stay distinct."""


def _normalise_codes(client_codes: str | Iterable[str] | None) -> list[str]:
    """Accept a bare code, an ``active_codes`` list, or ``None``."""
    if not client_codes:
        return []
    candidates: Iterable[str] = (
        [client_codes] if isinstance(client_codes, str) else client_codes
    )
    codes: list[str] = []
    for raw in candidates:
        code = (raw or "").strip()
        if code and code not in codes:
            codes.append(code)
    return codes


async def resolve_partner_for_codes(
    session: AsyncSession, client_codes: str | Iterable[str] | None
) -> Partner | None:
    """Return the partner owning any of ``client_codes``, else ``None``.

    Every code is tried because a client may hold a current code plus a
    pre-conversion alias, and only one of them has to match a registered
    prefix.
    """
    resolver = get_resolver()
    for code in _normalise_codes(client_codes):
        try:
            return await resolver.resolve_by_client_code(session, code)
        except PartnerNotFoundError:
            continue
    return None


class FlightDisplay:
    """Renderer bound to one client's partner, for one request.

    Build it once per request and reuse it across a loop: the partner is
    resolved a single time and every ``real -> display`` decision is
    memoised, so a list of twenty rows costs one alias query per *distinct*
    flight instead of one per row.
    """

    __slots__ = ("_partner", "_cache")

    def __init__(self, partner: Partner | None) -> None:
        self._partner = partner
        self._cache: dict[str, str | None] = {}

    @classmethod
    async def for_client(
        cls, session: AsyncSession, client_codes: str | Iterable[str] | None
    ) -> "FlightDisplay":
        return cls(await resolve_partner_for_codes(session, client_codes))

    async def mask(
        self, session: AsyncSession, real_flight_name: str | None
    ) -> str | None:
        """Return the client-facing mask, or ``None`` when there is none.

        Never returns ``real_flight_name``.
        """
        if not real_flight_name or self._partner is None:
            return None
        if real_flight_name in self._cache:
            return self._cache[real_flight_name]

        masked = await FlightMaskService.real_to_mask(
            session, self._partner.id, real_flight_name
        )
        if masked is None:
            logger.info(
                "flight_display: partner %s has no alias for the requested "
                "flight; rendering a placeholder",
                self._partner.code,
            )
        self._cache[real_flight_name] = masked
        return masked

    async def label(
        self,
        session: AsyncSession,
        real_flight_name: str | None,
        *,
        ordinal: int | None = None,
    ) -> str:
        """Mask, or a placeholder when there is none.

        Pass ``ordinal`` (1-based) when several *distinct* flights are listed
        together so the user can still tell them apart.  Use :meth:`mask`
        instead wherever the caller can drop the flight clause altogether —
        a placeholder is only worth showing when the sentence needs a
        subject.
        """
        masked = await self.mask(session, real_flight_name)
        if masked:
            return masked
        if ordinal is None:
            return FLIGHT_PLACEHOLDER
        return f"{FLIGHT_ORDINAL_PREFIX} #{ordinal}"


async def flight_mask_for_client(
    session: AsyncSession,
    client_codes: str | Iterable[str] | None,
    real_flight_name: str | None,
) -> str | None:
    """One-off :meth:`FlightDisplay.mask` for callers with a single flight."""
    display = await FlightDisplay.for_client(session, client_codes)
    return await display.mask(session, real_flight_name)


async def flight_label_for_client(
    session: AsyncSession,
    client_codes: str | Iterable[str] | None,
    real_flight_name: str | None,
) -> str:
    """One-off :meth:`FlightDisplay.label` for callers with a single flight."""
    display = await FlightDisplay.for_client(session, client_codes)
    return await display.label(session, real_flight_name)
