"""Broadcast DAO - Database access layer for broadcast operations."""
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.broadcast import BroadcastMessage, BroadcastStatus


class BroadcastDAO:
    """Data Access Object for BroadcastMessage operations."""

    @staticmethod
    async def create(session: AsyncSession, broadcast_data: dict) -> BroadcastMessage:
        """
        Create a new broadcast message.

        Args:
            session: Database session
            broadcast_data: Dictionary with broadcast fields

        Returns:
            Created BroadcastMessage object
        """
        broadcast = BroadcastMessage(**broadcast_data)
        session.add(broadcast)
        await session.flush()
        await session.refresh(broadcast)
        return broadcast

    @staticmethod
    async def get_by_id(session: AsyncSession, broadcast_id: int) -> BroadcastMessage | None:
        """
        Get broadcast by ID.

        Args:
            session: Database session
            broadcast_id: Broadcast ID

        Returns:
            BroadcastMessage object or None
        """
        result = await session.execute(
            select(BroadcastMessage).where(BroadcastMessage.id == broadcast_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_status(
        session: AsyncSession,
        broadcast_id: int,
        status: BroadcastStatus
    ) -> bool:
        """
        Update broadcast status.

        Args:
            session: Database session
            broadcast_id: Broadcast ID
            status: New status

        Returns:
            True if updated, False otherwise
        """
        result = await session.execute(
            update(BroadcastMessage)
            .where(BroadcastMessage.id == broadcast_id)
            .values(status=status)
        )
        await session.flush()
        return result.rowcount > 0

    @staticmethod
    async def update_statistics(
        session: AsyncSession,
        broadcast_id: int,
        sent_count: int,
        failed_count: int,
        blocked_count: int
    ) -> bool:
        """
        Update broadcast statistics.

        Args:
            session: Database session
            broadcast_id: Broadcast ID
            sent_count: Number of sent messages
            failed_count: Number of failed sends
            blocked_count: Number of blocked users

        Returns:
            True if updated
        """
        result = await session.execute(
            update(BroadcastMessage)
            .where(BroadcastMessage.id == broadcast_id)
            .values(
                sent_count=sent_count,
                failed_count=failed_count,
                blocked_count=blocked_count
            )
        )
        await session.flush()
        return result.rowcount > 0

    @staticmethod
    async def get_by_admin(
        session: AsyncSession,
        admin_telegram_id: int,
        limit: int = 20
    ) -> list[BroadcastMessage]:
        """
        Get recent broadcasts by admin.

        Args:
            session: Database session
            admin_telegram_id: Admin's Telegram ID
            limit: Maximum number of results

        Returns:
            List of BroadcastMessage objects
        """
        result = await session.execute(
            select(BroadcastMessage)
            .where(BroadcastMessage.created_by_telegram_id == admin_telegram_id)
            .order_by(BroadcastMessage.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_statistics(
        session: AsyncSession,
        broadcast_id: int
    ) -> dict:
        """
        Get broadcast statistics.

        Args:
            session: Database session
            broadcast_id: Broadcast ID

        Returns:
            Dictionary with statistics
        """
        broadcast = await BroadcastDAO.get_by_id(session, broadcast_id)
        if not broadcast:
            return {}

        return {
            "total_users": broadcast.total_users,
            "sent_count": broadcast.sent_count,
            "failed_count": broadcast.failed_count,
            "blocked_count": broadcast.blocked_count,
            "status": broadcast.status,
            "created_at": broadcast.created_at,
            "started_at": broadcast.started_at,
            "completed_at": broadcast.completed_at
        }

    @staticmethod
    async def count_all(session: AsyncSession) -> int:
        """
        Count total broadcasts.

        Args:
            session: Database session

        Returns:
            Total count
        """
        result = await session.execute(
            select(func.count(BroadcastMessage.id))
        )
        return result.scalar_one()

    @staticmethod
    async def delete(session: AsyncSession, broadcast_id: int) -> bool:
        """
        Delete broadcast (only if draft or failed).

        Args:
            session: Database session
            broadcast_id: Broadcast ID

        Returns:
            True if deleted
        """
        broadcast = await BroadcastDAO.get_by_id(session, broadcast_id)
        if not broadcast:
            return False

        # Only allow deletion of drafts and failed broadcasts
        if broadcast.status not in [BroadcastStatus.DRAFT, BroadcastStatus.FAILED]:
            return False

        await session.delete(broadcast)
        await session.flush()
        return True
