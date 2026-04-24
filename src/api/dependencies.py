"""FastAPI dependencies."""
import logging
from typing import AsyncGenerator, Callable
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from fastapi import Request, Header, Depends, HTTPException, status
from src.bot.utils.i18n import i18n, get_user_language
from src.infrastructure.database.models.client import Client

logger = logging.getLogger(__name__)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    db_client = request.app.state.db_client

    if not db_client:
        raise RuntimeError("Database client not initialized")

    async with db_client.session_factory() as session:
        yield session


async def get_redis(request: Request) -> Redis:
    """Get Redis connection from app state."""
    redis = request.app.state.redis

    if not redis:
        raise RuntimeError("Redis not initialized")

    return redis


def get_translator(accept_language: str | None = Header(None, alias="Accept-Language")) -> Callable[[str, dict], str]:
    """
    Get translator function based on Accept-Language header.

    Default language is Uzbek (uz).
    Frontend can send Accept-Language header (e.g., "ru", "uz") to get responses in that language.
    """
    language = get_user_language(accept_language) if accept_language else "uz"

    def translator(key: str, **kwargs) -> str:
        return i18n.get(language, key, **kwargs)

    return translator


# ---------------------------------------------------------------------------
# Session constants
# ---------------------------------------------------------------------------
SESSION_PREFIX = "session:"
SESSION_TTL_SECONDS = 86400  # 24 hours


# ---------------------------------------------------------------------------
# Internal auth helpers (private – not imported by routers)
# ---------------------------------------------------------------------------

async def _authenticate_bearer(
    auth_header: str,
    redis: Redis,
    session: AsyncSession,
) -> "Client":
    """
    Validate a Bearer token against Redis and return the Client ORM object.

    Refreshes the TTL on every successful access (sliding window).
    """
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Redis lookup
    client_id_raw = await redis.get(f"{SESSION_PREFIX}{token}")
    if client_id_raw is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    client_id = int(client_id_raw)

    # Refresh TTL (sliding window)
    await redis.expire(f"{SESSION_PREFIX}{token}", SESSION_TTL_SECONDS)

    # Fetch ORM object
    from src.infrastructure.database.dao.client import ClientDAO
    client = await ClientDAO.get_by_id(session, client_id)
    if not client:
        # Token points to a deleted user → clean up
        await redis.delete(f"{SESSION_PREFIX}{token}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return client


async def _authenticate_telegram(
    init_data: str,
    session: AsyncSession,
) -> Client:
    """
    Validate Telegram Web App initData (HMAC SHA-256) and return the Client ORM object.

    This is the legacy auth path kept for backward-compatibility with the
    existing Telegram WebApp frontend.
    """
    from src.api.utils.telegram_auth import validate_telegram_init_data
    from src.config import config

    user_data = validate_telegram_init_data(
        init_data=init_data,
        bot_token=config.telegram.TOKEN.get_secret_value()
    )
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid initData",
        )

    telegram_id = user_data.get("id")

    from src.infrastructure.database.dao.client import ClientDAO
    client = await ClientDAO.get_by_telegram_id(session, telegram_id)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if not client.is_logged_in:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not logged in",
        )

    return client


# ---------------------------------------------------------------------------
# Public dependency — used by all protected routers
# ---------------------------------------------------------------------------

async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """
    Resolve the current authenticated user.

    Dual-auth strategy (zero-breakage):
      1. Bearer token  →  Redis session lookup  (new path)
      2. Telegram initData  →  HMAC validation   (legacy fallback)

    Returns a Client ORM object in both cases.
    """
    # Priority 1: Bearer token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
            client = await _authenticate_bearer(auth_header, redis, session)
            from src.config import config
            if client.telegram_id and config.telegram.ADMIN_ACCESS_IDs:
                if client.telegram_id in config.telegram.ADMIN_ACCESS_IDs:
                    client.role = "super-admin"
            return client

    # Priority 2: Telegram initData fallback
    init_data = request.headers.get("X-Telegram-Init-Data")
    if init_data:
            client = await _authenticate_telegram(init_data, session)
            from src.config import config
            if client.telegram_id and config.telegram.ADMIN_ACCESS_IDs:
                if client.telegram_id in config.telegram.ADMIN_ACCESS_IDs:
                    client.role = "super-admin"
            return client

    # Neither auth method provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication credentials. "
               "Provide Authorization: Bearer <token> or X-Telegram-Init-Data header.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ---------------------------------------------------------------------------
# Admin dependency — used by admin-only routers
# ---------------------------------------------------------------------------

async def get_admin_user(
    current_user=Depends(get_current_user),
):
    """
    [LEGACY/DEPRECATED] Verify that the current user is an admin.
    
    This is kept for backward-compatibility with older endpoints that might
    rely on the Client role flag rather than the new RBAC system.
    """
    if current_user.role not in ['admin', 'super-admin']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# ---------------------------------------------------------------------------
# New RBAC Admin Dependencies
# ---------------------------------------------------------------------------

class AdminJWTPayload(BaseModel):
    admin_id: int
    role_name: str
    jti: str
    home_page: str | None = None
    permissions: list[str] = Field(default_factory=list)

async def get_admin_from_jwt(
    request: Request,
    redis: Redis = Depends(get_redis)
) -> AdminJWTPayload:
    """
    Validates Admin JWT from the ``X-Admin-Authorization: Bearer <token>`` header.

    Checks the Redis JTI blocklist to ensure the token has not been revoked.
    Returns an ``AdminJWTPayload`` on success; raises 401 on any auth failure.
    """
    from src.config import config
    from src.api.utils.admin_jwt import decode_admin_token
    from src.infrastructure.cache.keys import CacheKeys

    auth_header = request.headers.get("X-Admin-Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Admin-Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    token = auth_header.removeprefix("Bearer ").strip()
    
    # 1. Decode & verify signature/expiry
    payload = decode_admin_token(
        token=token,
        secret=config.api.JWT_SECRET.get_secret_value(),
        algorithm=config.api.JWT_ALGORITHM
    )
    
    jti = payload.get("jti")
    
    # 2. Check blocklist
    is_blocked = await redis.exists(CacheKeys.admin_jwt_blocklist(jti))
    if is_blocked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin session revoked (logged out)",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    return AdminJWTPayload(
        admin_id=int(payload["sub"]),
        role_name=payload["role"],
        jti=jti,
        home_page=payload.get("home_page"),
        permissions=payload.get("permissions") or [],
    )


def require_permission(resource: str, action: str) -> Callable:
    """
    FastAPI dependency factory that enforces RBAC.
    Usage:
        @router.get("/finance", dependencies=[Depends(require_permission("finance", "read"))])
    """
    async def _check_permission(
        admin: AdminJWTPayload = Depends(get_admin_from_jwt),
        session: AsyncSession = Depends(get_db),
        redis: Redis = Depends(get_redis),
    ) -> AdminJWTPayload:
        
        # super-admin bypass
        if admin.role_name == "super-admin":
            return admin
            
        from src.infrastructure.services.admin_rbac_service import RBACService
        
        perms = await RBACService.get_permissions(redis, session, admin.role_name)
        required_perm = f"{resource}:{action}"
        
        if required_perm not in perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Requires: {required_perm}"
            )
            
        return admin
        
    return _check_permission
