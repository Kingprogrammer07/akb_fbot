"""Opaque flight identifiers for inline-keyboard ``callback_data``.

Telegram delivers ``reply_markup`` — and therefore every ``callback_data``
payload — to the client together with the message.  A payload is not
server-side state: any tdlib/Telethon-based or modified client can read
it.  Putting the real flight name there would undo the partner mask layer
documented in :mod:`src.infrastructure.services.flight_mask`, which exists
precisely to keep names like ``M196-M197`` away from a partner's end
users, no matter how correctly the button *text* is masked.

Every user-facing keyboard therefore carries a **flight token**:

* for a client that belongs to a partner the token is the numeric id of
  the ``partner_flight_aliases`` row — the same row that supplies the mask
  rendered on the button.  The id says nothing about the real name and,
  unlike the mask string, survives an admin renaming the mask and can
  never contain the ``:`` used as callback separator;
* for a client with no partner the mask layer does not apply — such a
  client already sees real flight names everywhere — so the token is the
  real name.

:func:`resolve_flight_token` is deliberately *not* a plain inverse.  It
re-resolves the caller's own partner and refuses an alias belonging to
anyone else, so a forged payload cannot reach another partner's flight,
and a partner's client can never smuggle a raw real flight name back in
(numeric tokens only).  Callers that know which flights they offered
should also pass ``allowed`` so the answer is restricted to those.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Container, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.partner_flight_alias import (
    PartnerFlightAliasDAO,
)
from src.infrastructure.database.models.partner import Partner
from src.infrastructure.services.flight_mask import FlightMaskService
from src.infrastructure.services.partner_resolver import (
    PartnerNotFoundError,
    get_resolver,
)

# Alias ids are plain positive integers; the length cap keeps a hostile
# payload from being turned into an unbounded int.
_ALIAS_TOKEN_RE = re.compile(r"^[0-9]{1,18}$")


@dataclass(frozen=True)
class FlightRef:
    """A flight as it may be shown to, and referenced by, one client."""

    real: str
    """Authoritative flight name — never leaves the server."""

    token: str
    """Opaque value safe to embed in ``callback_data``."""

    mask: str | None
    """Partner mask for display; ``None`` when the client has no partner."""

    @property
    def display(self) -> str:
        """Mask when there is one, else the real name (no mask layer)."""
        return self.mask or self.real


def _client_codes(client) -> list[str]:
    codes = getattr(client, "active_codes", None) or []
    if isinstance(codes, str):
        codes = [codes]
    return [c for c in codes if c]


async def resolve_client_partner(
    session: AsyncSession, client
) -> Partner | None:
    """Return the partner owning any of ``client``'s codes, else ``None``."""
    resolver = get_resolver()
    for code in _client_codes(client):
        try:
            return await resolver.resolve_by_client_code(session, code)
        except PartnerNotFoundError:
            continue
    return None


async def build_flight_ref(
    session: AsyncSession, client, real_flight_name: str
) -> FlightRef:
    """Mint the display name and callback token for one real flight.

    Creates the partner alias when it is missing, so a partner's client is
    never shown — nor handed a payload containing — the real name.  The
    new row is committed because the token points at it: a rolled-back id
    would render a dead button.
    """
    real = (real_flight_name or "").strip()
    if not real:
        return FlightRef(real=real, token=real, mask=None)

    partner = await resolve_client_partner(session, client)
    if partner is None:
        return FlightRef(real=real, token=real, mask=None)

    alias = await PartnerFlightAliasDAO.get_by_real(session, partner.id, real)
    if alias is not None:
        return FlightRef(
            real=real, token=str(alias.id), mask=alias.mask_flight_name
        )

    alias = await FlightMaskService.ensure_mask(
        session,
        partner_id=partner.id,
        partner_code=partner.code,
        real_flight_name=real,
    )
    # Read before committing: a commit may expire the instance, and a
    # lazy refresh is not available on the async session.
    ref = FlightRef(real=real, token=str(alias.id), mask=alias.mask_flight_name)
    await session.commit()
    return ref


async def build_flight_refs(
    session: AsyncSession, client, real_flight_names: Iterable[str]
) -> dict[str, FlightRef]:
    """:func:`build_flight_ref` for a list, keyed by the real flight name."""
    refs: dict[str, FlightRef] = {}
    for name in real_flight_names:
        if name and name not in refs:
            refs[name] = await build_flight_ref(session, client, name)
    return refs


async def resolve_flight_token(
    session: AsyncSession,
    client,
    token: str,
    allowed: Container[str] | None = None,
) -> FlightRef | None:
    """Turn a ``callback_data`` token back into a flight for this caller.

    Returns ``None`` — never a guess — when the token is malformed, points
    at another partner's alias, or names a flight outside ``allowed``.
    """
    token = (token or "").strip()
    if not token:
        return None

    partner = await resolve_client_partner(session, client)
    if partner is None:
        ref = FlightRef(real=token, token=token, mask=None)
    else:
        # A partner's client only ever receives numeric alias tokens, so a
        # raw flight name arriving here is a forged payload.
        if not _ALIAS_TOKEN_RE.match(token):
            return None
        alias = await PartnerFlightAliasDAO.get_by_id(session, int(token))
        if alias is None or alias.partner_id != partner.id:
            return None
        ref = FlightRef(
            real=alias.real_flight_name,
            token=token,
            mask=alias.mask_flight_name,
        )

    if allowed is not None and ref.real not in allowed:
        return None
    return ref
