"""Print every partner row — quick operational sanity check.

Run from the repo root:  ``python check_partners.py``
"""
import asyncio

from sqlalchemy import select

from src.config import config
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.models.partner import Partner


async def main() -> None:
    async with DatabaseClient(config.database.database_url) as client:
        async with client.session_factory() as session:
            result = await session.execute(select(Partner).order_by(Partner.id))
            for partner in result.scalars().all():
                print(
                    f"Code: {partner.code}, Name: {partner.display_name}, "
                    f"Prefix: {partner.prefix}, DM: {partner.is_dm_partner}"
                )


asyncio.run(main())
