"""User-facing Carousel endpoints.

Returns active carousel items to authenticated app users and records
view/click interactions for analytics.

Auth: standard user auth (``Authorization: Bearer <token>`` or
``X-Telegram-Init-Data`` header) via ``get_current_user``.
No admin permissions required — any logged-in user can view the carousel.

Admin CRUD lives in ``admin_carousel.py`` (Admin JWT + RBAC).
"""
from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db, get_redis
from src.api.routers.admin_carousel import _build_item_response
from src.api.schemas.carousel import CarouselItemResponse
from src.infrastructure.database.dao.carousel import CarouselDAO
from src.infrastructure.database.models.client import Client

router = APIRouter(prefix="/carousel", tags=["carousel"])


@router.get(
    "/",
    response_model=list[CarouselItemResponse],
    summary="Active carousel items for the current user",
)
async def list_active_items(
    current_user: Client = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> list[CarouselItemResponse]:
    """Return all active carousel items ordered by display order."""
    items = await CarouselDAO.get_all_active(session)
    return [
        await _build_item_response(item, redis)  # type: ignore[misc]
        for item in items
    ]


@router.post(
    "/{item_id}/view",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Track a carousel item view",
)
async def track_view(
    item_id: int,
    current_user: Client = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Increment the daily view counter for a carousel item.

    Failures are silently swallowed so that a tracking hiccup never blocks
    the caller.
    """
    try:
        await CarouselDAO.increment_view(session, item_id)
        await session.commit()
    except Exception:
        pass
    return {"status": "accepted"}


@router.post(
    "/{item_id}/click",
    status_code=status.HTTP_200_OK,
    summary="Track a carousel item click",
)
async def track_click(
    item_id: int,
    current_user: Client = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Increment the daily click counter for a carousel item.

    Failures are silently swallowed so that a tracking hiccup never blocks
    the caller.
    """
    try:
        await CarouselDAO.increment_click(session, item_id)
        await session.commit()
    except Exception:
        pass
    return {"status": "accepted"}
