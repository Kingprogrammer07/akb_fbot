"""Opaque flight references for inline-keyboard ``callback_data``.

``reply_markup`` is delivered to the Telegram client together with the
message, so every ``callback_data`` payload is readable by a modified or
tdlib-based client.  A real flight name placed there undoes the partner
mask layer (:mod:`src.infrastructure.services.flight_display`) no matter
how carefully the button *text* is masked.

User keyboards therefore carry a **flight token**: the first 16 hex chars
of ``HMAC-SHA256(key, scope || 0x00 || real_flight_name)``.  The token is

* stateless — rendering a keyboard writes nothing (no alias minting, which
  ``flight_display`` explains is unsafe on render paths);
* scoped — callers pass :func:`client_token_scope` for the client the
  keyboard is shown to, so two clients (of different partners, say) see
  unrelated tokens for the same flight and cannot line up their masks by
  comparing ``callback_data``;
* not invertible without the key, which is derived from ``API_JWT_SECRET``.

Because the token is a one-way value, :func:`resolve_flight_token` can only
map it back by testing the flights the *caller* is already entitled to — the
client's own sheet flights, the flights just listed, the FSM ``worksheet`` —
under the caller's own scope.  That is the authorisation check: a forged
token, or a token copied from another client's button, matches nothing.
There is deliberately no global reverse lookup, and a raw flight name is
never accepted in place of a token: echoing a guessed name would let a
client confirm which real flight hides behind one of its masks.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterable
from functools import lru_cache

from src.config import config

FLIGHT_TOKEN_LENGTH = 16
"""Hex characters kept from the digest: 64 bits, short enough for any prefix."""

_KEY_DERIVATION_LABEL = b"akb:flight-callback-token:v1"
_SCOPE_SEPARATOR = "\x00"


@lru_cache(maxsize=1)
def _token_key() -> bytes:
    """Derive the token key once; never log or expose the result."""
    secret = config.api.JWT_SECRET.get_secret_value().encode("utf-8")
    return hmac.new(secret, _KEY_DERIVATION_LABEL, hashlib.sha256).digest()


def client_token_scope(client_id: int) -> str:
    """Scope for tokens rendered to, and resolved for, one client account."""
    return f"client:{client_id}"


def _scope_prefix(scope: str) -> bytes:
    """HMAC message prefix for ``scope``.

    The scope may not contain the separator, so the first separator in a
    message always ends the scope and ``(scope, name)`` pairs cannot collide.
    """
    if not scope or _SCOPE_SEPARATOR in scope:
        raise ValueError("flight token scope must be non-empty and contain no NUL")
    return f"{scope}{_SCOPE_SEPARATOR}".encode("utf-8")


def _digest(scope_prefix: bytes, real_flight_name: str) -> str:
    message = scope_prefix + real_flight_name.strip().encode("utf-8")
    digest = hmac.new(_token_key(), message, hashlib.sha256).hexdigest()
    return digest[:FLIGHT_TOKEN_LENGTH]


def flight_token(real_flight_name: str, scope: str) -> str:
    """Return the ``callback_data`` token for ``real_flight_name`` in ``scope``."""
    return _digest(_scope_prefix(scope), real_flight_name)


def resolve_flight_token(
    token: str, allowed_real_flight_names: Iterable[str], scope: str
) -> str | None:
    """Return the allowed flight ``token`` was minted for in ``scope``, else ``None``.

    Names are compared with surrounding whitespace removed, but the element
    is returned exactly as given: sheet titles and ``flight_cargos`` rows can
    carry that whitespace, and DAO lookups match the stored value untrimmed.
    """
    prefix = _scope_prefix(scope)
    candidate = token.strip().encode("utf-8")
    if not candidate:
        return None

    for name in allowed_real_flight_names:
        if not name or not name.strip():
            continue
        if hmac.compare_digest(_digest(prefix, name).encode("ascii"), candidate):
            return name
    return None
