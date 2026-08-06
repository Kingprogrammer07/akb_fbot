import asyncio
from sqlalchemy import select
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.models.partner import Partner
from src.config import config

async def main():
    async with DatabaseClient(config.database.database_url) as client:
        res = await client.session.execute(select(Partner))
        partners = res.scalars().all()
        for p in partners:
            print(f"Code: {p.code}, Name: {p.display_name}, Prefix: {p.prefix}, DM: {p.is_dm_partner}")

asyncio.run(main())
