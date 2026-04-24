"""User-facing Notification endpoints."""
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from src.api.dependencies import get_db, get_current_user
from src.api.schemas.notification import (
    NotificationResponse,
    NotificationListResponse,
    UnreadCountResponse,
)
from src.infrastructure.database.dao.notification import NotificationDAO
from src.infrastructure.database.models.client import Client

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "/",
    response_model=NotificationListResponse,
    summary="Get my notifications",
)
async def get_my_notifications(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    """Get paginated list of notifications for the current user, newest first."""
    items, total = await NotificationDAO.get_user_notifications(
        session, current_user.id, page, size
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(n) for n in items],
        total=total,
        page=page,
        size=size,
    )


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="Get unread notification count",
)
async def get_unread_count(
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    """Returns the number of unread notifications for the current user."""
    try:
        count = await NotificationDAO.get_unread_count(session, current_user.id)
    except Exception as e:
        logger.error(
            f"Failed to fetch unread count for client_id={current_user.id}: {e}",
            exc_info=True,
        )
        count = 0
    return UnreadCountResponse(count=count)


@router.post(
    "/{notification_id}/read",
    status_code=status.HTTP_200_OK,
    summary="Mark notification as read",
)
async def mark_as_read(
    notification_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    """Mark a specific notification as read."""
    updated = await NotificationDAO.mark_as_read(session, notification_id, current_user.id)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    await session.commit()
    return {"status": "ok"}


@router.post(
    "/read-all",
    status_code=status.HTTP_200_OK,
    summary="Mark all notifications as read",
)
async def mark_all_as_read(
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    """Mark all notifications as read for the current user."""
    count = await NotificationDAO.mark_all_as_read(session, current_user.id)
    await session.commit()
    return {"status": "ok", "updated": count}
