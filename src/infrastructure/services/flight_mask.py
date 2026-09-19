"""Bidirectional flight name masking.

Layered above :mod:`partner_resolver` and the ``partner_flight_aliases``
table.  Provides four primitives:

* :meth:`real_to_mask` — render real → partner-specific mask (None when missing).
* :meth:`mask_to_real` — reverse lookup, e.g. when a cashier types a mask.
* :meth:`ensure_mask`  — atomic get-or-create with auto-generation.
* :meth:`set_mask`     — admin override; validates uniqueness.

The auto-generation rule for a brand-new mask is:
``{partner.code}{N}`` where ``N`` is one greater than the highest numeric
suffix already used by *any* mask of that partner that matches the
``^{partner.code}\\d+$`` pattern.  This produces compact, readable masks
like ``AKB1``, ``AKB2`` … while still allowing admins to enter arbitrary
strings (e.g. ``AKB-150``) for individual real flights.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.partner_flight_alias import (
    PartnerFlightAliasDAO,
)
from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_flight_alias import (
    PartnerFlightAlias,
)

logger = logging.getLogger(__name__)


class FlightMaskError(Exception):
    """Base class for flight-mask domain errors."""


class FlightMaskConflictError(FlightMaskError):
    """Raised when the requested mask is already in use by another flight."""


@dataclass(frozen=True)
class MaskPair:
    real: str
    mask: str


class FlightMaskService:
    """Stateless service — every call takes ``session`` explicitly."""

    # Auto-generation pattern: '{partner_code}{digits}'
    _AUTO_SUFFIX_RE = re.compile(r"^(?P<digits>\d+)$")

    @staticmethod
    def is_own_mask_name(partner_code: str, real_flight_name: str) -> bool:
        """Is ``real_flight_name`` already this partner's own number?

        The China import names each worksheet after the number AKB tells its
        clients, so ``cargo_items`` stores flights as ``AKB285``.  Minting a
        mask for such a name gives a flight the clients already know a second
        number — that is how ``AKB285`` reached them as ``AKB359`` — and binds
        that number to a different flight, so a cashier typing ``AKB283``
        landed on real flight ``AKB209``.

        A name in the partner's own ``CODE<digits>`` form — the form
        :meth:`_next_auto_mask` generates — is therefore shown as it is and
        never gets an alias.  It leaks nothing: the string is the partner's
        own.  For every other partner the same name is masked as usual.
        """
        code = (partner_code or "").strip().upper()
        name = (real_flight_name or "").strip().upper()
        if not code or not name.startswith(code):
            return False
        suffix = name[len(code) :]
        return suffix.isascii() and suffix.isdigit()

    # ------------------------------------------------------------------
    # Read paths
    # ------------------------------------------------------------------

    @staticmethod
    async def real_to_mask(
        session: AsyncSession, partner_id: int, real_flight_name: str
    ) -> str | None:
        alias = await PartnerFlightAliasDAO.get_by_real(
            session, partner_id, real_flight_name
        )
        return alias.mask_flight_name if alias else None

    @staticmethod
    async def mask_to_real(
        session: AsyncSession, partner_id: int, mask_flight_name: str
    ) -> str | None:
        alias = await PartnerFlightAliasDAO.get_by_mask(
            session, partner_id, mask_flight_name
        )
        return alias.real_flight_name if alias else None

    # ------------------------------------------------------------------
    # Write paths
    # ------------------------------------------------------------------

    @classmethod
    async def ensure_mask(
        cls,
        session: AsyncSession,
        partner_id: int,
        partner_code: str,
        real_flight_name: str,
    ) -> PartnerFlightAlias:
        """Get-or-create an alias for ``(partner_id, real_flight_name)``.

        Generates a default mask of ``{partner_code}{N}`` when no row exists.
        Concurrency-safe: an :class:`IntegrityError` from a parallel insert
        is caught and the resulting row is re-fetched.
        """
        existing = await PartnerFlightAliasDAO.get_by_real(
            session, partner_id, real_flight_name
        )
        if existing is not None:
            return existing

        next_mask = await cls._next_auto_mask(session, partner_id, partner_code)
        try:
            return await PartnerFlightAliasDAO.create(
                session,
                partner_id=partner_id,
                real_flight_name=real_flight_name,
                mask_flight_name=next_mask,
            )
        except IntegrityError:
            await session.rollback()
            # Another worker won the race — re-fetch the now-committed row.
            existing = await PartnerFlightAliasDAO.get_by_real(
                session, partner_id, real_flight_name
            )
            if existing is None:
                raise
            return existing

    @classmethod
    async def set_mask(
        cls,
        session: AsyncSession,
        partner_id: int,
        real_flight_name: str,
        new_mask: str,
    ) -> PartnerFlightAlias:
        """Admin override of an existing mask, or create a new one.

        Raises :class:`FlightMaskConflictError` when ``new_mask`` is already
        bound to a different real flight for the same partner.
        """
        new_mask = new_mask.strip()
        if not new_mask:
            raise FlightMaskError("mask cannot be empty")

        clash = await PartnerFlightAliasDAO.get_by_mask(
            session, partner_id, new_mask
        )
        if clash and clash.real_flight_name != real_flight_name:
            raise FlightMaskConflictError(
                f"mask {new_mask!r} is already bound to real flight "
                f"{clash.real_flight_name!r} for partner_id={partner_id}"
            )

        existing = await PartnerFlightAliasDAO.get_by_real(
            session, partner_id, real_flight_name
        )
        if existing is None:
            return await PartnerFlightAliasDAO.create(
                session,
                partner_id=partner_id,
                real_flight_name=real_flight_name,
                mask_flight_name=new_mask,
            )

        return await PartnerFlightAliasDAO.update_mask(session, existing, new_mask)

    # ------------------------------------------------------------------
    # Composite helpers
    # ------------------------------------------------------------------

    @classmethod
    async def display_flight_name(
        cls,
        session: AsyncSession,
        partner: Partner,
        real_flight_name: str,
    ) -> str:
        """The name ``partner``'s clients may see for ``real_flight_name``.

        Mints the alias when the partner has none, except for a name already
        in the partner's own numbering (:meth:`is_own_mask_name`), which is
        returned unchanged and stores nothing.  ``FlightDisplay`` makes the
        same decision when it renders to one client; this helper is for the
        admin senders that resolve one flight for whole partner groups.
        """
        if cls.is_own_mask_name(partner.code, real_flight_name):
            return real_flight_name
        alias = await cls.ensure_mask(
            session,
            partner_id=partner.id,
            partner_code=partner.code,
            real_flight_name=real_flight_name,
        )
        return alias.mask_flight_name

    @classmethod
    async def normalize_flight_input(
        cls,
        session: AsyncSession,
        partner_id: int,
        flight_query: str,
    ) -> str:
        """Translate any user-supplied flight string to its **real** name.

        Cashiers and warehouse staff may type either the real flight name
        (``M200``) or the partner-specific mask (``AKB150``).  This helper
        returns the real flight name in either case, falling back to the
        original input when no alias is configured (so behaviour is
        backward compatible with code paths that don't yet use masks).
        """
        if not flight_query:
            return flight_query
        candidate = flight_query.strip()
        # 1. Treat as mask first (faster path when mask was given).
        real = await cls.mask_to_real(session, partner_id, candidate)
        if real is not None:
            return real
        # 2. Otherwise the input is already the real name (or unknown).
        return candidate

    # ------------------------------------------------------------------
    # Auto-generation
    # ------------------------------------------------------------------

    @classmethod
    async def _next_auto_mask(
        cls, session: AsyncSession, partner_id: int, partner_code: str
    ) -> str:
        """Compute ``{partner_code}{N}`` where N = highest existing suffix + 1.

        Only masks that match the canonical ``^{partner_code}\\d+$`` form are
        considered; any admin-customised mask (e.g. ``AKB-150``) is ignored
        for counter purposes so it does not skew sequence numbering.
        """
        prefix = partner_code.upper()
        result = await session.execute(
            select(PartnerFlightAlias.mask_flight_name).where(
                PartnerFlightAlias.partner_id == partner_id,
                PartnerFlightAlias.mask_flight_name.regexp_match(rf"^{prefix}\d+$"),
            )
        )
        max_n = 0
        for (mask,) in result.all():
            tail = mask[len(prefix):]
            m = cls._AUTO_SUFFIX_RE.match(tail)
            if m:
                n = int(m.group("digits"))
                if n > max_n:
                    max_n = n
        return f"{prefix}{max_n + 1}"
