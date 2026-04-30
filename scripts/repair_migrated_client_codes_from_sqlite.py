"""Undo accidental client_code shortening caused by an older sqlite migration.

The old ``migrate_users_from_sqlite.py`` converted sqlite ``new_client_code``
values such as ``AKB01-2/14`` into short codes such as ``A02-14`` before
writing ``clients.client_code``. This script uses the sqlite file as the
source of truth and updates only rows where that exact conversion can be
proven:

* sqlite ``new_client_code`` matches the legacy ``AKBrr-d/seq`` format
* the current Postgres ``clients.client_code`` equals the shortened value
* the row can be matched by ``telegram_id`` or ``legacy_code``
* the target raw code is not used by another client alias

By default this is a dry-run. Pass ``--apply`` to write changes.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))

from scripts.convert_extra_codes_to_short import _convert
from src.config import config
from src.infrastructure.database.models.client import Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("repair_client_codes")

DEFAULT_SQLITE_PATH = ROOT / "database.sqlite3"


@dataclass(frozen=True)
class Candidate:
    telegram_id: int | None
    legacy_code: str | None
    raw_new_code: str
    shortened_code: str


def _normalize(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _parse_telegram_id(value: Any) -> int | None:
    try:
        if value not in (None, "", "None"):
            return int(value)
    except (TypeError, ValueError):
        return None
    return None


def _load_candidates(sqlite_path: Path, limit: int | None) -> list[Candidate]:
    if not sqlite_path.exists():
        raise SystemExit(f"sqlite file not found: {sqlite_path}")

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT telegram_id, client_code, new_client_code FROM users ORDER BY id ASC"
            + (f" LIMIT {int(limit)}" if limit else "")
        ).fetchall()
    finally:
        conn.close()

    candidates: list[Candidate] = []
    seen: set[tuple[int | None, str | None, str]] = set()
    for row in rows:
        raw_new_code = _normalize(row["new_client_code"])
        if not raw_new_code:
            continue

        shortened_code = _convert(raw_new_code)
        if not shortened_code or shortened_code == raw_new_code:
            continue

        candidate = Candidate(
            telegram_id=_parse_telegram_id(row["telegram_id"]),
            legacy_code=_normalize(row["client_code"]),
            raw_new_code=raw_new_code,
            shortened_code=shortened_code,
        )
        key = (candidate.telegram_id, candidate.legacy_code, candidate.raw_new_code)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)

    return candidates


async def _find_client(session: AsyncSession, candidate: Candidate) -> Client | None:
    clauses = []
    if candidate.telegram_id is not None:
        clauses.append(Client.telegram_id == candidate.telegram_id)
    if candidate.legacy_code:
        clauses.append(func.upper(Client.legacy_code) == candidate.legacy_code.upper())
    if not clauses:
        return None

    result = await session.execute(select(Client).where(or_(*clauses)).limit(2))
    clients = result.scalars().all()
    if len(clients) != 1:
        return None
    return clients[0]


async def _target_used_by_other(
    session: AsyncSession,
    target_code: str,
    current_client_id: int,
) -> bool:
    code = target_code.upper()
    result = await session.execute(
        select(Client.id)
        .where(
            Client.id != current_client_id,
            or_(
                func.upper(Client.client_code) == code,
                func.upper(Client.extra_code) == code,
                func.upper(Client.legacy_code) == code,
            ),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def repair(sqlite_path: Path, *, apply: bool, limit: int | None) -> None:
    candidates = _load_candidates(sqlite_path, limit)
    logger.info("Loaded %d repair candidates from sqlite", len(candidates))

    engine = create_async_engine(config.database.database_url, future=True)
    Session: sessionmaker[AsyncSession] = sessionmaker(  # type: ignore[type-arg]
        engine, class_=AsyncSession, expire_on_commit=False
    )

    repaired = skipped_not_found = skipped_current_mismatch = skipped_conflict = 0

    async with Session() as session:
        for candidate in candidates:
            client = await _find_client(session, candidate)
            if client is None:
                skipped_not_found += 1
                logger.warning(
                    "skip not-found/ambiguous: tg=%s legacy=%s raw=%s shortened=%s",
                    candidate.telegram_id,
                    candidate.legacy_code,
                    candidate.raw_new_code,
                    candidate.shortened_code,
                )
                continue

            current_code = _normalize(client.client_code)
            if (current_code or "").upper() != candidate.shortened_code.upper():
                skipped_current_mismatch += 1
                continue

            if await _target_used_by_other(session, candidate.raw_new_code, client.id):
                skipped_conflict += 1
                logger.warning(
                    "skip conflict: client_id=%s %s -> %s",
                    client.id,
                    candidate.shortened_code,
                    candidate.raw_new_code,
                )
                continue

            if apply:
                client.client_code = candidate.raw_new_code
            logger.info(
                "%s client_id=%s tg=%s legacy=%s: %s -> %s",
                "repair" if apply else "[dry-run] repair",
                client.id,
                client.telegram_id,
                client.legacy_code,
                candidate.shortened_code,
                candidate.raw_new_code,
            )
            repaired += 1

        if apply:
            await session.commit()

    await engine.dispose()
    logger.info(
        "DONE: repaired=%d skipped_not_found=%d skipped_current_mismatch=%d "
        "skipped_conflict=%d apply=%s",
        repaired,
        skipped_not_found,
        skipped_current_mismatch,
        skipped_conflict,
        apply,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--sqlite", default=str(DEFAULT_SQLITE_PATH))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually update Postgres. Without this flag the script is a dry-run.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        repair(
            sqlite_path=Path(args.sqlite),
            apply=args.apply,
            limit=args.limit,
        )
    )
