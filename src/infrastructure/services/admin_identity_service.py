"""
Admin identity: which admin account a request or a bot action belongs to.

Live account state for JWT authentication
-----------------------------------------
An Admin JWT is valid for ``API_JWT_EXPIRE_MINUTES`` (8 hours by default) and
carries a frozen snapshot of the admin's role.  Signature and expiry checks
alone therefore cannot tell whether the account has since been deactivated,
demoted or deleted.

:class:`AdminIdentityService` resolves the *current* identity from the database
on every request, backed by a short-lived Redis cache so the extra correctness
costs at most one query per admin per :data:`IDENTITY_TTL` seconds.  Mutation
endpoints call :meth:`AdminIdentityService.invalidate` so a change takes effect
on the next request rather than after the TTL.

Telegram id and AdminAccount PK
-------------------------------
The project addresses admins by two different ids:

* **Telegram id** — what aiogram handlers see (``message.from_user.id``).
* **AdminAccount PK** — ``admin_accounts.id``, what the Admin JWT carries
  (``AdminJWTPayload.admin_id``) and what audit columns store.

Audit columns such as ``client_payment_events.approved_by_admin_id`` are defined
in the **AdminAccount PK** namespace, because that is what the RBAC layer and the
cashier-log queries filter on.  Bot handlers must therefore translate before
writing, with :func:`resolve_admin_pk_by_telegram_id`.
"""
import json
import logging
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.cache.keys import CacheKeys
from src.infrastructure.database.dao.admin_account import AdminAccountDAO

logger = logging.getLogger(__name__)

# Bounded staleness for an identity that is never explicitly invalidated (for
# example a role renamed directly in the database).  Every known mutation path
# invalidates the key outright, so this is a safety net, not the main mechanism.
IDENTITY_TTL = 45

# Tokens for accounts that no longer exist are cached too, otherwise anyone
# holding a stale-but-signed token could force a database query per request.
MISSING_IDENTITY_TTL = 15

# Lifetime of the per-admin version counter. It only has to outlive the cached
# entries that reference it, so any value comfortably above IDENTITY_TTL works;
# expiring it merely costs one extra database read.
IDENTITY_VERSION_TTL = 3600


@dataclass(frozen=True, slots=True)
class AdminIdentity:
    """The authorisation-relevant state of an admin account, as stored today."""

    admin_id: int
    is_active: bool
    role_name: str


class AdminIdentityService:
    """Reads current admin identity through a short-lived Redis cache."""

    @staticmethod
    async def get(
        redis: Redis,
        session: AsyncSession,
        admin_id: int,
    ) -> AdminIdentity | None:
        """
        Return the admin's current identity, or ``None`` if no such account
        exists.  Callers must treat ``None`` and ``is_active is False`` as
        authentication failures.
        """
        cache_key = CacheKeys.admin_identity(admin_id)
        version_key = CacheKeys.admin_identity_version(admin_id)

        # Read both in one round trip so the entry is compared against the
        # version it was actually stored under.
        cached, raw_version = await redis.mget(cache_key, version_key)
        version = AdminIdentityService._parse_version(raw_version)

        if cached is not None:
            payload = AdminIdentityService._decode(cached)
            # A stale version means the entry was written by a request that
            # started before a revocation; a malformed entry is not trusted at
            # all.  Either way, fall through to the database.
            if payload is not None and payload.get("v") == version:
                if not payload.get("exists"):
                    return None
                role_name = payload.get("role_name")
                if isinstance(role_name, str):
                    return AdminIdentity(
                        admin_id=admin_id,
                        is_active=bool(payload.get("is_active")),
                        role_name=role_name,
                    )

        account = await AdminAccountDAO.get_by_id_with_relations(session, admin_id)

        if account is None:
            await redis.setex(
                cache_key,
                MISSING_IDENTITY_TTL,
                json.dumps({"v": version, "exists": False}),
            )
            return None

        identity = AdminIdentity(
            admin_id=admin_id,
            is_active=bool(account.is_active),
            role_name=account.role_name,
        )
        await redis.setex(
            cache_key,
            IDENTITY_TTL,
            json.dumps(
                {
                    "v": version,
                    "exists": True,
                    "is_active": identity.is_active,
                    "role_name": identity.role_name,
                }
            ),
        )
        return identity

    @staticmethod
    async def invalidate(redis: Redis, admin_id: int) -> None:
        """
        Force the next request to re-read this admin's identity from the
        database.  Call it immediately after changing an admin's active status,
        role or existence.

        The version counter is bumped *before* the entry is dropped: a
        concurrent request that already read the old state can still write its
        snapshot afterwards, but it will carry the superseded version and be
        ignored rather than silently restoring revoked access.
        """
        version_key = CacheKeys.admin_identity_version(admin_id)

        await redis.incr(version_key)
        await redis.expire(version_key, IDENTITY_VERSION_TTL)
        await redis.delete(CacheKeys.admin_identity(admin_id))

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _decode(raw: str | bytes) -> dict | None:
        """Parse a cache entry, tolerating both decoded and raw Redis clients."""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("Discarding malformed admin identity cache entry")
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _parse_version(raw: str | bytes | int | None) -> int:
        """An absent or unreadable counter is treated as generation zero."""
        if raw is None:
            return 0
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return int(raw)
        except (ValueError, TypeError):
            logger.warning("Discarding malformed admin identity version counter")
            return 0


async def resolve_admin_pk_by_telegram_id(
    session: AsyncSession,
    telegram_id: int | None,
) -> int | None:
    """
    Translate a Telegram user id into the AdminAccount primary key.

    Use this before writing any audit column that stores an AdminAccount PK from
    a bot handler.  Storing the raw Telegram id instead would put two id
    namespaces in one column and make cashier-log filtering silently wrong.

    Returns ``None`` when the id cannot be resolved (no ``from_user``, or a
    Telegram admin with no ``admin_accounts`` row — ``is_admin_by_telegram_id``
    also grants access via config ``ADMIN_ACCESS_IDs`` and legacy
    ``clients.role``, neither of which creates one).  ``None`` is deliberate: a
    NULL reads as "no admin account", whereas a Telegram id written into a PK
    column reads as *some other admin*.

    Callers writing an audit row must pass the raw Telegram id alongside, into
    ``approved_by_telegram_id``, so the operator stays identifiable when this
    returns ``None``.
    """
    if not telegram_id:
        return None

    admin_pk = await AdminAccountDAO.get_id_by_telegram_id(session, telegram_id)

    if admin_pk is None:
        logger.warning(
            "No admin_accounts row for telegram_id=%s; approved_by_admin_id "
            "will be NULL, so this action is excluded from per-cashier log "
            "filters (the operator remains identified by "
            "approved_by_telegram_id). Create an admin account for this "
            "operator to restore them to the cashier log.",
            telegram_id,
        )

    return admin_pk
