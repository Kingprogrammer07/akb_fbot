"""
RoleDAO — queries for the Role and Permission models.
"""
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.infrastructure.database.dao.base import BaseDAO
from src.infrastructure.database.models.admin_account import AdminAccount
from src.infrastructure.database.models.role import Permission, Role, role_permissions


class RoleDAO(BaseDAO[Role]):
    """DAO for managing Role models."""

    def __init__(self, session: AsyncSession):
        super().__init__(Role, session)

    @classmethod
    async def get_all_roles(cls, session: AsyncSession) -> Sequence[Role]:
        """Return all roles with their permissions eager-loaded."""
        query = (
            select(Role)
            .options(selectinload(Role.permissions))
            .order_by(Role.id)
        )
        result = await session.execute(query)
        return result.scalars().all()

    @classmethod
    async def get_by_id(cls, session: AsyncSession, role_id: int) -> Role | None:
        """Get a single role by ID with permissions loaded."""
        query = (
            select(Role)
            .where(Role.id == role_id)
            .options(selectinload(Role.permissions))
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_name(cls, session: AsyncSession, name: str) -> Role | None:
        """Get a role by its unique name."""
        query = select(Role).where(Role.name == name)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @classmethod
    async def create_role(
        cls,
        session: AsyncSession,
        name: str,
        description: str | None = None,
        home_page: str = "/admin",
    ) -> Role:
        """
        Create a new custom role (no permissions yet — assign via update_role_permissions).
        Flushes but does not commit.
        """
        role = Role(name=name, description=description, is_custom=True, home_page=home_page)
        session.add(role)
        await session.flush()
        return role

    @classmethod
    async def update_role_permissions(
        cls,
        session: AsyncSession,
        role_id: int,
        permission_ids: list[int],
    ) -> Role | None:
        """
        Replace the full set of permissions for a role atomically.

        Uses ORM-managed collection clear rather than a raw DELETE on the
        association table.  A raw DELETE bypasses SQLAlchemy's identity map,
        leaving the in-memory ``role.permissions`` collection stale.  When the
        ORM then computes the diff for the new assignment it sees the old
        permissions as "still present" and may emit only a partial INSERT set
        or raise a unique-constraint error — silently losing permissions.

        ``role.permissions.clear()`` tells the ORM to schedule DELETEs for every
        current entry; the subsequent flush sends those DELETEs to the DB before
        the new INSERTs are written, guaranteeing a clean atomic replacement.

        Returns the updated Role (with permissions loaded), or None if not found.
        """
        role = await cls.get_by_id(session, role_id)
        if not role:
            return None

        # Let the ORM manage the removal so the in-memory collection stays
        # consistent with what is about to be flushed to the DB.
        role.permissions.clear()
        await session.flush()

        if permission_ids:
            perm_result = await session.execute(
                select(Permission).where(Permission.id.in_(permission_ids))
            )
            role.permissions = list(perm_result.scalars().all())

        await session.flush()

        # Refresh so the returned object reflects the committed association rows.
        await session.refresh(role, ["permissions"])
        return role

    @classmethod
    async def delete_role(
        cls,
        session: AsyncSession,
        role_id: int,
    ) -> Role | None:
        """
        Delete a custom role after enforcing safety constraints.

        Returns the Role object (snapshot before deletion) so the caller can
        invalidate caches using the role name, or None if the role does not exist.

        Raises ValueError if:
        - The role is a system role (``is_custom=False``) — built-in roles must
          never be removed; they are seeded and referenced by the auth flow.
        - One or more **active** admin accounts are still assigned to this role —
          deleting the role would strip those admins of their permissions
          unexpectedly.

        The ``role_permissions`` association rows are removed automatically via
        the ``ondelete="CASCADE"`` FK on the ``role_permissions`` table.
        """
        role = await cls.get_by_id(session, role_id)
        if not role:
            return None

        if not role.is_custom:
            raise ValueError(
                f"Role '{role.name}' is a built-in system role and cannot be deleted."
            )

        active_admin_count_query = select(func.count(AdminAccount.id)).where(
            AdminAccount.role_id == role_id,
            AdminAccount.is_active == True,  # noqa: E712 — SQLAlchemy requires ==
        )
        active_count: int = (await session.execute(active_admin_count_query)).scalar_one()

        if active_count > 0:
            raise ValueError(
                f"Cannot delete role '{role.name}': "
                f"{active_count} active admin account(s) are still assigned to it. "
                "Reassign or deactivate them first."
            )

        await session.delete(role)
        await session.flush()
        return role
