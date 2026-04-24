"""Ostatka (A-) leftover statistics reporter.

Aggregates cargo data for ``A-`` prefixed flights and posts a formatted
summary to ``config.telegram.AKB_OSTATKA_GROUP_ID``.  Called from two
places:

* :class:`src.bot.handlers.admin.ostatka_sender.OstatkaBulkSender` — once a
  manual ostatka bulk send finishes, it posts a per-flight summary.
* :func:`src.bot.utils.backup_scheduler.daily_backup_task` — when the
  singleton ``StaticData.ostatka_daily_notifications`` flag is enabled, it
  calls :func:`send_daily_ostatka_stats` to post an aggregate for every
  active ostatka flight.

Filtering rules
---------------
Only cargos whose matching ``ClientTransaction.is_taken_away`` is ``False``
(or has no transaction at all) are counted.  Taken-away cargo belongs to
the client, not the warehouse, so including it in an ostatka summary would
misrepresent what is still on the shelf.

All numbers are computed inside PostgreSQL to avoid shipping entire flight
tables into Python memory.
"""
from __future__ import annotations

import html as html_module
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select

from src.bot.utils.safe_sender import safe_send_message
from src.config import config
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.tools.datetime_utils import get_current_business_time

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

OSTATKA_FLIGHT_LIKE: str = "A-%"
_DEFAULT_USD_TO_UZS_RATE: float = 12_000


# ---------------------------------------------------------------------------
# Value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OstatkaFlightStat:
    """Aggregate totals for a single ostatka flight."""

    flight_name: str
    cargo_count: int
    total_weight_kg: float
    total_amount_uzs: float

    def is_empty(self) -> bool:
        return self.cargo_count == 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def send_ostatka_stats_for_flight(
    bot: "Bot",
    flight_name: str,
) -> bool:
    """Post a single-flight ostatka statistics summary to the group.

    Args:
        bot:         aiogram bot instance.
        flight_name: Flight name to summarise (e.g. ``"A-2026-04-24"``).

    Returns:
        ``True`` when a message was posted, ``False`` when no data was found
        to report (empty flight, all cargo already taken away, etc.).
    """
    async with DatabaseClient(config.database.database_url) as db_client:
        async with db_client.session_factory() as session:
            rate = await _resolve_usd_rate(session)
            stat = await _aggregate_flight_stat(session, flight_name, rate)

    if stat is None or stat.is_empty():
        logger.info(
            "Ostatka stats: nothing to report for flight %s", flight_name
        )
        return False

    text = _format_single_flight(stat)
    await _post(bot, text)
    return True


async def send_daily_ostatka_stats(bot: "Bot") -> bool:
    """Post the daily leftover summary for every active ostatka flight.

    Invoked by the scheduler once per 24 h.  Fetches every distinct A-
    flight that still has non-taken-away cargo and posts a compact multi-
    flight digest.  Returns ``False`` when there is nothing to report so
    the caller can distinguish "disabled feature" from "quiet day".
    """
    async with DatabaseClient(config.database.database_url) as db_client:
        async with db_client.session_factory() as session:
            rate = await _resolve_usd_rate(session)
            stats = await _aggregate_all_flights(session, rate)

    active = [s for s in stats if not s.is_empty()]
    if not active:
        logger.info("Ostatka daily stats: no active flights to report")
        return False

    text = _format_daily_digest(active)
    await _post(bot, text)
    return True


async def is_daily_ostatka_enabled() -> bool:
    """Return the ``StaticData.ostatka_daily_notifications`` flag."""
    try:
        async with DatabaseClient(config.database.database_url) as db_client:
            async with db_client.session_factory() as session:
                static_data = await StaticDataDAO.get_first(session)
                return bool(getattr(static_data, "ostatka_daily_notifications", False))
    except Exception:
        logger.exception("Ostatka stats: failed to read daily flag")
        return False


# ---------------------------------------------------------------------------
# Aggregation helpers (private)
# ---------------------------------------------------------------------------


def _active_cargo_subquery():
    """Build a selectable of FlightCargo rows whose ClientTransaction is NOT
    flagged ``is_taken_away=True``.

    The ``LEFT OUTER JOIN`` semantics are critical: cargo with no matching
    transaction row (legacy data, send never completed, etc.) must still be
    counted as "in warehouse" — only an *explicit* ``is_taken_away=True``
    hides it.  The match is ``(flight_name, client_code)`` case-insensitive,
    mirroring the existing rules in ``ClientTransactionDAO``.
    """
    taken_away_join = and_(
        func.upper(ClientTransaction.client_code) == func.upper(FlightCargo.client_id),
        func.upper(ClientTransaction.reys) == func.upper(FlightCargo.flight_name),
        ClientTransaction.is_taken_away == True,  # noqa: E712
    )
    return (
        select(FlightCargo)
        .outerjoin(ClientTransaction, taken_away_join)
        .where(
            FlightCargo.flight_name.ilike(OSTATKA_FLIGHT_LIKE),
            ClientTransaction.id.is_(None),
        )
        .subquery()
    )


