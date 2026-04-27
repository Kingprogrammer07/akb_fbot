import asyncio
from sqlalchemy import select, update
from src.infrastructure.database.setup import create_session_pool
from src.config import config
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.expected_cargo import ExpectedFlightCargo

async def main():
    session_factory = create_session_pool(config.database.database_url)
    async with session_factory() as session:
        result = await session.execute(select(Client))
        clients = result.scalars().all()
        
        fc_updates = 0
        ec_updates = 0
        
        for client in clients:
            primary = client.primary_code
            if not primary: continue
            
            aliases = [c for c in client.active_codes if c and c != primary]
            if not aliases: continue
            
            res1 = await session.execute(select(FlightCargo).where(FlightCargo.client_id.in_(aliases)))
            for fc in res1.scalars().all():
                fc.client_id = primary
                fc_updates += 1
                
            res2 = await session.execute(select(ExpectedFlightCargo).where(ExpectedFlightCargo.client_code.in_(aliases)))
            for ec in res2.scalars().all():
                ec.client_code = primary
                ec_updates += 1
                
        if fc_updates or ec_updates:
            print(f"Updating {fc_updates} flight_cargos and {ec_updates} expected_cargos...")
            await session.commit()
            print("Done!")
        else:
            print("Nothing to update.")

if __name__ == "__main__":
    asyncio.run(main())
