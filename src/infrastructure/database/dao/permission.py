"""
PermissionDAO — queries for the Permission model.
"""
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.base import BaseDAO
from src.infrastructure.database.models.role import Permission


class PermissionDAO(BaseDAO[Permission]):
    """DAO for managing Permission models."""

    def __init__(self, session: AsyncSession):
        super().__init__(Permission, session)

    @classmethod
    async def get_all_permissions(cls, session: AsyncSession) -> Sequence[Permission]:
        """Return all permissions ordered by resource then action."""
        query = select(Permission).order_by(Permission.resource, Permission.action)
        result = await session.execute(query)
        return result.scalars().all()

    @classmethod
    async def get_by_ids(
        cls, session: AsyncSession, ids: list[int]
    ) -> Sequence[Permission]:
        """Fetch multiple permissions by their primary keys."""
        query = select(Permission).where(Permission.id.in_(ids))
        result = await session.execute(query)
        return result.scalars().all()
