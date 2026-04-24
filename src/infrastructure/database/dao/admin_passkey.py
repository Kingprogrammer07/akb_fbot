from typing import Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.base import BaseDAO
from src.infrastructure.database.models.admin_passkey import AdminPasskey


class AdminPasskeyDAO(BaseDAO[AdminPasskey]):
    """DAO for managing AdminPasskey models for WebAuthn login."""

    def __init__(self, session: AsyncSession):
        super().__init__(AdminPasskey, session)

    @classmethod
    async def get_by_credential_id(
        cls, session: AsyncSession, credential_id: str
    ) -> AdminPasskey | None:
        """Get a passkey by its globally unique credential ID."""
        query = select(AdminPasskey).where(AdminPasskey.credential_id == credential_id)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @classmethod
    async def list_for_admin(
        cls, session: AsyncSession, admin_id: int
    ) -> Sequence[AdminPasskey]:
        """List all registered passkeys for an admin account."""
        query = select(AdminPasskey).where(AdminPasskey.admin_account_id == admin_id)
        result = await session.execute(query)
        return result.scalars().all()

    @classmethod
    async def update_sign_count(
        cls, session: AsyncSession, passkey_id: int, new_sign_count: int
    ) -> None:
        """Update the sign_count for a passkey (preventing clone attacks)."""
        passkey = await session.get(AdminPasskey, passkey_id)
        if passkey:
            passkey.sign_count = new_sign_count
            await session.flush()
