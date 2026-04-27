"""Convert legacy ``AKB{rr}-{ds}/{seq}`` client codes in every table that
references them.

Phase 4e's :mod:`scripts.convert_extra_codes_to_short` only touched the
``clients`` table.  Tables that **reference** client codes by string
(``flight_cargos.client_id``, ``expected_flight_cargos.client_code``,
``client_transactions.client_code``, ``cargo_items.client_id``,
``client_extra_passport.client_code``, ``client_payment_events`` …)
still contain the pre-Phase-4e values.  As a result, queries that join
on ``current_user.active_codes`` (the new short codes) return zero rows.

This script runs the same ``_convert`` logic from ``convert_extra_codes_to_short``
across every column that stores a client code as text.  It is **idempotent**
— rows whose value does not match the legacy regex are skipped, so re-runs
are safe.

Usage::

    python scripts/convert_legacy_codes_everywhere.py --dry-run
    python scripts/convert_legacy_codes_everywhere.py
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))

from scripts.convert_extra_codes_to_short import _convert
from src.config import config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("convert_everywhere")


# (table, column) pairs that store client codes as text.
# Order does not matter because each row is rewritten independently and
# the conversion is idempotent.
_TARGETS: list[tuple[str, str]] = [
    ("flight_cargos", "client_id"),
    ("expected_flight_cargos", "client_code"),
    ("client_transaction_data", "client_code"),
    ("cargo_items", "client_id"),
    ("client_extra_passport", "client_code"),
    ("delivery_requests", "client_code"),
    ("client_payment_events", "client_code"),
    ("partner_shipment_temp", "client_code"),
    ("cargo_delivery_proofs", "client_code"),
]


async def _convert_table(
    session: AsyncSession,
    table: str,
    column: str,
    *,
    dry_run: bool,
) -> tuple[int, int]:
    """Rewrite legacy values in ``table.column``.  Returns ``(converted, skipped)``."""
    # Skip tables that do not exist in this deployment (older snapshots).
    exists = (
        await session.execute(
            text("SELECT to_regclass(:t)"),
            {"t": table},
        )
    ).scalar()
    if not exists:
        logger.info("table %s missing — skipping", table)
        return 0, 0

    rows = (
        await session.execute(
            text(
                f'SELECT DISTINCT "{column}" AS code FROM "{table}" '
                f'WHERE "{column}" IS NOT NULL '
                f"AND \"{column}\" ~ '^AKB[0-9]{{2}}-[0-9]+/[0-9]+$'"
            )
        )
    ).all()

    converted = skipped = 0
    for (old_value,) in rows:
        new_value = _convert(old_value)
        if not new_value or new_value == old_value:
            skipped += 1
            continue

        if dry_run:
            logger.info(
                "[dry-run] %s.%s: %s → %s",
                table, column, old_value, new_value,
            )
        else:
            await session.execute(
                text(
                    f'UPDATE "{table}" SET "{column}" = :new '
                    f'WHERE "{column}" = :old'
                ),
                {"new": new_value, "old": old_value},
            )
        converted += 1

    if not dry_run:
        await session.commit()
    return converted, skipped


async def main(*, dry_run: bool) -> None:
    engine = create_async_engine(config.database.database_url, future=True)
    Session: sessionmaker[AsyncSession] = sessionmaker(  # type: ignore[type-arg]
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with Session() as session:
        for table, column in _TARGETS:
            converted, skipped = await _convert_table(
                session, table, column, dry_run=dry_run
            )
            logger.info(
                "table=%s column=%s converted=%d skipped=%d",
                table, column, converted, skipped,
            )

    await engine.dispose()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(dry_run=args.dry_run))