async def _aggregate_flight_stat(
    session: "AsyncSession",
    flight_name: str,
    usd_to_uzs_rate: float,
) -> OstatkaFlightStat | None:
    """Return aggregate totals for a single ostatka flight or ``None``."""
    sub = _active_cargo_subquery()
    weight_col = sub.c.weight_kg
    price_col = sub.c.price_per_kg
    row = (
        await session.execute(
            select(
                func.count().label("cnt"),
                func.coalesce(func.sum(weight_col), 0).label("weight"),
                func.coalesce(
                    func.sum(weight_col * price_col * usd_to_uzs_rate), 0
                ).label("amount"),
            ).where(func.upper(sub.c.flight_name) == flight_name.upper())
        )
    ).one()

    return OstatkaFlightStat(
        flight_name=flight_name,
        cargo_count=int(row.cnt or 0),
        total_weight_kg=float(row.weight or 0),
        total_amount_uzs=float(row.amount or 0),
    )


async def _aggregate_all_flights(
    session: "AsyncSession",
    usd_to_uzs_rate: float,
) -> list[OstatkaFlightStat]:
    """Return per-flight totals for every A- flight with pending leftovers."""
    sub = _active_cargo_subquery()
    rows = (
        await session.execute(
            select(
                sub.c.flight_name,
                func.count().label("cnt"),
                func.coalesce(func.sum(sub.c.weight_kg), 0).label("weight"),
                func.coalesce(
                    func.sum(sub.c.weight_kg * sub.c.price_per_kg * usd_to_uzs_rate),
                    0,
                ).label("amount"),
            ).group_by(sub.c.flight_name).order_by(sub.c.flight_name)
        )
    ).all()

    return [
        OstatkaFlightStat(
            flight_name=r.flight_name,
            cargo_count=int(r.cnt or 0),
            total_weight_kg=float(r.weight or 0),
            total_amount_uzs=float(r.amount or 0),
        )
        for r in rows
    ]


async def _resolve_usd_rate(session: "AsyncSession") -> float:
    """Return the effective USD→UZS rate (live or custom override)."""
    try:
        from src.bot.utils.currency_converter import currency_converter

        return float(await currency_converter.get_rate_async(session, "USD", "UZS"))
    except Exception:
        await session.rollback()
        logger.warning("Ostatka stats: currency conversion failed, using fallback")
        return _DEFAULT_USD_TO_UZS_RATE


# ---------------------------------------------------------------------------
# Formatting + delivery
# ---------------------------------------------------------------------------


def _format_single_flight(stat: OstatkaFlightStat) -> str:
    """Build the HTML body for a single-flight summary."""
    now = get_current_business_time()
    return (
        f"📊 <b>Ostatka hisoboti</b>\n\n"
        f"✈️ Reys: <b>{html_module.escape(stat.flight_name)}</b>\n"
        f"🗓 Sana: {now.strftime('%Y-%m-%d %H:%M')}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📦 Jami yuk: <b>{stat.cargo_count}</b> dona\n"
        f"⚖️ Jami vazn: <b>{stat.total_weight_kg:.2f}</b> kg\n"
        f"💰 Jami summa: <b>{stat.total_amount_uzs:,.0f}</b> so'm\n"
    )


def _format_daily_digest(stats: list[OstatkaFlightStat]) -> str:
    """Build the HTML body for a multi-flight daily digest."""
    now = get_current_business_time()
    total_cargo = sum(s.cargo_count for s in stats)
    total_weight = sum(s.total_weight_kg for s in stats)
    total_amount = sum(s.total_amount_uzs for s in stats)

    lines = [
        f"📊 <b>Kunlik ostatka hisoboti</b>",
        f"🗓 Sana: {now.strftime('%Y-%m-%d %H:%M')}",
        "━━━━━━━━━━━━━━━",
    ]
    for s in stats:
        lines.append(
            f"✈️ <b>{html_module.escape(s.flight_name)}</b>\n"
            f"   📦 {s.cargo_count} dona  ⚖️ {s.total_weight_kg:.2f} kg  "
            f"💰 {s.total_amount_uzs:,.0f} so'm"
        )
    lines.append("━━━━━━━━━━━━━━━")
    lines.append(
        f"🧾 <b>Umumiy:</b> {total_cargo} dona | {total_weight:.2f} kg | "
        f"{total_amount:,.0f} so'm"
    )
    return "\n".join(lines)


async def _post(bot: "Bot", text: str) -> None:
    """Deliver the message to the ostatka group; swallow non-fatal errors."""
    chat_id = config.telegram.AKB_OSTATKA_GROUP_ID
    try:
        await safe_send_message(bot, chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception:
        logger.exception("Ostatka stats: failed to post to group %s", chat_id)


__all__ = [
    "OstatkaFlightStat",
    "is_daily_ostatka_enabled",
    "send_daily_ostatka_stats",
    "send_ostatka_stats_for_flight",
]
