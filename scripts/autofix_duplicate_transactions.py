"""
Dublikat tranzaksiyalarni avtomatik tozalash.

FAQAT ikkita xavfsiz holatda o'chiradi:
  1. Backfill + real: pending/qator=0/summa=0/bal<0 qatorni o'chir, real to'lovni qoldir
  2. Ghost + real: events=0 qatorni o'chir, events>0 qatorni qoldir

Ikki tomonlama real to'lovlarga (events>0 + events>0) TEGMAYDI — qo'lda ko'rish kerak.

ISHLATISH:
  python scripts/autofix_duplicate_transactions.py --dry-run
  python scripts/autofix_duplicate_transactions.py --execute
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
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.client_transaction import ClientTransaction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _is_backfill(tx: ClientTransaction) -> bool:
    return (
        tx.qator_raqami == 0
        and tx.payment_status == "pending"
        and float(tx.summa or 0) == 0.0
        and float(tx.payment_balance_difference or 0) < 0
    )


async def run(dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "EXECUTE"
    logger.info(f"===== AUTOFIX DUPLICATES [{mode}] =====")

    async with DatabaseClient(config.database.database_url) as db:
        async with db.session_factory() as session:
            try:
                clients = list(
                    (await session.execute(select(Client))).scalars().all()
                )
                all_txs = list(
                    (
                        await session.execute(
                            select(ClientTransaction).options(
                                selectinload(ClientTransaction.payment_events)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

                # client_code → Client mapping
                code_to_client: dict[str, Client] = {}
                for c in clients:
                    for code in c.active_codes:
                        code_to_client[code.upper()] = c

                # (client.id, normalized_reys) bo'yicha guruhlash
                grouped: dict[tuple, list[ClientTransaction]] = {}
                for tx in all_txs:
                    if not tx.reys:
                        continue
                    rn = tx.reys.strip().upper()
                    if rn.startswith(("WALLET_ADJ", "SYS_ADJ", "UZPOST")):
                        continue
                    client = code_to_client.get(tx.client_code.strip().upper())
                    key = (client.id if client else f"nc_{tx.client_code}", rn)
                    grouped.setdefault(key, []).append(tx)

                to_delete: list[tuple[ClientTransaction, str]] = []
                manual: list[list[ClientTransaction]] = []

                for txs in grouped.values():
                    if len(txs) < 2:
                        continue

                    backfills = [t for t in txs if _is_backfill(t)]
                    reals = [t for t in txs if not _is_backfill(t)]

                    if backfills and reals:
                        # Holat 1: backfill + real → backfillni o'chir
                        for b in backfills:
                            to_delete.append(
                                (b, f"backfill → KEEP id={reals[0].id} "
                                    f"cc={reals[0].client_code} "
                                    f"status={reals[0].payment_status}")
                            )
                        continue

                    # Ikkalasi ham "real" (not backfill) — events tekshiruv
                    without_events = [t for t in txs if len(t.payment_events) == 0]
                    with_events = [t for t in txs if len(t.payment_events) > 0]

                    if without_events and with_events:
                        # Holat 2: ghost (events=0) + real → ghostni o'chir
                        for g in without_events:
                            to_delete.append(
                                (g, f"ghost(events=0) → KEEP id={with_events[0].id} "
                                    f"cc={with_events[0].client_code} "
                                    f"status={with_events[0].payment_status}")
                            )
                        continue

                    # Ikkalasida ham real to'lov → qo'lda tekshirish
                    manual.append(txs)

                # --- Hisobot ---
                logger.info(f"Xavfsiz o'chirish: {len(to_delete)} ta")
                for tx, reason in to_delete:
                    logger.warning(
                        f"  {'[DELETE]' if not dry_run else '[DRY-DELETE]'} "
                        f"id={tx.id} cc={tx.client_code} reys={tx.reys} "
                        f"status={tx.payment_status} "
                        f"bal={float(tx.payment_balance_difference or 0):,.0f} | "
                        f"{reason}"
                    )

                if manual:
                    logger.info(
                        f"\nQO'LDA TEKSHIRISH KERAK (ikkalasi real to'lov): "
                        f"{len(manual)} ta guruh"
                    )
                    for txs in manual:
                        logger.info(
                            f"  reys={txs[0].reys} "
                            f"tg={txs[0].telegram_id}"
                        )
                        for t in txs:
                            logger.info(
                                f"    id={t.id} cc={t.client_code} "
                                f"status={t.payment_status} "
                                f"paid={float(t.paid_amount or 0):,.0f} "
                                f"events={len(t.payment_events)}"
                            )

                if not to_delete:
                    logger.info("O'chiriladigan narsa topilmadi.")
                    return

                if dry_run:
                    logger.info("\nDRY-RUN: hech narsa o'zgartirilmadi.")
                    logger.info(
                        "Haqiqiy o'chirish: python scripts/autofix_duplicate_transactions.py --execute"
                    )
                    return

                for tx, _ in to_delete:
                    await session.delete(tx)

                await session.commit()
                logger.info(
                    f"\nMUVAFFAQIYATLI: {len(to_delete)} ta dublikat o'chirildi."
                )

            except Exception:
                logger.exception("Xatolik! Rollback.")
                await session.rollback()
                raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Dublikat tranzaksiyalarni autofix")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
