"""
Faqat 4 ta "ghost" tranzaksiyani o'chiradi.

Ghost tranzaksiya = payment_events yo'q (events=0) + payment_balance_difference=0
ya'ni hech qanday real pul harakati bo'lmagan, script tomonidan qo'lda
to'ldirilgan va endi keraksiz bo'lib qolgan yozuvlar.

Xavfsizlik tekshiruvi:
  - events > 0 bo'lsa — O'CHIRMAYMIZ
  - payment_balance_difference != 0 bo'lsa — O'CHIRMAYMIZ
  - Faqat target IDlar ro'yxatidan o'chiramiz

ISHLATISH:
  python scripts/cleanup_ghost_transactions.py --dry-run
  python scripts/cleanup_ghost_transactions.py --execute
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import config
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.models.client_transaction import ClientTransaction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Faqat shu 4 ta ID ga tegamiz — qo'lda tekshirilgan, 100% xavfsiz
SAFE_GHOST_IDS: list[int] = [189, 195, 198, 204]


async def run(dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "EXECUTE"
    logger.info(f"===== GHOST CLEANUP [{mode}] =====")

    async with DatabaseClient(config.database.database_url) as db_client:
        async with db_client.session_factory() as session:
            try:
                txs = list(
                    (
                        await session.execute(
                            select(ClientTransaction)
                            .where(ClientTransaction.id.in_(SAFE_GHOST_IDS))
                            .options(selectinload(ClientTransaction.payment_events))
                        )
                    )
                    .scalars()
                    .all()
                )

                confirmed_safe: list[ClientTransaction] = []
                skipped: list[ClientTransaction] = []

                for tx in txs:
                    event_count = len(tx.payment_events)
                    bal_diff = float(tx.payment_balance_difference or 0)

                    # Ikki qavat xavfsizlik tekshiruvi
                    if event_count > 0 or bal_diff != 0.0:
                        skipped.append(tx)
                        logger.warning(
                            f"SKIP id={tx.id} cc={tx.client_code} — "
                            f"events={event_count}, bal_diff={bal_diff} "
                            f"(xavfsiz emas, tegmadik)"
                        )
                    else:
                        confirmed_safe.append(tx)
                        logger.info(
                            f"{'[DELETE]' if not dry_run else '[DRY DELETE]'} "
                            f"id={tx.id} | cc={tx.client_code} | "
                            f"tg={tx.telegram_id} | reys={tx.reys} | "
                            f"paid={float(tx.paid_amount or 0):,.0f} | "
                            f"events=0 | bal_diff=0"
                        )

                logger.info(f"Xavfsiz o'chirish: {len(confirmed_safe)} ta")
                logger.info(f"O'tkazib yuborilgan: {len(skipped)} ta")

                if not confirmed_safe:
                    logger.info("O'chiriladigan narsa topilmadi.")
                    return

                if dry_run:
                    logger.info("DRY-RUN: hech narsa o'zgartirilmadi.")
                    return

                for tx in confirmed_safe:
                    await session.delete(tx)

                await session.commit()
                logger.info(
                    f"MUVAFFAQIYATLI: {len(confirmed_safe)} ta ghost tranzaksiya o'chirildi."
                )

            except Exception:
                logger.exception("Xatolik! Rollback.")
                await session.rollback()
                raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Ghost tranzaksiyalarni tozalash")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
