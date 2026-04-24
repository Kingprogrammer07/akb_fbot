"""Session log DAO for managing session events with FIFO cleanup."""
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.session_log import SessionLog
from src.infrastructure.tools.datetime_utils import get_current_time


class SessionLogDAO:
    """
    DAO for SessionLog with "Last 20 records" retention policy.
    """
    
    MAX_LOGS_PER_CLIENT = 20

    @staticmethod
    async def add_log(
        session: AsyncSession,
        client_id: int,
        telegram_id: int,
        event_type: str,
        ip_address: str | None = None,
        device_info: str | None = None,
        client_code: str | None = None,
        phone: str | None = None,
        username: str | None = None
    ) -> SessionLog:
        """
        Add a new session log and enforce FIFO cleanup.
        
        If client has more than 20 logs, delete the oldest ones.
        """
        # Create and insert the new log
        log = SessionLog(
            client_id=client_id,
            telegram_id=telegram_id,
            event_type=event_type,
            ip_address=ip_address,
            device_info=device_info,
            client_code=client_code,
            phone=phone,
            username=username,
            created_at=get_current_time()
        )
        session.add(log)
        await session.flush()
        
        # Count logs for this client
        count_query = select(func.count(SessionLog.id)).where(
            SessionLog.client_id == client_id
        )
        result = await session.execute(count_query)
        count = result.scalar_one()
        
        # If count exceeds max, delete oldest logs
        if count > SessionLogDAO.MAX_LOGS_PER_CLIENT:
            excess = count - SessionLogDAO.MAX_LOGS_PER_CLIENT
            
            # Find IDs of oldest logs to delete
            oldest_query = (
                select(SessionLog.id)
                .where(SessionLog.client_id == client_id)
                .order_by(SessionLog.created_at.asc())
                .limit(excess)
            )
            oldest_result = await session.execute(oldest_query)
            oldest_ids = [row[0] for row in oldest_result.fetchall()]
            
            if oldest_ids:
                await session.execute(
                    delete(SessionLog).where(SessionLog.id.in_(oldest_ids))
                )
        
        return log

    @staticmethod
    async def get_by_client_id(
        session: AsyncSession,
        client_id: int,
        limit: int = 20,
        offset: int = 0
    ) -> list[SessionLog]:
        """
        Get session logs for a client, ordered by most recent first.
        """
        query = (
            select(SessionLog)
            .where(SessionLog.client_id == client_id)
            .order_by(SessionLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def count_by_client_id(
        session: AsyncSession,
        client_id: int
    ) -> int:
        """Count total session logs for a client."""
        query = select(func.count(SessionLog.id)).where(
            SessionLog.client_id == client_id
        )
        result = await session.execute(query)
        return result.scalar_one()

    @staticmethod
    async def get_by_telegram_id(
        session: AsyncSession,
        telegram_id: int,
        limit: int = 20
    ) -> list[SessionLog]:
        """Get session logs by telegram_id (for display in bot)."""
        query = (
            select(SessionLog)
            .where(SessionLog.telegram_id == telegram_id)
            .order_by(SessionLog.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(query)
        return list(result.scalars().all())
