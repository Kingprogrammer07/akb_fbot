"""Secret token that authenticates Telegram's calls to ``POST /webhook``.

The webhook endpoint is reachable from the internet, and the bot's admin
filters trust ``update.from_user.id``.  Without a shared secret, anyone who
knows an admin's Telegram id could post a forged update and act as that admin.
Telegram echoes the ``secret_token`` passed to ``setWebhook`` in the
:data:`WEBHOOK_SECRET_HEADER` header of every webhook request, so the handler
only accepts requests that carry it.

The secret is derived from the bot token instead of being a separate setting:

* nothing new has to be provisioned for a deploy — whoever holds the token
  already controls the bot, so it is the natural root for this secret;
* rotating the token rotates the secret, because start-up re-registers the
  webhook with the value derived from the new token;
* the HMAC is one-way, so the header value Telegram sends reveals nothing
  about the token.
"""

import hashlib
import hmac

WEBHOOK_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
"""Header in which Telegram sends the ``secret_token`` given to ``setWebhook``."""

_DERIVATION_LABEL = b"akb:telegram-webhook-secret:v1"


def webhook_secret_token(bot_token: str) -> str:
    """Return the webhook secret for ``bot_token``; never log the result.

    The value is the lowercase hex HMAC-SHA256 of a versioned label keyed by
    the token: 64 characters, well inside Telegram's limit of 1-256 characters
    from ``A-Z a-z 0-9 _ -``.
    """
    return hmac.new(bot_token.encode(), _DERIVATION_LABEL, hashlib.sha256).hexdigest()
