"""Debug tooling endpoints controlled through Redis."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from src.api.dependencies import AdminJWTPayload, get_admin_from_jwt, get_redis

router = APIRouter(prefix="/debug", tags=["debug"])

_ERUDA_KEY_PREFIX = "debug:eruda:"
_ALLOWED_ERUDA_SCOPES = frozenset({"warehouse"})


class ErudaStatusResponse(BaseModel):
    scope: str
    enabled: bool
    ttl_seconds: int | None = None


class ErudaToggleRequest(BaseModel):
    scope: str = Field(default="warehouse")
    enabled: bool
    ttl_seconds: int | None = Field(default=3600, ge=60, le=86400)


def _eruda_key(scope: str) -> str:
    normalized_scope = scope.strip().lower()
    if normalized_scope not in _ALLOWED_ERUDA_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported Eruda scope: {scope}",
        )
    return f"{_ERUDA_KEY_PREFIX}{normalized_scope}"


async def _read_eruda_status(redis: Redis, scope: str) -> ErudaStatusResponse:
    key = _eruda_key(scope)
    enabled_raw = await redis.get(key)
    ttl = await redis.ttl(key)
    ttl_seconds = ttl if ttl >= 0 else None
    return ErudaStatusResponse(
        scope=scope.strip().lower(),
        enabled=enabled_raw == b"1" or enabled_raw == "1",
        ttl_seconds=ttl_seconds,
    )


@router.get("/eruda/status", response_model=ErudaStatusResponse)
async def get_eruda_status(
    scope: str = Query(default="warehouse"),
    admin: AdminJWTPayload = Depends(get_admin_from_jwt),
    redis: Redis = Depends(get_redis),
) -> ErudaStatusResponse:
    """Return whether Eruda is enabled for this debug scope."""
    _ = admin
    return await _read_eruda_status(redis, scope)


@router.post("/eruda/status", response_model=ErudaStatusResponse)
async def set_eruda_status(
    body: ErudaToggleRequest,
    admin: AdminJWTPayload = Depends(get_admin_from_jwt),
    redis: Redis = Depends(get_redis),
) -> ErudaStatusResponse:
    """Enable or disable Eruda for a limited time. Super-admin only."""
    if admin.role_name != "super-admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super-admin can change Eruda debug status.",
        )

    key = _eruda_key(body.scope)
    if body.enabled:
        if body.ttl_seconds is None:
            await redis.set(key, "1")
        else:
            await redis.set(key, "1", ex=body.ttl_seconds)
    else:
        await redis.delete(key)

    return await _read_eruda_status(redis, body.scope)
