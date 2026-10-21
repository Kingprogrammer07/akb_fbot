"""Short-lived signed links to the photos of one ``flight_cargos`` row.

The External Cargo API hands these to the partner (webmandarin.uz). Its
browser shows them in ``<img>`` and its server copies them, and neither can
send the ``X-API-Key`` header, so each link carries its own proof: an HMAC
over the row id, the photo's position and an expiry. A link opens exactly one
photo until it expires; it never names a bucket key or a Telegram file id, and
it cannot be pointed at another row without the key.

The key is derived from the admin JWT secret (required and strength-checked),
with its own label so a photo link can never pass for any other signature.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from functools import lru_cache

from src.config import config

#: A link stays usable at least this long — the partner copies the photos
#: right after its worker confirms, well inside it.
LINK_TTL_SECONDS = 3600

#: Expiries snap to this grid, so one photo gets the same link for a while and
#: the browser and the partner's cache can reuse it.
LINK_BUCKET_SECONDS = 900

#: The farthest expiry a signature is accepted for.
LINK_MAX_LIFETIME_SECONDS = LINK_TTL_SECONDS + LINK_BUCKET_SECONDS

_KEY_LABEL = b"akb/external-cargo-photo/v1"


@lru_cache(maxsize=1)
def _signing_key() -> bytes:
    secret = config.api.JWT_SECRET.get_secret_value().encode("utf-8")
    return hmac.new(secret, _KEY_LABEL, hashlib.sha256).digest()


def photo_signature(cargo_id: int, index: int, expires_at: int) -> str:
    message = f"{cargo_id}.{index}.{expires_at}".encode("utf-8")
    return hmac.new(_signing_key(), message, hashlib.sha256).hexdigest()


def link_expiry(now: int | None = None) -> int:
    """The next expiry on the shared grid, at least one full TTL away."""
    moment = int(time.time()) if now is None else now
    grid = (moment // LINK_BUCKET_SECONDS + 1) * LINK_BUCKET_SECONDS
    return grid + LINK_TTL_SECONDS


def photo_link_valid(
    cargo_id: int, index: int, expires_at: int, signature: str, now: int | None = None
) -> bool:
    """Is this an unexpired link this server signed for this very photo?"""
    moment = int(time.time()) if now is None else now
    if not moment < expires_at <= moment + LINK_MAX_LIFETIME_SECONDS:
        return False
    expected = photo_signature(cargo_id, index, expires_at)
    return hmac.compare_digest(expected, signature)
