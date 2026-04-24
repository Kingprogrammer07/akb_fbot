"""Delivery Request DAO - Database access layer for delivery request operations."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.delivery_request import DeliveryRequest


class DeliveryRequestDAO:
    """Data Access Object for DeliveryRequest operations."""

    @staticmethod
    async def create(
        session: AsyncSession,
        client_id: int,
        client_code: str,
        telegram_id: int,
        delivery_type: str,
        flight_names: str,
        full_name: str,
        phone: str,
        region: str,
        address: str,
        prepayment_receipt_file_id: str | None = None
    ) -> DeliveryRequest:
        """
        Create a new delivery request.

        Args:
            session: Database session
            client_id: Client ID
            client_code: Client code
            telegram_id: Telegram user ID
            delivery_type: Delivery type (uzpost, yandex, akb, bts)
            flight_names: JSON string of flight names
            full_name: Client full name
            phone: Client phone
            region: Client region
            address: Client address
            prepayment_receipt_file_id: File ID of prepayment receipt (for UZPOST)

        Returns:
            Created DeliveryRequest object
        """
        request = DeliveryRequest(
            client_id=client_id,
            client_code=client_code,
            telegram_id=telegram_id,
            delivery_type=delivery_type,
            flight_names=flight_names,
            full_name=full_name,
            phone=phone,
            region=region,
            address=address,
            prepayment_receipt_file_id=prepayment_receipt_file_id,
            status="pending"
        )
        session.add(request)
        await session.flush()
        await session.refresh(request)
        return request

    @staticmethod
    async def get_by_id(session: AsyncSession, request_id: int) -> DeliveryRequest | None:
        """Get delivery request by ID."""
        result = await session.execute(
            select(DeliveryRequest).where(DeliveryRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_client(session: AsyncSession, client_id: int) -> list[DeliveryRequest]:
        """Get all delivery requests for a client."""
        result = await session.execute(
            select(DeliveryRequest)
            .where(DeliveryRequest.client_id == client_id)
            .order_by(DeliveryRequest.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_client_paginated(
        session: AsyncSession, client_id: int, limit: int, offset: int
    ) -> list[DeliveryRequest]:
        """Get paginated delivery requests for a client."""
        result = await session.execute(
            select(DeliveryRequest)
            .where(DeliveryRequest.client_id == client_id)
            .order_by(DeliveryRequest.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_by_client(session: AsyncSession, client_id: int) -> int:
        """Count total delivery requests for a client."""
        result = await session.execute(
            select(func.count(DeliveryRequest.id))
            .where(DeliveryRequest.client_id == client_id)
        )
        return result.scalar() or 0

    @staticmethod
    async def get_recent_requests_by_client(
        session: AsyncSession, client_id: int, hours: int = 1
    ) -> list[DeliveryRequest]:
        """Get delivery requests created by client within the last N hours."""
        import datetime
        time_threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        result = await session.execute(
            select(DeliveryRequest)
            .where(
                DeliveryRequest.client_id == client_id,
                DeliveryRequest.created_at >= time_threshold
            )
            .order_by(DeliveryRequest.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_pending(session: AsyncSession) -> list[DeliveryRequest]:
        """Get all pending delivery requests."""
        result = await session.execute(
            select(DeliveryRequest)
            .where(DeliveryRequest.status == "pending")
            .order_by(DeliveryRequest.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def approve(
        session: AsyncSession,
        request_id: int,
        admin_id: int
    ) -> DeliveryRequest | None:
        """Approve a delivery request."""
        from src.infrastructure.tools.datetime_utils import get_current_time

        request = await DeliveryRequestDAO.get_by_id(session, request_id)
        if not request:
            return None

        request.status = "approved"
        request.processed_by_admin_id = admin_id
        request.processed_at = get_current_time()

        await session.flush()
        await session.refresh(request)
        return request

    @staticmethod
    async def reject(
        session: AsyncSession,
        request_id: int,
        admin_id: int,
        comment: str | None = None
    ) -> DeliveryRequest | None:
        """Reject a delivery request."""
        from src.infrastructure.tools.datetime_utils import get_current_time

        request = await DeliveryRequestDAO.get_by_id(session, request_id)
        if not request:
            return None

        request.status = "rejected"
        request.processed_by_admin_id = admin_id
        request.processed_at = get_current_time()
        request.admin_comment = comment

        await session.flush()
        await session.refresh(request)
        return request
