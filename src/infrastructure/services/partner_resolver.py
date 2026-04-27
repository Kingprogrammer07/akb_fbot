"""Resolve a ``client_code`` to its owning :class:`Partner`.

The resolver is implemented as a process-wide cache keyed by the partner's
single-character ``prefix``.  The cache is populated lazily on first use
and refreshed:

* explicitly via :meth:`PartnerResolver.refresh` after partner CRUD;
* implicitly when ``resolve_by_client_code`` is called with a prefix that
  is not in the cache (so a freshly inserted partner is picked up without
  a manual refresh in long-running processes).

Threading note: aiogram + FastAPI run on a single asyncio loop, so a plain
``dict`` cache is safe.  No locking is required.
"""
from __future__ import annotations

import logging
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.partner import PartnerDAO
from src.infrastructure.database.models.partner import Partner

logger = logging.getLogger(__name__)


class PartnerNotFoundError(LookupError):
    """Raised when a ``client_code`` cannot be matched to any partner."""


class PartnerResolver:
    """Cached prefix-to-partner lookup.

    Use :func:`get_resolver` to obtain the singleton instance.
    """

    def __init__(self) -> None:
        self._by_prefix: dict[str, Partner] = {}
        self._by_code: dict[str, Partner] = {}
        # Prefixes sorted by length descending so longest-prefix-match
        # (e.g. ``GGX`` beats ``G``) is a single linear scan.
        self._prefixes_lpm: list[str] = []
        self._loaded: bool = False

    # ------------------------------------------------------------------
    # Loading / refresh
    # ------------------------------------------------------------------

    async def _load(self, session: AsyncSession) -> None:
        partners = await PartnerDAO.get_all_active(session)
        self._by_prefix = {p.prefix.upper(): p for p in partners}
        self._by_code = {p.code.upper(): p for p in partners}
        self._prefixes_lpm = sorted(
            self._by_prefix.keys(), key=len, reverse=True
        )
        self._loaded = True
        logger.debug(
            "PartnerResolver loaded %d active partner(s) with prefixes: %s",
            len(partners),
            self._prefixes_lpm,
        )

    async def refresh(self, session: AsyncSession) -> None:
        """Force-reload the cache.  Call after partner CRUD."""
        await self._load(session)

    async def _ensure_loaded(self, session: AsyncSession) -> None:
        if not self._loaded:
            await self._load(session)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve_by_client_code(
        self, session: AsyncSession, client_code: str
    ) -> Partner:
        """Return the :class:`Partner` for a given ``client_code``.

        Uses **longest-prefix matching**: the partner whose ``prefix``
        is the longest string that ``client_code`` starts with wins.
        That guarantees multi-character routes such as ``GGX`` (AKB
        Xorazm filiali) take precedence over the single-character ``G``
        when both exist.

        Raises :class:`PartnerNotFoundError` when no partner matches.
        """
        if not client_code or not client_code.strip():
            raise PartnerNotFoundError("empty client_code")

        await self._ensure_loaded(session)

        normalised = client_code.strip().upper()
        partner = self._match_lpm(normalised)
        if partner is not None:
            return partner

        # Refresh once in case the partner was added after the cache was
        # populated; this avoids permanent staleness in long-running workers.
        await self.refresh(session)
        partner = self._match_lpm(normalised)
        if partner is None:
            raise PartnerNotFoundError(
                f"no partner registered for client_code={client_code!r}"
            )
        return partner

    def _match_lpm(self, normalised_code: str) -> Partner | None:
        for prefix in self._prefixes_lpm:
            if normalised_code.startswith(prefix):
                return self._by_prefix[prefix]
        return None

    async def get_by_code(
        self, session: AsyncSession, partner_code: str
    ) -> Partner | None:
        await self._ensure_loaded(session)
        return self._by_code.get(partner_code.strip().upper())

    async def all_active(self, session: AsyncSession) -> list[Partner]:
        await self._ensure_loaded(session)
        return list(self._by_code.values())


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_resolver: Final[PartnerResolver] = PartnerResolver()


def get_resolver() -> PartnerResolver:
    """Return the process-wide :class:`PartnerResolver` instance."""
    return _resolver
