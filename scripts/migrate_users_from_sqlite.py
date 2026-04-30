"""One-shot import of legacy users from ``database.sqlite3`` into the new
``clients`` table.

Field mapping (per project decisions, 2026-04-28):

* ``client_code``     ← sqlite ``new_client_code`` as-is. When
                        ``new_client_code`` is empty, falls back to sqlite
                        ``client_code``.
* ``legacy_code``     ← sqlite ``client_code`` raw value (historical
                        ``AKB570`` / ``AKB123`` identifier).
* ``extra_code``      ← always ``NULL``.
* ``full_name``       ← ``fullname``
* ``phone``           ← ``phone``
* ``passport_series`` ← ``passport_number``
* ``date_of_birth``   ← parsed from ``birth_date``
* ``pinfl``           ← ``pinfl``
* ``address``         ← ``address``
* ``region`` / ``district`` ← legacy snake_case keys derived from
                              numeric ``region_code`` / ``district_code``.
* ``passport_images`` ← JSON-encoded list of Telegram file_ids.
* ``language_code``   ← ``language``
* ``is_logged_in``    ← True for ``approved``, False otherwise.
* ``role``            ← ``"user"``.

Modes
-----
* **Upsert** (default): re-running the script updates existing rows in
  place, matched first by ``telegram_id`` (when present), otherwise by
  ``legacy_code``, otherwise by ``client_code``.

* ``--override``: truncates ``clients`` before inserting fresh data.

Special duplicate handling
--------------------------
* If sqlite contains duplicate ``telegram_id`` values in the same run:
  - the FIRST row keeps its telegram_id
  - NEXT duplicate rows get ``telegram_id = NULL`` before insert/update

This prevents unique constraint violations on ``ix_clients_telegram_id``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

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

CODE_TO_LEGACY_REGION_KEY: dict[str, str] = {
    code: key for key, code in LEGACY_REGION_KEY_TO_CODE.items()
}
CODE_TO_LEGACY_DISTRICT_KEY: dict[str, str] = {
    code: key for key, code in LEGACY_DISTRICT_KEY_TO_CODE.items()
}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None

    if isinstance(value, datetime):
        return value

    s = str(value).strip()
    if not s:
        return None

    # Supported formats:
    # 2025-01-18 12:30:00
    # 2025-01-18T12:30:00
    # 2025-01-18
    # 18.01.2025
    # 15.042004  <-- weird legacy format
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d.%m%Y",
    ):
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
    files = [f for f in (front, back) if f]
    return json.dumps(files, ensure_ascii=False) if files else None


def _resolve_region(region_code: str | None) -> str | None:
    if not region_code:
        return None
    return CODE_TO_LEGACY_REGION_KEY.get(str(region_code), str(region_code))


def _resolve_district(district_code: str | None) -> str | None:
    if not district_code:
        return None
    return CODE_TO_LEGACY_DISTRICT_KEY.get(str(district_code), str(district_code))


def _normalize_code(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _row_to_data(row: sqlite3.Row) -> dict[str, Any] | None:
    """Convert a sqlite `users` row to a `clients` insert/update dict.

    Returns None when the row carries no usable identity:
    no telegram_id AND no client_code/new_client_code.
    """
    telegram_id_raw = row["telegram_id"]
    telegram_id: int | None = None

    try:
        if telegram_id_raw not in (None, "", "None"):
            telegram_id = int(telegram_id_raw)
    except (TypeError, ValueError):
        logger.warning("Invalid telegram_id %r, forcing NULL", telegram_id_raw)
        telegram_id = None

    legacy_value = _normalize_code(row["client_code"])
    new_value = _normalize_code(row["new_client_code"])

    # Canonical client_code prefers sqlite new_client_code exactly as stored,
    # then falls back to the old client_code value.
    primary_code = new_value or legacy_value

    if telegram_id is None and not primary_code:
        return None

    return {
        "telegram_id": telegram_id,
        "full_name": (row["fullname"] or "").strip(),
        "phone": _normalize_code(row["phone"]),
        "passport_series": _normalize_code(row["passport_number"]),
        "pinfl": _normalize_code(row["pinfl"]),
        "date_of_birth": _parse_date(row["birth_date"]),
        "address": _normalize_code(row["address"]),
        "region": _resolve_region(row["region_code"]),
        "district": _resolve_district(row["district_code"]),
        "passport_images": _passport_images_json(
            row["passport_front_file_id"], row["passport_back_file_id"]
        ),
        "client_code": primary_code,
        "extra_code": None,
        "legacy_code": legacy_value,
        "language_code": (_normalize_code(row["language"]) or "uz")[:5],
        "is_logged_in": (row["verification_status"] == "approved"),
        "role": "user",
        "created_at": _parse_dt(row["registered_at"]) or datetime.utcnow(),
    }


# ---------------------------------------------------------------------------
# DB lookup helpers
# ---------------------------------------------------------------------------

async def _find_existing(
    session: AsyncSession,
    data: dict[str, Any],
) -> Client | None:
    """Locate an existing Client row that this sqlite row should update.

    Match priority:
    1) telegram_id (if present)
    2) legacy_code
    3) client_code
    """
    tg = data.get("telegram_id")
    if tg is not None:
        existing = (
            await session.execute(
                select(Client).where(Client.telegram_id == tg)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    legacy_code = data.get("legacy_code")
    if legacy_code:
        existing = (
            await session.execute(
                select(Client).where(Client.legacy_code == legacy_code)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    client_code = data.get("client_code")
    if client_code:
        existing = (
            await session.execute(
                select(Client).where(Client.client_code == client_code)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    return None


async def _exists_other_by_telegram_id(
    session: AsyncSession,
    telegram_id: int,
    *,
    current_id: int | None = None,
) -> bool:
    """Check whether another row already uses this telegram_id."""
    query = select(Client.id).where(Client.telegram_id == telegram_id)
    if current_id is not None:
        query = query.where(Client.id != current_id)

    found = (await session.execute(query.limit(1))).scalar_one_or_none()
    return found is not None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

async def migrate(
    sqlite_path: Path,
    *,
    dry_run: bool,
    limit: int | None,
    override: bool,
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

    inserted = 0
    updated = 0
    skipped_invalid = 0
    skipped_client_code_duplicates = 0
    skipped_legacy_code_duplicates = 0
    telegram_id_nullified = 0

    # In-run duplicate trackers
    seen_telegram_ids: set[int] = set()
    seen_client_codes: set[str] = set()
    seen_legacy_codes: set[str] = set()

    async with Session() as session:
        if override:
            if dry_run:
                logger.info("[dry-run] would TRUNCATE clients RESTART IDENTITY CASCADE")
            else:
                logger.warning("--override: deleting every row in clients")
                await session.execute(
                    text("TRUNCATE TABLE clients RESTART IDENTITY CASCADE")
                )
                await session.commit()

        for idx, row in enumerate(rows, start=1):
            data = _row_to_data(row)
            if data is None:
                skipped_invalid += 1
                logger.warning("Skipping invalid sqlite row #%d: no telegram_id and no code", idx)
                continue

            # ---------------------------------------------------------------
            # STEP 1: In-run duplicate telegram_id handling
            # Rule:
            #   - first row keeps telegram_id
            #   - next duplicate rows become telegram_id = None
            # ---------------------------------------------------------------
            tg = data.get("telegram_id")
            if tg is not None:
                if tg in seen_telegram_ids:
                    logger.warning(
                        "Duplicate telegram_id in sqlite run: %s -> forcing NULL "
                        "(client_code=%s, legacy_code=%s)",
                        tg,
                        data.get("client_code"),
                        data.get("legacy_code"),
                    )
                    data["telegram_id"] = None
                    telegram_id_nullified += 1
                else:
                    seen_telegram_ids.add(tg)

            # ---------------------------------------------------------------
            # STEP 2: In-run duplicate client_code handling
            # We skip later duplicates to avoid unique collisions.
            # ---------------------------------------------------------------
            client_code = data.get("client_code")
            if client_code:
                if client_code in seen_client_codes:
                    logger.warning(
                        "Skipping duplicate client_code in sqlite run: %s "
                        "(telegram_id=%s, legacy_code=%s)",
                        client_code,
                        data.get("telegram_id"),
                        data.get("legacy_code"),
                    )
                    skipped_client_code_duplicates += 1
                    continue
                seen_client_codes.add(client_code)

            # ---------------------------------------------------------------
            # STEP 3: In-run duplicate legacy_code handling
            # We skip later duplicates to avoid weird alias collisions.
            # ---------------------------------------------------------------
            legacy_code = data.get("legacy_code")
            if legacy_code:
                if legacy_code in seen_legacy_codes:
                    logger.warning(
                        "Skipping duplicate legacy_code in sqlite run: %s "
                        "(telegram_id=%s, client_code=%s)",
                        legacy_code,
                        data.get("telegram_id"),
                        data.get("client_code"),
                    )
                    skipped_legacy_code_duplicates += 1
                    continue
                seen_legacy_codes.add(legacy_code)

            # ---------------------------------------------------------------
            # STEP 4: In upsert mode, find existing row
            # ---------------------------------------------------------------
            existing = None if override else await _find_existing(session, data)

            # ---------------------------------------------------------------
            # STEP 5: Extra DB-level protection for telegram_id
            # Even after in-run handling, DB may already contain same tg in upsert mode.
            # If conflict exists on another row, nullify telegram_id.
            # ---------------------------------------------------------------
            tg_after = data.get("telegram_id")
            if tg_after is not None:
                conflict_exists = await _exists_other_by_telegram_id(
                    session,
                    tg_after,
                    current_id=(existing.id if existing is not None else None),
                )
                if conflict_exists:
                    logger.warning(
                        "DB already has telegram_id=%s on another row -> forcing NULL "
                        "(client_code=%s, legacy_code=%s)",
                        tg_after,
                        data.get("client_code"),
                        data.get("legacy_code"),
                    )
                    data["telegram_id"] = None
                    telegram_id_nullified += 1

            # ---------------------------------------------------------------
            # STEP 6: Update existing row
            # ---------------------------------------------------------------
            if existing is not None:
                if dry_run:
                    logger.info(
                        "[dry-run] update id=%s telegram_id=%s client_code=%s legacy_code=%s",
                        existing.id,
                        data["telegram_id"],
                        data["client_code"],
                        data["legacy_code"],
                    )
                else:
                    for k, v in data.items():
                        # Keep original created_at on updates
                        if k == "created_at":
                            continue
                        setattr(existing, k, v)

                updated += 1
                continue

            # ---------------------------------------------------------------
            # STEP 7: Insert new row
            # ---------------------------------------------------------------
            if dry_run:
                logger.info(
                    "[dry-run] insert telegram_id=%s client_code=%s legacy_code=%s",
                    data["telegram_id"],
                    data["client_code"],
                    data["legacy_code"],
                )
            else:
                session.add(Client(**data))

            inserted += 1

            # Flush every 100 operations
            if (inserted + updated) % 100 == 0 and not dry_run:
                try:
                    await session.flush()
                    logger.info(
                        "flushed (inserted=%d updated=%d tg_nullified=%d skipped_client_code_dup=%d skipped_legacy_code_dup=%d)",
                        inserted,
                        updated,
                        telegram_id_nullified,
                        skipped_client_code_duplicates,
                        skipped_legacy_code_duplicates,
                    )
                except Exception:
                    logger.exception("flush failed — rolling back batch")
                    await session.rollback()
                    raise

        # Final commit
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
        "DONE: inserted=%d updated=%d skipped_invalid=%d tg_nullified=%d "
        "skipped_client_code_dup=%d skipped_legacy_code_dup=%d total=%d",
        inserted,
        updated,
        skipped_invalid,
        telegram_id_nullified,
        skipped_client_code_duplicates,
        skipped_legacy_code_duplicates,
        len(rows),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Migrate users from sqlite to postgres clients table")
    p.add_argument("--sqlite", default=str(DEFAULT_SQLITE_PATH))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--override",
        action="store_true",
        help="TRUNCATE clients (CASCADE) before inserting. Destructive.",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        migrate(
            sqlite_path=Path(args.sqlite),
            dry_run=args.dry_run,
            limit=args.limit,
            override=args.override,
        )
    )
