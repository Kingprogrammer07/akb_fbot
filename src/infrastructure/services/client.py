from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.client import ClientDAO
from src.config import config


class ClientService:

    async def get_client(
        self, telegram_id: int, session: AsyncSession
    ):
        return await ClientDAO.get_by_telegram_id(session, telegram_id)

    async def update_client(
        self,
        telegram_id: int,
        data: dict,
        session: AsyncSession,
    ):
        """Update an existing client."""
        client = await ClientDAO.get_by_telegram_id(session, telegram_id)
        if not client:
            return None
        return await ClientDAO.update(session, client, data)

    async def register_client(
        self,
        telegram_id: int,
        full_name: str,
        referrer_telegram_id: int | None,
        session: AsyncSession,
        region: str | None = None,
        district: str | None = None,
    ):
        """Register a new client with auto-generated client code."""
        # Generate client code using new utility
        from src.api.utils.code_generator import generate_client_code
        client_code = await generate_client_code(session, region, district)

        data = {
            "telegram_id": telegram_id,
            "full_name": full_name,
            "referrer_telegram_id": referrer_telegram_id,
            "client_code": client_code,
            "region": region,
            "district": district,
        }
        return await ClientDAO.create(session, data)

    async def delete_client(
        self,
        telegram_id: int,
        session: AsyncSession,
    ):
        """Delete a client by telegram_id."""
        client = await ClientDAO.get_by_telegram_id(session, telegram_id)
        if client:
            await ClientDAO.delete(session, client)
            return True
        return False

    async def count_referrals(
        self,
        telegram_id: int,
        session: AsyncSession,
    ) -> int:
        """Count how many clients were referred by this user (deprecated, use count_referrals_by_client_code)."""
        return await ClientDAO.count_referrals(session, telegram_id)

    async def count_referrals_by_client_code(
        self,
        client_code: str,
        session: AsyncSession,
    ) -> int:
        """Count how many clients were referred by this client (by client_code)."""
        return await ClientDAO.count_referrals_by_client_code(session, client_code)

    async def get_client_by_code(
        self,
        client_code: str,
        session: AsyncSession,
    ):
        """Get client by client code."""
        return await ClientDAO.get_by_client_code(session, client_code)

    async def get_client_by_id(
        self,
        client_id: int,
        session: AsyncSession,
    ):
        """Get client by ID."""
        return await ClientDAO.get_by_id(session, client_id)

    async def count_extra_passports(
        self,
        telegram_id: int,
        session: AsyncSession,
    ) -> int:
        """Count extra passports for a client (deprecated, use count_extra_passports_by_client_code)."""
        return await ClientDAO.count_extra_passports(session, telegram_id)

    async def count_extra_passports_by_client_code(
        self,
        client_code: str,
        session: AsyncSession,
    ) -> int:
        """Count extra passports for a client by client_code."""
        return await ClientDAO.count_extra_passports_by_client_code(session, client_code)
