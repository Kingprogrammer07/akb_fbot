"""Analytics Event DAO."""
from datetime import datetime
from typing import Optional
from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import JSONB

from src.infrastructure.database.models.analytics_event import AnalyticsEvent


class AnalyticsEventDAO:
    """Data Access Object for AnalyticsEvent operations."""

    @staticmethod
    async def create(
        session: AsyncSession,
        event_type: str,
        user_id: Optional[int] = None,
        event_data: Optional[dict] = None
    ) -> AnalyticsEvent:
        """
        Create a new analytics event.
        
        Args:
            session: Database session
            event_type: Type of event (e.g., 'client_registration', 'cargo_upload')
            user_id: Optional Telegram ID of user who triggered the event
            event_data: Optional dictionary with event-specific data
            
        Returns:
            Created AnalyticsEvent instance
        """
        event = AnalyticsEvent(
            event_type=event_type,
            user_id=user_id,
            event_data=event_data
        )
        session.add(event)
        await session.flush()
        await session.refresh(event)
        return event

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        event_id: int
    ) -> Optional[AnalyticsEvent]:
        """Get analytics event by ID."""
        result = await session.execute(
            select(AnalyticsEvent).where(AnalyticsEvent.id == event_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_event_type(
        session: AsyncSession,
        event_type: str,
        limit: int = 100,
        offset: int = 0
    ) -> list[AnalyticsEvent]:
        """
        Get events by type, ordered by created_at descending.
        
        Args:
            session: Database session
            event_type: Event type to filter by
            limit: Maximum number of events to return
            offset: Number of events to skip
            
        Returns:
            List of AnalyticsEvent instances
        """
        result = await session.execute(
            select(AnalyticsEvent)
            .where(AnalyticsEvent.event_type == event_type)
            .order_by(desc(AnalyticsEvent.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_user_id(
        session: AsyncSession,
        user_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> list[AnalyticsEvent]:
        """
        Get events by user_id, ordered by created_at descending.
        
        Args:
            session: Database session
            user_id: Telegram ID of user
            limit: Maximum number of events to return
            offset: Number of events to skip
            
        Returns:
            List of AnalyticsEvent instances
        """
        result = await session.execute(
            select(AnalyticsEvent)
            .where(AnalyticsEvent.user_id == user_id)
            .order_by(desc(AnalyticsEvent.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_date_range(
        session: AsyncSession,
        start_date: datetime,
        end_date: datetime,
        event_type: Optional[str] = None,
        user_id: Optional[int] = None,
        limit: int = 1000,
        offset: int = 0
    ) -> list[AnalyticsEvent]:
        """
        Get events within a date range with optional filters.
        
        Args:
            session: Database session
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            event_type: Optional event type filter
            user_id: Optional user ID filter
            limit: Maximum number of events to return
            offset: Number of events to skip
            
        Returns:
            List of AnalyticsEvent instances
        """
        conditions = [
            AnalyticsEvent.created_at >= start_date,
            AnalyticsEvent.created_at <= end_date
        ]
        
        if event_type:
            conditions.append(AnalyticsEvent.event_type == event_type)
        if user_id:
            conditions.append(AnalyticsEvent.user_id == user_id)
        
        result = await session.execute(
            select(AnalyticsEvent)
            .where(and_(*conditions))
            .order_by(desc(AnalyticsEvent.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_by_event_type(
        session: AsyncSession,
        event_type: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> int:
        """
        Count events of a specific type, optionally within a date range.
        
        Args:
            session: Database session
            event_type: Event type to count
            start_date: Optional start of date range
            end_date: Optional end of date range
            
        Returns:
            Count of events
        """
        conditions = [AnalyticsEvent.event_type == event_type]
        
        if start_date:
            conditions.append(AnalyticsEvent.created_at >= start_date)
        if end_date:
            conditions.append(AnalyticsEvent.created_at <= end_date)
        
        result = await session.execute(
            select(func.count(AnalyticsEvent.id))
            .where(and_(*conditions))
        )
        return result.scalar_one()

    @staticmethod
    async def get_event_types(
        session: AsyncSession
    ) -> list[str]:
        """
        Get list of all distinct event types.
        
        Args:
            session: Database session
            
        Returns:
            List of distinct event type strings
        """
        result = await session.execute(
            select(AnalyticsEvent.event_type)
            .distinct()
            .order_by(AnalyticsEvent.event_type)
        )
        return list(result.scalars().all())

