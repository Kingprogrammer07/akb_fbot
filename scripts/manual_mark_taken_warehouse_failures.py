"""Recover known warehouse bulk-mark-taken failures.

This script is for the 2026-06-17 production failures where proof photos were
uploaded to S3 but DB insert failed because the database still allowed
``mandarin`` instead of ``akb``.

Dry-run by default. Pass ``--apply`` to write changes.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, os.path.abspath(ROOT))

from src.config import config
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.dao.admin_account import AdminAccountDAO
from src.infrastructure.database.dao.admin_audit_log import AdminAuditLogDAO
from src.infrastructure.database.dao.cargo_delivery_proof import CargoDeliveryProofDAO
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.tools.datetime_utils import get_current_time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("manual_mark_taken_warehouse_failures")


@dataclass(frozen=True)
class RecoveryTarget:
    transaction_id: int
    photo_s3_keys: tuple[str, ...]


DEFAULT_TARGETS: dict[int, RecoveryTarget] = {
    5945: RecoveryTarget(
        transaction_id=5945,
        photo_s3_keys=(
            "warehouse/5945/0_5945_20260617_100144_387b2dcc.webp",
        ),
    ),
    6317: RecoveryTarget(
        transaction_id=6317,
        photo_s3_keys=(
            "warehouse/6317/0_6317_20260617_095749_d2523678.webp",
            "warehouse/6317/0_6317_20260617_095901_0afef22d.webp",
            "warehouse/6317/0_6317_20260617_095913_7d736082.webp",
            "warehouse/6317/0_6317_20260617_095916_f48a333d.webp",
        ),
    ),
    6330: RecoveryTarget(
        transaction_id=6330,
        photo_s3_keys=(
            "warehouse/6330/0_6330_20260617_095414_be60a579.webp",
        ),
    ),
    6332: RecoveryTarget(
        transaction_id=6332,
        photo_s3_keys=(
            "warehouse/6332/0_6332_20260617_112857_cba6d468.webp",
        ),
    ),
    6580: RecoveryTarget(
        transaction_id=6580,
        photo_s3_keys=(
            "warehouse/6580/0_6580_20260617_095611_a7aecaa9.webp",
        ),
    ),
    6617: RecoveryTarget(
        transaction_id=6617,
        photo_s3_keys=(
            "warehouse/6617/0_6617_20260617_100219_77ee1f0d.webp",
        ),
    ),
}


def _money(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _select_targets(only: list[int] | None) -> list[RecoveryTarget]:
    if not only:
        return list(DEFAULT_TARGETS.values())

    unknown = sorted(set(only) - set(DEFAULT_TARGETS))
    if unknown:
        raise SystemExit(f"Unknown transaction_id for this recovery set: {unknown}")

    return [DEFAULT_TARGETS[tx_id] for tx_id in only]


async def recover(
    *,
    apply: bool,
    only: list[int] | None,
    admin_id: int,
    delivery_method: str,
) -> None:
    targets = _select_targets(only)
    target_ids = [target.transaction_id for target in targets]
    now = get_current_time()

    async with DatabaseClient(config.database.database_url) as db_client:
        async with db_client.session_factory() as session:
            admin = await AdminAccountDAO.get_by_id_with_relations(session, admin_id)
            if admin is None:
                message = f"Admin account not found: admin_id={admin_id}"
                if apply:
                    raise SystemExit(message)
                logger.warning("%s; dry-run can continue", message)

            result = await session.execute(
                select(ClientTransaction).where(ClientTransaction.id.in_(target_ids))
            )
            tx_by_id = {tx.id: tx for tx in result.scalars().all()}
            proven_ids = await CargoDeliveryProofDAO.get_proven_transaction_ids(
                session,
                target_ids,
            )

            changed = 0
            skipped_missing = 0
            skipped_noop = 0

            for target in targets:
                tx = tx_by_id.get(target.transaction_id)
                if tx is None:
                    skipped_missing += 1
                    logger.warning("skip missing transaction_id=%s", target.transaction_id)
                    continue

                client = await ClientDAO.get_by_client_code(session, tx.client_code)
                logger.info(
                    "%s tx=%s code=%s name=%s phone=%s tg=%s flight=%s row=%s "
                    "payment=%s remaining=%s already_taken=%s proof_exists=%s photos=%d",
                    "[apply]" if apply else "[dry-run]",
                    tx.id,
                    tx.client_code,
                    client.full_name if client else None,
                    client.phone if client else None,
                    client.telegram_id if client else tx.telegram_id,
                    tx.reys,
                    tx.qator_raqami,
                    tx.payment_status,
                    _money(tx.remaining_amount),
                    tx.is_taken_away,
                    tx.id in proven_ids,
                    len(target.photo_s3_keys),
                )

                needs_proof = tx.id not in proven_ids
                needs_taken_flag = not tx.is_taken_away
                if not needs_proof and not needs_taken_flag:
                    skipped_noop += 1
                    continue

                if apply:
                    if needs_proof:
                        await CargoDeliveryProofDAO.create(
                            session=session,
                            transaction_id=tx.id,
                            delivery_method=delivery_method,
                            photo_s3_keys=list(target.photo_s3_keys),
                            marked_by_admin_id=admin_id,
                        )

                    if needs_taken_flag:
                        tx.is_taken_away = True
                        tx.taken_away_date = now
                        session.add(tx)

                    await AdminAuditLogDAO.log(
                        session=session,
                        action="MANUAL_RECOVER_WAREHOUSE_MARK_TAKEN",
                        admin_id=admin_id,
                        role_snapshot=admin.role_name if admin else "manual",
                        details={
                            "source": "bulk_mark_taken_2026_06_17_constraint_failure",
                            "transaction_id": tx.id,
                            "client_code": tx.client_code,
                            "flight_name": tx.reys,
                            "delivery_method": delivery_method,
                            "photo_s3_keys": list(target.photo_s3_keys),
                            "created_proof": needs_proof,
                            "marked_taken": needs_taken_flag,
                        },
                    )

                changed += 1

            if apply:
                await session.commit()
                logger.info("Committed manual recovery changes.")
            else:
                logger.info("Dry-run only. Re-run with --apply to write changes.")

            logger.info(
                "DONE changed=%d skipped_missing=%d skipped_noop=%d apply=%s",
                changed,
                skipped_missing,
                skipped_noop,
                apply,
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually update Postgres. Without this flag the script is a dry-run.",
    )
    parser.add_argument(
        "--only",
        action="append",
        type=int,
        default=None,
        help="Recover only a known transaction_id. Can be passed more than once.",
    )
    parser.add_argument(
        "--admin-id",
        type=int,
        default=13,
        help="AdminAccount id to attach to proof/audit rows.",
    )
    parser.add_argument(
        "--delivery-method",
        choices=["uzpost", "bts", "akb", "yandex", "self_pickup"],
        default="akb",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        recover(
            apply=args.apply,
            only=args.only,
            admin_id=args.admin_id,
            delivery_method=args.delivery_method,
        )
    )
