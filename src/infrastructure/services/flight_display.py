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
3. Otherwise create it when the caller opted into minting (see below), or
   return ``None``.  Callers then render :data:`FLIGHT_PLACEHOLDER` / an
   ordinal, or drop the flight clause entirely.

Step 3 never returns the real name.  That is the whole point: a missing
mask is a rendering problem, not a licence to leak.

**Minting is limited to names read from the client's own records.**  By
default rendering never writes: a missing alias yields ``None``.  A caller
passes ``mint_missing=True`` only when every flight name it hands to this
module was read from the client's *own* records — its database rows
(``flight_cargos``, ``cargo_items``, ``client_transaction_data``,
``expected_flight_cargos``) or the Google Sheets data fetched for its codes.
The missing alias is then created with ``FlightMaskService.ensure_mask`` in a
transaction of its own on the caller's engine and committed at once, so the
caller's session is neither committed nor rolled back, and concurrent
requests minting the same flight end up with a single alias.

A caller that may pass a user-supplied name — a request body, a query
parameter, a callback payload, typed text — must keep the default and
translate that input with ``FlightMaskService.normalize_flight_input``.
``normalize_flight_input`` returns unknown input unchanged, so minting from it
would persist an arbitrary string as a "real flight name"; a track code shared
from another partner's cargo would write that partner's confidential flight
name into *this* partner's alias slice; and because the generated mask is
``max(N)+1``, the value handed back would tell a caller whether a guessed
flight name already existed.  Aliases for flights that existed before this
rule were created by the ``d4b9e7a1c2f5`` backfill migration.

Admin-facing surfaces (the alias editor, cashier tooling) deliberately do
**not** use this module — staff work with real flight names.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from src.infrastructure.database.models.client_transaction import NON_FLIGHT_REYS_PREFIXES
from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_flight_alias import (
    PartnerFlightAlias,
)
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

_FLIGHT_ORDINAL_LABEL = re.compile(rf"{re.escape(FLIGHT_ORDINAL_PREFIX)} #([1-9][0-9]*)")


def parse_flight_ordinal(label: str) -> int | None:
    """Return ``N`` for a ``Reys #N`` list entry, else ``None``."""
    match = _FLIGHT_ORDINAL_LABEL.fullmatch(label.strip())
    return int(match.group(1)) if match else None

_MINT_ATTEMPTS = 3
"""Concurrent mints of two *different* flights for one partner can pick the
same ``max(N)+1`` mask; the loser retries and then sees the winner's row."""

_REAL_FLIGHT_NAME_MAX_LENGTH: int = (
    PartnerFlightAlias.__table__.c.real_flight_name.type.length
)
"""A longer name can never be stored as an alias, so it is never minted."""


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


def _engine_of(session: AsyncSession) -> AsyncEngine:
    """Return the engine behind ``session``, to open a transaction beside it."""
    bind = session.bind
    if isinstance(bind, AsyncConnection):
        return bind.engine
    if isinstance(bind, AsyncEngine):
        return bind
    raise TypeError(
        "flight_display: minting needs a session bound to an AsyncEngine or "
        f"an AsyncConnection, not {type(bind).__name__}"
    )


def _can_carry_alias(real_flight_name: str) -> bool:
    """Only a real flight name can carry an alias.

    Blank names and bookkeeping rows are not flights, and over-long names do
    not fit the alias column.
    """
    if not real_flight_name.strip():
        return False
    if real_flight_name.startswith(NON_FLIGHT_REYS_PREFIXES):
        return False
    if len(real_flight_name) > _REAL_FLIGHT_NAME_MAX_LENGTH:
        logger.warning(
            "flight_display: a %d-character flight name exceeds the "
            "%d-character alias column; not minting",
            len(real_flight_name),
            _REAL_FLIGHT_NAME_MAX_LENGTH,
        )
        return False
    return True


