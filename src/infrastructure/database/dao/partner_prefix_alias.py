"""Data access for ``partner_prefix_aliases``.

Static + session-scoped, matching the other partner DAOs.  Routing logic
(longest-prefix match, conflict handling) belongs to
``services.partner_resolver.PartnerResolver``, not here.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_prefix_alias import PartnerPrefixAlias


class PartnerPrefixAliasDAO:
    """Lookup helpers for extra partner prefixes."""

    @staticmethod
    async def get_all_for_active_partners(
        session: AsyncSession,
    ) -> list[PartnerPrefixAlias]:
        """Every alias belonging to an active partner, ordered by prefix.

        Alphabetical order is not the resolution order — ``PartnerResolver``
        re-sorts by length for longest-prefix matching.  It is fixed here only
        so the cache, and the conflict log lines derived from it, stay stable
        across reloads.
        """
        result = await session.execute(
            select(PartnerPrefixAlias)
            .join(Partner, Partner.id == PartnerPrefixAlias.partner_id)
            .where(Partner.is_active.is_(True))
            .order_by(PartnerPrefixAlias.prefix.asc())
        )
        return list(result.scalars().all())
