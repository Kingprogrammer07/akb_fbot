import logging
from typing import Any, Sequence

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.infrastructure.database.dao.base import BaseDAO
from src.infrastructure.database.models.admin_account import AdminAccount
from src.infrastructure.database.models.admin_audit_log import AdminAuditLog
from src.infrastructure.tools.datetime_utils import get_current_time

logger = logging.getLogger(__name__)


class AdminAuditLogDAO(BaseDAO[AdminAuditLog]):
    """DAO for managing AdminAuditLog models."""

    def __init__(self, session: AsyncSession):
        super().__init__(AdminAuditLog, session)

    @classmethod
    async def _resolve_actor_snapshot(
        cls,
        session: AsyncSession,
        admin_id: int,
    ) -> tuple[int | None, str | None]:
        """Resolve the persisted audit actor snapshot from admin_accounts."""
        result = await session.execute(
            select(AdminAccount.id, AdminAccount.system_username)
            .where(AdminAccount.id == admin_id)
            .limit(1)
        )
        row = result.first()
        if not row:
            return None, None
        return row.id, row.system_username

    @classmethod
    async def log(
        cls,
        session: AsyncSession,
        action: str,
        admin_id: int | None = None,
        role_snapshot: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        actor_system_username: str | None = None,
    ) -> AdminAuditLog:
        """
        Create a new immutable audit log entry.

        Pass ``role_snapshot`` to capture the acting admin's role name at the
        time of the action for immutable historical context.

        If ``admin_id`` does not exist in ``admin_accounts`` (e.g. DB was reset
        or the admin was deleted while their JWT was still valid), the log entry
        is written with ``admin_account_id = NULL`` instead of crashing the
        request with a FK violation.
        """
        resolved_admin_id: int | None = admin_id
        resolved_actor_username = actor_system_username

        if admin_id is not None:
            resolved_admin_id, stored_username = await cls._resolve_actor_snapshot(
                session,
                admin_id,
            )
            if resolved_actor_username is None:
                resolved_actor_username = stored_username

        if admin_id is not None and resolved_admin_id is None:
            logger.warning(
                "AdminAuditLog.log: admin_id=%d not found in admin_accounts - "
                "writing audit entry with NULL admin_account_id (action=%r)",
                admin_id,
                action,
            )

        audit_log = AdminAuditLog(
            admin_account_id=resolved_admin_id,
            action=action,
            role_snapshot=role_snapshot,
            actor_system_username=resolved_actor_username,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=get_current_time(),
        )
        session.add(audit_log)
        await session.flush()
        return audit_log

    @classmethod
    async def get_logs(
        cls,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        admin_id: int | None = None,
        role_snapshot: str | None = None,
        action: str | None = None,
    ) -> Sequence[AdminAuditLog]:
        """List audit logs with optional filtering by admin_id, role_snapshot, and action."""
        query = (
            select(AdminAuditLog)
            .options(selectinload(AdminAuditLog.admin_account))
            .order_by(desc(AdminAuditLog.created_at))
        )

        if admin_id is not None:
            query = query.where(AdminAuditLog.admin_account_id == admin_id)
        if role_snapshot is not None:
            query = query.where(AdminAuditLog.role_snapshot == role_snapshot)
        if action is not None:
            query = query.where(AdminAuditLog.action == action)

        query = query.offset(skip).limit(limit)
        result = await session.execute(query)
        return result.scalars().all()

    @classmethod
    async def count_logs(
        cls,
        session: AsyncSession,
        admin_id: int | None = None,
        role_snapshot: str | None = None,
        action: str | None = None,
    ) -> int:
        """Count audit logs matching the given filters (mirrors get_logs filters)."""
        query = select(func.count(AdminAuditLog.id))
        if admin_id is not None:
            query = query.where(AdminAuditLog.admin_account_id == admin_id)
        if role_snapshot is not None:
            query = query.where(AdminAuditLog.role_snapshot == role_snapshot)
        if action is not None:
            query = query.where(AdminAuditLog.action == action)
        result = await session.execute(query)
        return result.scalar_one()

    @classmethod
    async def get_last_login(
        cls,
        session: AsyncSession,
        admin_id: int,
    ) -> AdminAuditLog | None:
        """
        Get the last successful login event for an admin.
        Used to detect new devices/IPs compared to previous login.
        """
        query = (
            select(AdminAuditLog)
            .where(
                AdminAuditLog.admin_account_id == admin_id,
                AdminAuditLog.action.in_(["LOGIN_SUCCESS", "PASSKEY_LOGIN_SUCCESS"]),
            )
            .order_by(desc(AdminAuditLog.created_at))
            .limit(1)
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()
