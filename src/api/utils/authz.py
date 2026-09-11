"""Authorization helpers shared by the API routers.

Endpoints that take a ``client_code`` from the URL must prove the caller owns
that code — the codes are short and predictable (``A02-14``, ``SYT700``), so an
unchecked path parameter is a trivially enumerable IDOR.
"""
from fastapi import HTTPException, status

from src.infrastructure.database.models.client import Client


def assert_owns_client_code(current_user: Client, requested_code: str) -> None:
    """Raise 403 unless ``requested_code`` is one of the caller's own codes.

    ``Client.active_codes`` is the single source of truth: it already returns
    every alias of one account (``extra_code``, ``client_code``,
    ``legacy_code``), uppercased and deduplicated. Archived rows were written
    under whichever alias the scan tooling knew at the time, so all of them
    have to grant access.

    Why raise rather than silently return empty data: an empty response for
    someone else's valid code would still leak existence information ("this
    code has no cargo") while remaining an authorization bypass.
    """
    if (requested_code or "").strip().upper() not in set(current_user.active_codes):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: this data does not belong to your account.",
        )
