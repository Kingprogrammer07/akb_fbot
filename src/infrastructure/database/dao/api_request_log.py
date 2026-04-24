"""API Request Log DAO."""
from datetime import datetime
from typing import Optional
from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.api_request_log import APIRequestLog


class APIRequestLogDAO:
    """Data Access Object for APIRequestLog operations."""

    @staticmethod
    async def create(
        session: AsyncSession,
        method: str,
        endpoint: str,
        response_status: int,
        response_time_ms: int,
        user_id: Optional[int] = None,
        error_message: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> APIRequestLog:
        """
        Create a new API request log entry.
        
        Args:
            session: Database session
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path
            response_status: HTTP response status code
            response_time_ms: Request processing time in milliseconds
            user_id: Optional Telegram ID of authenticated user
            error_message: Optional error message if request failed
            ip_address: Optional client IP address
            
        Returns:
            Created APIRequestLog instance
        """
        log = APIRequestLog(
            method=method,
            endpoint=endpoint,
            response_status=response_status,
            response_time_ms=response_time_ms,
            user_id=user_id,
            error_message=error_message,
            ip_address=ip_address
        )
        session.add(log)
        await session.flush()
        await session.refresh(log)
        return log

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        log_id: int
    ) -> Optional[APIRequestLog]:
        """Get API request log by ID."""
        result = await session.execute(
            select(APIRequestLog).where(APIRequestLog.id == log_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_endpoint(
        session: AsyncSession,
        endpoint: str,
        limit: int = 100,
        offset: int = 0
    ) -> list[APIRequestLog]:
        """
        Get request logs by endpoint, ordered by created_at descending.
        
        Args:
            session: Database session
            endpoint: API endpoint path
            limit: Maximum number of logs to return
            offset: Number of logs to skip
            
        Returns:
            List of APIRequestLog instances
        """
        result = await session.execute(
            select(APIRequestLog)
            .where(APIRequestLog.endpoint == endpoint)
            .order_by(desc(APIRequestLog.created_at))
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
    ) -> list[APIRequestLog]:
        """
        Get request logs by user_id, ordered by created_at descending.
        
        Args:
            session: Database session
            user_id: Telegram ID of user
            limit: Maximum number of logs to return
            offset: Number of logs to skip
            
        Returns:
            List of APIRequestLog instances
        """
        result = await session.execute(
            select(APIRequestLog)
            .where(APIRequestLog.user_id == user_id)
            .order_by(desc(APIRequestLog.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_date_range(
        session: AsyncSession,
        start_date: datetime,
        end_date: datetime,
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        user_id: Optional[int] = None,
        response_status: Optional[int] = None,
        limit: int = 1000,
        offset: int = 0
    ) -> list[APIRequestLog]:
        """
        Get request logs within a date range with optional filters.
        
        Args:
            session: Database session
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            endpoint: Optional endpoint filter
            method: Optional HTTP method filter
            user_id: Optional user ID filter
            response_status: Optional status code filter
            limit: Maximum number of logs to return
            offset: Number of logs to skip
            
        Returns:
            List of APIRequestLog instances
        """
        conditions = [
            APIRequestLog.created_at >= start_date,
            APIRequestLog.created_at <= end_date
        ]
        
        if endpoint:
            conditions.append(APIRequestLog.endpoint == endpoint)
        if method:
            conditions.append(APIRequestLog.method == method)
        if user_id:
            conditions.append(APIRequestLog.user_id == user_id)
        if response_status is not None:
            conditions.append(APIRequestLog.response_status == response_status)
        
        result = await session.execute(
            select(APIRequestLog)
            .where(and_(*conditions))
            .order_by(desc(APIRequestLog.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_requests(
        session: AsyncSession,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        endpoint: Optional[str] = None,
        response_status: Optional[int] = None
    ) -> int:
        """
        Count request logs with optional filters.
        
        Args:
            session: Database session
            start_date: Optional start of date range
            end_date: Optional end of date range
            endpoint: Optional endpoint filter
            response_status: Optional status code filter
            
        Returns:
            Count of request logs
        """
        conditions = []
        
        if start_date:
            conditions.append(APIRequestLog.created_at >= start_date)
        if end_date:
            conditions.append(APIRequestLog.created_at <= end_date)
        if endpoint:
            conditions.append(APIRequestLog.endpoint == endpoint)
        if response_status is not None:
            conditions.append(APIRequestLog.response_status == response_status)
        
        result = await session.execute(
            select(func.count(APIRequestLog.id))
            .where(and_(*conditions) if conditions else True)
        )
        return result.scalar_one()

    @staticmethod
    async def get_average_response_time(
        session: AsyncSession,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        endpoint: Optional[str] = None
    ) -> float:
        """
        Get average response time in milliseconds with optional filters.
        
        Args:
            session: Database session
            start_date: Optional start of date range
            end_date: Optional end of date range
            endpoint: Optional endpoint filter
            
        Returns:
            Average response time in milliseconds
        """
        conditions = []
        
        if start_date:
            conditions.append(APIRequestLog.created_at >= start_date)
        if end_date:
            conditions.append(APIRequestLog.created_at <= end_date)
        if endpoint:
            conditions.append(APIRequestLog.endpoint == endpoint)
        
        result = await session.execute(
            select(func.avg(APIRequestLog.response_time_ms))
            .where(and_(*conditions) if conditions else True)
        )
        avg_time = result.scalar_one()
        return float(avg_time) if avg_time else 0.0

    @staticmethod
    async def get_endpoints(
        session: AsyncSession
    ) -> list[str]:
        """
        Get list of all distinct endpoints.
        
        Args:
            session: Database session
            
        Returns:
            List of distinct endpoint strings
        """
        result = await session.execute(
            select(APIRequestLog.endpoint)
            .distinct()
            .order_by(APIRequestLog.endpoint)
        )
        return list(result.scalars().all())

