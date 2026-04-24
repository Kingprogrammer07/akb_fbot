from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.infrastructure.database.dao.base import BaseDAO
from src.infrastructure.database.models.admin_account import AdminAccount
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.role import Role
from src.infrastructure.tools.datetime_utils import get_current_time


class AdminAccountDAO(BaseDAO[AdminAccount]):
    """DAO for managing AdminAccount models."""

    def __init__(self, session: AsyncSession):
        super().__init__(AdminAccount, session)

    @classmethod
    async def get_by_username(
        cls, session: AsyncSession, username: str
    ) -> AdminAccount | None:
        """
        Get an admin account by system username.
        Eagerly loads the associated Role, its permissions, and the Client.
        """
        query = (
            select(AdminAccount)
            .where(AdminAccount.system_username == username)
            .options(
                selectinload(AdminAccount.role).selectinload(Role.permissions),
                selectinload(AdminAccount.client)
            )
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_client_id(
        cls, session: AsyncSession, client_id: int
    ) -> AdminAccount | None:
        """Get an admin account by the underlying client ID."""
        query = (
            select(AdminAccount)
            .where(AdminAccount.client_id == client_id)
            .options(
                selectinload(AdminAccount.role).selectinload(Role.permissions),
                selectinload(AdminAccount.client)
            )
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_id_with_relations(
        cls, session: AsyncSession, admin_id: int
    ) -> AdminAccount | None:
        """Get an admin account by ID, loading role and client."""
        query = (
            select(AdminAccount)
            .where(AdminAccount.id == admin_id)
            .options(
                selectinload(AdminAccount.role).selectinload(Role.permissions),
                selectinload(AdminAccount.client)
            )
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @classmethod
    async def increment_failed_attempts(
        cls, session: AsyncSession, admin_id: int
    ) -> int:
        """
        Increment failed login attempts counter.
        If it reaches >= 5, lock the account for 15 minutes.
        Returns the new failed attempt count.
        """
        # Fetch current record
        account = await session.get(AdminAccount, admin_id)
        if not account:
            return 0
        
        new_count = account.failed_login_attempts + 1
        account.failed_login_attempts = new_count
        
        if new_count >= 5:
            import datetime as dt
            account.locked_until = get_current_time() + dt.timedelta(minutes=15)
            
        await session.flush()
        return new_count

    @classmethod
    async def reset_failed_attempts(
        cls, session: AsyncSession, admin_id: int
    ) -> None:
        """Reset failed login attempts counter and clear lockout."""
        stmt = (
            update(AdminAccount)
            .where(AdminAccount.id == admin_id)
            .values(
                failed_login_attempts=0,
                locked_until=None
            )
        )
        await session.execute(stmt)
        await session.flush()

    @classmethod
    async def get_all_super_admins(
        cls, session: AsyncSession
    ) -> Sequence[AdminAccount]:
        """
        Get all active super-admins.
        Useful for broadcasting security alerts to them.
        """
        query = (
            select(AdminAccount)
            .join(AdminAccount.role)
            .where(
                Role.name == "super-admin",
                AdminAccount.is_active == True
            )
            .options(selectinload(AdminAccount.client))
        )
        result = await session.execute(query)
        return result.scalars().all()

    @classmethod
    async def get_all_admins(
        cls,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        role_id: int | None = None,
        is_active: bool | None = None,
    ) -> Sequence[AdminAccount]:
        """
        List admin accounts with optional role and active-status filters.
        Eagerly loads role (with permissions) and client for each account.
        """
        query = (
            select(AdminAccount)
            .options(
                selectinload(AdminAccount.role).selectinload(Role.permissions),
                selectinload(AdminAccount.client),
            )
            .order_by(AdminAccount.id)
        )

        if role_id is not None:
            query = query.where(AdminAccount.role_id == role_id)
        if is_active is not None:
            query = query.where(AdminAccount.is_active == is_active)

        query = query.offset(skip).limit(limit)
        result = await session.execute(query)
        return result.scalars().all()

    @classmethod
    async def count_admins(
        cls,
        session: AsyncSession,
        role_id: int | None = None,
        is_active: bool | None = None,
    ) -> int:
        """Count admin accounts matching the given filters (mirrors get_all_admins filters)."""
        query = select(func.count(AdminAccount.id))
        if role_id is not None:
            query = query.where(AdminAccount.role_id == role_id)
        if is_active is not None:
            query = query.where(AdminAccount.is_active == is_active)
        result = await session.execute(query)
        return result.scalar_one()

    @classmethod
    async def create_admin(
        cls,
        session: AsyncSession,
        client_id: int,
        role_id: int,
        system_username: str,
        pin_hash: str,
    ) -> AdminAccount:
        """
        Create a new AdminAccount record and flush (caller must commit).
        """
        account = AdminAccount(
            client_id=client_id,
            role_id=role_id,
            system_username=system_username,
            pin_hash=pin_hash,
        )
        session.add(account)
        await session.flush()
        # Reload with relations so the caller gets a fully-populated object
        return await cls.get_by_id_with_relations(session, account.id)

    @classmethod
    async def update_pin_and_unlock(
        cls, session: AsyncSession, admin_id: int, new_pin_hash: str
    ) -> None:
        """
        Updates the PIN hash and resets lockout statuses.
        """
        stmt = (
            update(AdminAccount)
            .where(AdminAccount.id == admin_id)
            .values(
                pin_hash=new_pin_hash,
                failed_login_attempts=0,
                locked_until=None
            )
        )
        await session.execute(stmt)
        await session.flush()
