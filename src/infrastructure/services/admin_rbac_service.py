import logging
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.cache.keys import CacheKeys
from src.infrastructure.database.models.role import Role

logger = logging.getLogger(__name__)

# Cache permissions for 5 minutes. RBAC doesn't need to be strictly real-time 
# since admin actions are relatively short-lived endpoints, but 5m is a good balance.
PERMISSIONS_TTL = 300 


class RBACService:
    """Service to handle Role-Based Access Control and caching."""

    @staticmethod
    async def get_permissions(redis: Redis, session: AsyncSession, role_name: str) -> set[str]:
        """
        Get the set of flattened permissions (e.g., {'finance:read', 'finance:write'})
        for a given role name. Uses Redis.
        """
        # "super-admin" has implicit full access; skip checking Redis/DB
        if role_name == "super-admin":
            return set()

        cache_key = CacheKeys.role_permissions(role_name)
        cached_perms = await redis.smembers(cache_key)
        
        if cached_perms:
            # Redis connections configured with decode_responses=True already return
            # str; connections without it return bytes. Handle both defensively.
            return {p.decode('utf-8') if isinstance(p, bytes) else p for p in cached_perms}

        # Cache miss, fetch from database
        query = (
            select(Role)
            .where(Role.name == role_name)
        )
        result = await session.execute(query)
        role = result.scalar_one_or_none()
        
        if not role:
            logger.warning(f"RBAC lookup failed: role {role_name!r} not found.")
            return set()

        # Build list of "resource:action" strings
        perms_set = {perm.slug for perm in role.permissions}
        
        # SADD and EXPIRE in one MULTI/EXEC transaction, so a failure between
        # two round trips can never leave the set without its TTL.
        if perms_set:
            async with redis.pipeline(transaction=True) as pipe:
                pipe.sadd(cache_key, *perms_set)
                pipe.expire(cache_key, PERMISSIONS_TTL)
                await pipe.execute()
            
        return perms_set

    @staticmethod
    async def invalidate_role(redis: Redis, role_name: str) -> None:
        """
        Clear cached permissions for a role. 
        Call this immediately after editing a role's permissions in the DB.

        Callers invalidate after committing, so a Redis failure is logged, not
        raised: raising would report an error for a change that is already
        saved, while the stale entry still expires within PERMISSIONS_TTL.
        """
        cache_key = CacheKeys.role_permissions(role_name)
        try:
            await redis.delete(cache_key)
        except RedisError:
            logger.warning(
                "Could not invalidate the cached permissions of role %r; they "
                "may stay stale for up to %s seconds",
                role_name,
                PERMISSIONS_TTL,
                exc_info=True,
            )
