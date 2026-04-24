import asyncio
import logging
import sys
import os

# Loyiha papkasini topish va yo'lga qo'shish
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import select
from src.config import config
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.services.client import ClientService
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.bot.utils.currency_converter import currency_converter
from src.bot.handlers.admin.bulk_cargo_sender import DEFAULT_USD_TO_UZS_RATE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TARGET_FLIGHT = "A-M194-195_OSTATKA"

async def main():
    async with DatabaseClient(config.database.database_url) as db_client:
        async with db_client.session_factory() as session:
            # 1. Qo'shimcha to'lovni (extra_charge) olish
            static_data = await StaticDataDAO.get_first(session)
            extra_charge = float(static_data.extra_charge) if static_data else 0.0
            
            # 2. USD dan UZS ga kursni olish
            try:
                rate = await currency_converter.get_rate_async(session, "USD", "UZS")
            except Exception:
                rate = DEFAULT_USD_TO_UZS_RATE
                
            # 3. Faqat jo'natilgan (is_sent=True) yuklarni olish
            query = select(FlightCargo).where(
                FlightCargo.flight_name == TARGET_FLIGHT,
                FlightCargo.is_sent == True
            )
            result = await session.execute(query)
            cargos = result.scalars().all()
            
            # Yuklarni client_id bo'yicha guruhlash
            client_cargos = {}
            for cargo in cargos:
                client_cargos.setdefault(cargo.client_id, []).append(cargo)
                
            logger.info(f"Jami {len(client_cargos)} ta mijozning {TARGET_FLIGHT} dagi jo'natilgan yuklari topildi.")
            
            added_count = 0
            for client_id, c_list in client_cargos.items():
                client = await ClientService().get_client_by_code(client_id, session)
                lookup_codes = client.active_codes if client else [client_id]
                telegram_id = client.telegram_id if client else 0
                    
                # Tranzaksiya allaqachon yozilganligini tekshirish
                existing_tx = await ClientTransactionDAO.get_by_client_code_flight(
                    session, lookup_codes, TARGET_FLIGHT
                )
                
                if existing_tx:
                    logger.info(f"O'tkazib yuborildi {client_id}: Tranzaksiya allaqachon mavjud.")
                    continue
                    
                # Jami summa va vaznni hisoblash
                total_weight = 0.0
                total_price_uzs = 0.0
                
                for cargo in c_list:
                    weight = float(cargo.weight_kg or 0)
                    price_per_kg_usd = float(cargo.price_per_kg or 0)
                    price_per_kg_uzs = price_per_kg_usd * rate
                    
                    total_weight += weight
                    total_price_uzs += price_per_kg_uzs * weight
                    
                total_payment = total_price_uzs + extra_charge
                
                # Yangi qarz tranzaksiyasini yaratish
                await ClientTransactionDAO.create(
                    session,
                    {
                        "telegram_id": telegram_id,
                        "client_code": client_id,
                        "qator_raqami": 0,
                        "reys": TARGET_FLIGHT,
                        "summa": 0,
                        "vazn": str(round(total_weight, 2)),
                        "payment_type": "online",
                        "payment_status": "pending",
                        "paid_amount": 0,
                        "total_amount": total_payment,
                        "remaining_amount": total_payment,
                        "payment_balance_difference": -total_payment, # Qarz
                        "is_taken_away": False,
                    }
                )
                added_count += 1
                logger.info(f"Qarz qo'shildi {client_id}: {total_payment} UZS")
                
            await session.commit()
            logger.info(f"Tugadi. Jami {added_count} ta yangi tranzaksiya (qarz) yozildi.")

if __name__ == "__main__":
    asyncio.run(main())
