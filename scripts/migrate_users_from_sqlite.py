"""One-shot import of legacy users from ``database.sqlite3`` into the new
``clients`` table.

Field mapping (per project decisions):

* ``client_code``       ← sqlite ``client_code``  (whichever format —
                          when ``old_client_code`` is also set sqlite's
                          ``client_code`` already mirrors it).
* ``extra_code``        ← sqlite ``new_client_code`` (only when present
                          and different from ``client_code``).
* ``full_name``         ← ``fullname``
* ``phone``             ← ``phone``
* ``passport_series``   ← ``passport_number``
* ``date_of_birth``     ← parsed from ``birth_date`` text.
* ``pinfl``             ← ``pinfl``
* ``address``           ← ``address``
* ``region`` / ``district``
                        ← converted from numeric ``region_code`` /
                          ``district_code`` to the legacy snake_case
                          keys used elsewhere in the project (e.g.
                          ``toshkent_city``, ``uchtepa``).  Stored as
                          free-text values matching the format the
                          frontend currently sends and renders.
* ``passport_images``   ← JSON-encoded list of any non-empty
                          ``passport_front_file_id`` /
                          ``passport_back_file_id`` (Telegram file_ids
                          only — S3 upload deferred to a later phase).
* ``language_code``     ← ``language``
* ``created_at``        ← ``registered_at`` (parsed)
* ``is_logged_in``      ← True for ``approved`` users, False for
                          ``pending``.
* ``telegram_id``       ← ``telegram_id`` (NULL allowed; clients can
                          re-link via the existing login flow later).
* ``role``              ← ``"user"`` (clients model default).

The script is **idempotent**: each user is matched first by
``telegram_id`` (when present), otherwise by ``client_code``.  Existing
rows are left untouched; only missing rows are inserted.

Run::

    python scripts/migrate_users_from_sqlite.py

Optional flags:
    --dry-run     parse + log but do not write to Postgres.
    --limit N     process only the first N rows (useful for smoke tests).
    --sqlite PATH path to the sqlite file (defaults to ./database.sqlite3).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Make `src` importable when running the script directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))

from src.api.utils.constants import (
    LEGACY_DISTRICT_KEY_TO_CODE,
    LEGACY_REGION_KEY_TO_CODE,
)
from src.config import config
from src.infrastructure.database.models.client import Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("migrate_users")


# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

DEFAULT_SQLITE_PATH = ROOT / "database.sqlite3"

# Inverse lookups: numeric code → legacy snake_case key.
# These match the format `clients.region` / `clients.district` already use
# elsewhere in the project (e.g. profile_router, auth router).
CODE_TO_LEGACY_REGION_KEY: dict[str, str] = {
    code: key for key, code in LEGACY_REGION_KEY_TO_CODE.items()
}
CODE_TO_LEGACY_DISTRICT_KEY: dict[str, str] = {
    code: key for key, code in LEGACY_DISTRICT_KEY_TO_CODE.items()
}


def _parse_dt(value: Any) -> datetime | None:
    """Parse a sqlite TIMESTAMP column.  Tolerant to ``None`` / empty."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    logger.warning("Could not parse datetime value %r", value)
    return None


def _parse_date(value: Any) -> date | None:
    dt = _parse_dt(value)
    return dt.date() if dt else None


def _passport_images_json(front: str | None, back: str | None) -> str | None:
    """Build JSON array of Telegram file_ids (empty → ``None``)."""
    files = [f for f in (front, back) if f]
    return json.dumps(files) if files else None


def _resolve_region(region_code: str | None) -> str | None:
    """Numeric region code → legacy snake_case key (or pass-through)."""
    if not region_code:
        return None
    return CODE_TO_LEGACY_REGION_KEY.get(region_code, region_code)


def _resolve_district(district_code: str | None) -> str | None:
    if not district_code:
        return None
    return CODE_TO_LEGACY_DISTRICT_KEY.get(district_code, district_code)


