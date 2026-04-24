"""DAO for Notification management."""
import logging

from sqlalchemy import select, func, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.notification import Notification

logger = logging.getLogger(__name__)


class NotificationDAO:
    """Data Access Object for user notifications."""

    @staticmethod
    async def create(
        session: AsyncSession,
        client_id: int,
        title: str,
        body: str,
        notif_type: str = "info"
    ) -> Notification:
        """Create a new notification for a user."""
        notification = Notification(
            client_id=client_id,
            title=title,
            body=body,
            type=notif_type,
            is_read=False,
        )
        session.add(notification)
        await session.flush()
        await session.refresh(notification)
        logger.info(f"Created Notification id={notification.id} for client_id={client_id}")
        return notification

    @staticmethod
    async def get_user_notifications(
        session: AsyncSession,
        client_id: int,
        page: int = 1,
        size: int = 20
    ) -> tuple[list[Notification], int]:
        """
        Get paginated notifications for a user, newest first.
        
        Returns (items, total_count) tuple.
        """
        # Total count
        count_result = await session.execute(
            select(func.count(Notification.id))
            .where(Notification.client_id == client_id)
        )
        total = count_result.scalar_one()

        # Paginated items
        offset = (page - 1) * size
        result = await session.execute(
            select(Notification)
            .where(Notification.client_id == client_id)
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(size)
        )
        items = list(result.scalars().all())

        return items, total

    @staticmethod
    async def get_unread_count(session: AsyncSession, client_id: int) -> int:
        """Count unread notifications for a user."""
        result = await session.execute(
            select(func.count(Notification.id))
            .where(
                Notification.client_id == client_id,
                Notification.is_read == False
            )
        )
        return result.scalar_one()

    @staticmethod
    async def mark_as_read(
        session: AsyncSession,
        notification_id: int,
        client_id: int
    ) -> bool:
        """
        Mark a specific notification as read.
        
        Returns True if the notification was found and updated, False otherwise.
        Validates that the notification belongs to the given client.
        """
        result = await session.execute(
            sa_update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.client_id == client_id,
            )
            .values(is_read=True)
        )
        await session.flush()
        updated = result.rowcount > 0
        if updated:
            logger.debug(f"Marked notification {notification_id} as read for client {client_id}")
        return updated

    @staticmethod
    async def mark_all_as_read(session: AsyncSession, client_id: int) -> int:
        """
        Mark all notifications as read for a user.
        
        Returns the number of rows updated.
        """
        result = await session.execute(
            sa_update(Notification)
            .where(
                Notification.client_id == client_id,
                Notification.is_read == False,
            )
            .values(is_read=True)
        )
        await session.flush()
        count = result.rowcount
        if count > 0:
            logger.info(f"Marked {count} notifications as read for client {client_id}")
        return count