async def _mint_once(
    engine: AsyncEngine, partner: Partner, real_flight_name: str
) -> str:
    """Get-or-create the alias in a transaction of its own and commit it."""
    inserted: list[object] = []

    def _record_insert(_session: Session, instance: object) -> None:
        inserted.append(instance)

    async with AsyncSession(engine, expire_on_commit=False) as mint_session:
        # Fail fast rather than wait forever when the caller's own open
        # transaction holds a lock this INSERT needs.
        await mint_session.execute(text("SET LOCAL lock_timeout = '5s'"))
        # ``ensure_mask`` returns the row whoever created it; only a flushed
        # INSERT means this call did (a lost race never reaches persistent).
        event.listen(
            mint_session.sync_session, "pending_to_persistent", _record_insert
        )
        alias = await FlightMaskService.ensure_mask(
            mint_session,
            partner_id=partner.id,
            partner_code=partner.code,
            real_flight_name=real_flight_name,
        )
        mask = alias.mask_flight_name
        await mint_session.commit()

    if inserted:
        logger.info(
            "flight_display: minted alias %s for partner %s", mask, partner.code
        )
    return mask


async def _mint(
    session: AsyncSession, partner: Partner, real_flight_name: str
) -> str:
    """Create the missing alias without touching ``session``'s transaction."""
    engine = _engine_of(session)
    for attempt in range(1, _MINT_ATTEMPTS):
        try:
            return await _mint_once(engine, partner, real_flight_name)
        except IntegrityError:
            logger.warning(
                "flight_display: mask for partner %s collided with a concurrent "
                "mint (attempt %d of %d); retrying",
                partner.code,
                attempt,
                _MINT_ATTEMPTS,
            )
    return await _mint_once(engine, partner, real_flight_name)


class FlightDisplay:
    """Renderer bound to one client's partner, for one request.

    Build it once per request and reuse it across a loop: the partner is
    resolved a single time and every ``real -> display`` decision is
    memoised, so a list of twenty rows costs one alias query per *distinct*
    flight instead of one per row.
    """

    __slots__ = ("_partner", "_mint_missing", "_cache")

    def __init__(
        self, partner: Partner | None, *, mint_missing: bool = False
    ) -> None:
        self._partner = partner
        self._mint_missing = mint_missing
        self._cache: dict[str, str | None] = {}

    @classmethod
    async def for_client(
        cls,
        session: AsyncSession,
        client_codes: str | Iterable[str] | None,
        *,
        mint_missing: bool = False,
    ) -> "FlightDisplay":
        """Bind to the partner owning ``client_codes``.

        Pass ``mint_missing=True`` only when every name rendered afterwards
        comes from this client's own records (see the module docstring).
        """
        partner = await resolve_partner_for_codes(session, client_codes)
        return cls(partner, mint_missing=mint_missing)

    async def mask(
        self, session: AsyncSession, real_flight_name: str | None
    ) -> str | None:
        """Return the client-facing mask, or ``None`` when there is none.

        With ``mint_missing`` a missing alias is created, so ``None`` is left
        for clients without a partner and for names that cannot carry an
        alias (blank, or longer than the alias column).  Never returns
        ``real_flight_name``.
        """
        if not real_flight_name or self._partner is None:
            return None
        if real_flight_name in self._cache:
            return self._cache[real_flight_name]

        masked = await FlightMaskService.real_to_mask(
            session, self._partner.id, real_flight_name
        )
        if (
            masked is None
            and self._mint_missing
            and _can_carry_alias(real_flight_name)
        ):
            masked = await _mint(session, self._partner, real_flight_name)
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
        subject.  With ``mint_missing`` a client that has a partner gets a
        mask for every name that can carry an alias, so the placeholder and
        the ordinal remain only for clients without a partner.
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
    *,
    mint_missing: bool = False,
) -> str | None:
    """One-off :meth:`FlightDisplay.mask` for callers with a single flight."""
    display = await FlightDisplay.for_client(
        session, client_codes, mint_missing=mint_missing
    )
    return await display.mask(session, real_flight_name)


async def flight_label_for_client(
    session: AsyncSession,
    client_codes: str | Iterable[str] | None,
    real_flight_name: str | None,
    *,
    mint_missing: bool = False,
) -> str:
    """One-off :meth:`FlightDisplay.label` for callers with a single flight."""
    display = await FlightDisplay.for_client(
        session, client_codes, mint_missing=mint_missing
    )
    return await display.label(session, real_flight_name)
