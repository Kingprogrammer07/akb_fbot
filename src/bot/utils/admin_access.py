from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import config
from src.infrastructure.database.models.admin_account import AdminAccount
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.role import Role


def is_config_super_admin(telegram_id: int | None) -> bool:
    """Config admins are root super-admins and always take priority."""
    return bool(
        telegram_id
        and config.telegram.ADMIN_ACCESS_IDs
        and telegram_id in config.telegram.ADMIN_ACCESS_IDs
    )


async def is_super_admin_by_telegram_id(
    session: AsyncSession,
    telegram_id: int | None,
) -> bool:
    """Check super-admin access across config, RBAC admin accounts, and legacy client role."""
    if is_config_super_admin(telegram_id):
        return True
    if not telegram_id:
        return False

    rbac_query = (
        select(AdminAccount.id)
        .join(AdminAccount.role)
        .join(AdminAccount.client)
        .where(
            Client.telegram_id == telegram_id,
            Role.name == "super-admin",
            AdminAccount.is_active == True,  # noqa: E712 - SQLAlchemy requires ==
        )
        .limit(1)
    )
    rbac_result = await session.execute(rbac_query)
    if rbac_result.scalar_one_or_none() is not None:
        return True

    legacy_query = (
        select(Client.id)
        .where(
            Client.telegram_id == telegram_id,
            Client.role == "super-admin",
        )
        .limit(1)
    )
    legacy_result = await session.execute(legacy_query)
    return legacy_result.scalar_one_or_none() is not None


async def is_admin_by_telegram_id(
    session: AsyncSession,
    telegram_id: int | None,
) -> bool:
    """Check admin access across config, RBAC admin accounts, and legacy client role."""
    if is_config_super_admin(telegram_id):
        return True
    if not telegram_id:
        return False

    rbac_query = (
        select(AdminAccount.id)
        .join(AdminAccount.client)
        .where(
            Client.telegram_id == telegram_id,
            AdminAccount.is_active == True,  # noqa: E712 - SQLAlchemy requires ==
        )
        .limit(1)
    )
    rbac_result = await session.execute(rbac_query)
    if rbac_result.scalar_one_or_none() is not None:
        return True

    legacy_query = (
        select(Client.id)
        .where(
            Client.telegram_id == telegram_id,
            Client.role.in_(["admin", "super-admin"]),
        )
        .limit(1)
    )
    legacy_result = await session.execute(legacy_query)
    return legacy_result.scalar_one_or_none() is not None
