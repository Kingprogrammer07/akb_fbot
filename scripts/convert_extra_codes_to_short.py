"""Rewrite legacy ``AKB{rr}-{ds}/{seq}`` codes into the new short format.

For every ``Client`` row whose ``client_code`` or ``extra_code`` matches
the pattern ``AKB{region}-{district}/{seq}``, the script computes the
new short code and writes it back **into the same column**:

* Tashkent (region 01) → ``A{district_subcode:02d}-{seq}``
  Example: ``AKB01-2/14`` → ``A02-14``.
* Other regions → ``A{R}{D}{seq}`` where ``R``/``D`` are the first ASCII
  letters of the region and district display names.
  Example: ``AKB80-2/9`` (Buxoro G'ijduvon) → ``ABG9``.

The seq number is preserved verbatim from the source code so historical
ordering is not lost.

Collision safety
----------------
Old codes used per-region seq scoping (e.g. Andijon had a single seq=14
that lived in some district).  The new format uses the (region,
district) letter pair as a namespace, so two old districts of the same
region with the same seq would collapse into one new code.  The script
detects this *before* writing: if the target value is already taken (by
another row in the same column), the row is skipped and reported on
stdout for manual review.

Usage
-----
::

    python scripts/convert_extra_codes_to_short.py --dry-run
    python scripts/convert_extra_codes_to_short.py
    python scripts/convert_extra_codes_to_short.py --column extra_code

The default column is ``extra_code`` because that is where the legacy
``AKB{rr}-{ds}/{seq}`` values live in the production data set; pass
``--column client_code`` to also rewrite the primary code column.
``--column both`` runs the conversion in two passes.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))

from src.api.utils.code_generator import _REGION_PREFIX
from src.config import config
from src.infrastructure.database.models.client import Client

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("convert_codes")


_LEGACY_RE = re.compile(r"^AKB(?P<r>\d{2})-(?P<d>\d+)/(?P<seq>\d+)$")


def _convert(code: str) -> str | None:
    """Return the new short code, or ``None`` when the input does not match.

    * Tashkent (region 01) → ``A{district_subcode:02d}-{seq}``.
    * Other regions       → ``{REGION_PREFIX}{seq}`` where ``REGION_PREFIX``
                            is the hand-picked 3-char code from
                            :data:`code_generator._REGION_PREFIX`.
    """
    m = _LEGACY_RE.match(code or "")
    if not m:
        return None
    region_code = m.group("r")
    district_sub = m.group("d")
    seq = m.group("seq")

    if region_code == "01":
        return f"A{int(district_sub):02d}-{seq}"

    prefix = _REGION_PREFIX.get(region_code)
    if not prefix:
        logger.warning(
            "no region prefix configured for region_code=%r (code=%r)",
            region_code, code,
        )
        return None
    return f"{prefix}{seq}"


async def _run_for_column(
    session: AsyncSession,
    column_name: str,
    *,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Convert all matching rows in ``Client.<column_name>`` in place.

    Returns ``(converted, skipped_collision, skipped_unmatched)``.
    """
    column = getattr(Client, column_name)

    # Pull every candidate row in one query.  Postgres regex hits the
    # column index when one exists, but even on a sequential scan this
    # is a one-off operation.
    rows = (
        await session.execute(
            select(Client.id, column).where(
                column.is_not(None),
                column.op("~")(r"^AKB\d{2}-\d+/\d+$"),
            )
        )
    ).all()

    if not rows:
        logger.info("no rows to convert in column %s", column_name)
        return 0, 0, 0

    logger.info("processing %d rows from column %s", len(rows), column_name)

    # Snapshot of values currently in this column for collision checks.
    existing_values: set[str] = {
        v
        for (v,) in (
            await session.execute(select(column).where(column.is_not(None)))
        ).all()
    }

    converted = collisions = unmatched = 0
    new_values_taken: set[str] = set()  # this run

    for row_id, old_value in rows:
        new_value = _convert(old_value)
        if new_value is None:
            unmatched += 1
            continue

        if new_value == old_value:
            continue  # idempotent — already converted somehow

        if new_value in existing_values or new_value in new_values_taken:
            collisions += 1
            logger.warning(
                "collision skipped: id=%s %s → %s already taken",
                row_id, old_value, new_value,
            )
            continue

        if dry_run:
            logger.info(
                "[dry-run] id=%s %s → %s (column=%s)",
                row_id, old_value, new_value, column_name,
            )
        else:
            await session.execute(
                update(Client).where(Client.id == row_id).values(
                    **{column_name: new_value}
                )
            )

        existing_values.discard(old_value)
        new_values_taken.add(new_value)
        converted += 1

    if not dry_run:
        await session.commit()

    return converted, collisions, unmatched


async def main(columns: list[str], *, dry_run: bool) -> None:
    engine = create_async_engine(config.database.database_url, future=True)
    Session: sessionmaker[AsyncSession] = sessionmaker(  # type: ignore[type-arg]
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with Session() as session:
        for col in columns:
            converted, collisions, unmatched = await _run_for_column(
                session, col, dry_run=dry_run
            )
            logger.info(
                "column=%s converted=%d skipped_collision=%d skipped_unmatched=%d",
                col, converted, collisions, unmatched,
            )

    await engine.dispose()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument(
        "--column",
        choices=["client_code", "extra_code", "both"],
        default="extra_code",
        help="Which column to convert (default: extra_code).",
    )
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    cols = (
        ["client_code", "extra_code"]
        if args.column == "both"
        else [args.column]
    )
    asyncio.run(main(cols, dry_run=args.dry_run))