def _resolve_codes(row: sqlite3.Row) -> tuple[str | None, str | None]:
    """Return ``(client_code, extra_code)`` for a given sqlite row.

    * ``client_code``  → sqlite ``client_code`` (whichever format it
                         currently holds — old ``AKBNNN`` for legacy users
                         or new ``AKBRR-DD/N`` for already-migrated users).
    * ``extra_code``   → sqlite ``new_client_code`` only when it is
                         non-empty AND different from ``client_code``;
                         otherwise NULL.  This avoids storing the same
                         value twice while keeping the new-format alias
                         available when both exist.
    """
    primary = (row["client_code"] or "").strip() or None
    new_code = (row["new_client_code"] or "").strip() or None
    extra = new_code if new_code and new_code != primary else None
    return primary, extra


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

async def migrate(
    sqlite_path: Path,
    dry_run: bool = False,
    limit: int | None = None,
) -> None:
    if not sqlite_path.exists():
        raise SystemExit(f"sqlite file not found: {sqlite_path}")

    sconn = sqlite3.connect(sqlite_path)
    sconn.row_factory = sqlite3.Row

    engine = create_async_engine(config.database.database_url, future=True)
    Session: sessionmaker[AsyncSession] = sessionmaker(  # type: ignore[type-arg]
        engine, class_=AsyncSession, expire_on_commit=False
    )

    rows = sconn.execute(
        "SELECT * FROM users ORDER BY id ASC"
        + (f" LIMIT {int(limit)}" if limit else "")
    ).fetchall()

    logger.info("Loaded %d rows from sqlite", len(rows))

    inserted = skipped_existing = skipped_invalid = 0

    async with Session() as session:
        for row in rows:
            telegram_id: int | None = row["telegram_id"]
            primary_code, extra_code = _resolve_codes(row)

            # Skip rows with neither identity (no telegram_id and no code)
            # — nothing to insert and nothing to look up later.
            if telegram_id is None and not primary_code:
                skipped_invalid += 1
                continue

            # Idempotency: if a client already exists for this telegram_id
            # or this client_code, leave it alone.
            existing = None
            if telegram_id is not None:
                existing = await session.execute(
                    select(Client).where(Client.telegram_id == telegram_id)
                )
                existing = existing.scalar_one_or_none()
            if existing is None and primary_code:
                existing = await session.execute(
                    select(Client).where(Client.client_code == primary_code)
                )
                existing = existing.scalar_one_or_none()
            if existing is not None:
                skipped_existing += 1
                continue

            data: dict[str, Any] = {
                "telegram_id": telegram_id,
                "full_name": row["fullname"] or "",
                "phone": row["phone"] or None,
                "passport_series": row["passport_number"] or None,
                "pinfl": row["pinfl"] or None,
                "date_of_birth": _parse_date(row["birth_date"]),
                "address": row["address"] or None,
                "region": _resolve_region(row["region_code"]),
                "district": _resolve_district(row["district_code"]),
                "passport_images": _passport_images_json(
                    row["passport_front_file_id"], row["passport_back_file_id"]
                ),
                "client_code": primary_code,
                "extra_code": extra_code,
                "language_code": (row["language"] or "uz")[:5],
                "is_logged_in": (row["verification_status"] == "approved"),
                "role": "user",
                "created_at": _parse_dt(row["registered_at"])
                or datetime.utcnow(),
            }

            if dry_run:
                logger.info(
                    "[dry-run] would insert telegram_id=%s code=%s extra=%s",
                    telegram_id,
                    primary_code,
                    extra_code,
                )
                inserted += 1
                continue

            client = Client(**data)
            session.add(client)
            inserted += 1

            # Flush periodically so a single bad row does not lose the
            # entire batch.  Postgres serialises the FK / unique checks
            # at flush time.
            if inserted % 100 == 0:
                try:
                    await session.flush()
                    logger.info("flushed %d so far", inserted)
                except Exception:
                    logger.exception("flush failed — rolling back batch")
                    await session.rollback()
                    raise

        if not dry_run:
            try:
                await session.commit()
            except Exception:
                logger.exception("final commit failed — rolling back")
                await session.rollback()
                raise

    sconn.close()
    await engine.dispose()

    logger.info(
        "DONE: inserted=%d skipped_existing=%d skipped_invalid=%d total=%d",
        inserted,
        skipped_existing,
        skipped_invalid,
        len(rows),
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--sqlite", default=str(DEFAULT_SQLITE_PATH))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        migrate(
            sqlite_path=Path(args.sqlite),
            dry_run=args.dry_run,
            limit=args.limit,
        )
    )
