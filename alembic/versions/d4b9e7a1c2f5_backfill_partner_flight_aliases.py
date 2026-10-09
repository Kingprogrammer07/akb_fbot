"""partner: backfill flight aliases for every flight partners' clients already have

Revision ID: d4b9e7a1c2f5
Revises: c3f8a2d6e1b4
Create Date: 2026-09-11 00:00:00.000000

Every flight a client sees must render as a partner mask.  The application
mints a missing alias when it shows a client flights read from that client's
own records (``FlightDisplay(mint_missing=True)``); this revision creates the
aliases once for the data that already exists.

For every active partner it collects each distinct real flight name used by
that partner's clients in

* ``flight_cargos`` (``client_id``, ``flight_name``),
* ``cargo_items`` (``client_id``, ``flight_name``),
* ``client_transaction_data`` (``client_code``, ``reys``; the balance
  bookkeeping rows ``UZPOST*``, ``WALLET_ADJ:*``, ``SYS_ADJ:*``, ``BONUS:*``
  and ``PENALTY:*`` name no flight and are excluded, as listed by
  ``NON_FLIGHT_REYS_PREFIXES`` in the ``ClientTransaction`` model),
* ``expected_flight_cargos`` (``client_code``, ``flight_name``; placeholder
  rows excluded).

A client code belongs to a partner exactly as ``PartnerResolver`` decides:
``code.strip().upper()`` matched by longest prefix over the active partners'
primary prefixes and their ``partner_prefix_aliases``, where an alias that
duplicates an already registered prefix is ignored, so a primary prefix wins
an exact clash.  Codes matching no active partner are skipped.

Flights the partner already has an alias for (exact ``real_flight_name``) are
left alone, as are blank names and names longer than the alias column.  The
rest get masks in order of first appearance — the earliest ``created_at``
across the four tables, then the real name — continuing the partner's counter
exactly like ``FlightMaskService._next_auto_mask``: ``{CODE}{N}`` with
``CODE = partners.code.upper()`` and ``N`` one above the highest numeric
suffix among the partner's masks matching ``^CODE\\d+$`` (case-sensitive, so
custom masks such as ``AKB-150`` do not move the counter).  Running the
upgrade again inserts nothing.

Every inserted row carries the sentinel timestamp ``2026-09-11 00:00:00+00``
as both ``created_at`` and ``updated_at``.  ``downgrade()`` deletes exactly
the aliases whose ``created_at`` and ``updated_at`` both still equal it: the
rows this revision created that nobody has edited since (an edit through the
ORM, e.g. ``FlightMaskService.set_mask``, moves ``updated_at``).  Aliases the
application minted, before or after the upgrade, carry real timestamps and
survive the downgrade.
"""

import logging
import re
from datetime import datetime, timezone
from typing import NamedTuple, Sequence, Union

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d4b9e7a1c2f5"
down_revision: Union[str, None] = "c3f8a2d6e1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


logger = logging.getLogger("alembic.runtime.migration")

BACKFILL_TIMESTAMP = datetime(2026, 9, 11, tzinfo=timezone.utc)
"""``created_at`` and ``updated_at`` of every alias this revision inserts."""

_REAL_FLIGHT_NAME_MAX_LENGTH = 100
"""``partner_flight_aliases.real_flight_name`` is ``VARCHAR(100)``."""

# ``FlightMaskService._AUTO_SUFFIX_RE``.
_AUTO_SUFFIX_RE = re.compile(r"^(?P<digits>\d+)$")

# Each query yields (client code, real flight name, earliest created_at).
_FLIGHT_SOURCES: tuple[str, ...] = (
    "SELECT client_id, flight_name, min(created_at) FROM flight_cargos "
    "WHERE client_id IS NOT NULL AND flight_name IS NOT NULL "
    "GROUP BY client_id, flight_name",
    "SELECT client_id, flight_name, min(created_at) FROM cargo_items "
    "WHERE client_id IS NOT NULL AND flight_name IS NOT NULL "
    "GROUP BY client_id, flight_name",
    "SELECT client_code, reys, min(created_at) FROM client_transaction_data "
    "WHERE client_code IS NOT NULL AND reys IS NOT NULL "
    "AND reys NOT LIKE 'UZPOST%' AND reys NOT LIKE 'WALLET_ADJ:%' "
    "AND reys NOT LIKE 'SYS_ADJ:%' AND reys NOT LIKE 'BONUS:%' "
    "AND reys NOT LIKE 'PENALTY:%' "
    "GROUP BY client_code, reys",
    "SELECT client_code, flight_name, min(created_at) FROM expected_flight_cargos "
    "WHERE is_placeholder IS FALSE "
    "AND client_code IS NOT NULL AND flight_name IS NOT NULL "
    "GROUP BY client_code, flight_name",
)


class _Partner(NamedTuple):
    id: int
    code: str


def _load_partners(
    conn: Connection,
) -> tuple[list[_Partner], list[tuple[str, int]]]:
    """Active partners and ``(prefix, partner_id)`` pairs, longest prefix first.

    Mirrors ``PartnerResolver._load``: primary prefixes first, then prefix
    aliases of active partners in prefix order, skipping any alias whose
    prefix is already registered.
    """
    rows = conn.execute(
        sa.text(
            "SELECT id, code, prefix FROM partners "
            "WHERE is_active IS TRUE ORDER BY code ASC"
        )
    ).all()
    partners = [_Partner(id=row.id, code=row.code) for row in rows]
    by_prefix: dict[str, int] = {row.prefix.upper(): row.id for row in rows}
    codes = {partner.id: partner.code for partner in partners}

    aliases = conn.execute(
        sa.text(
            "SELECT a.partner_id, a.prefix FROM partner_prefix_aliases a "
            "JOIN partners p ON p.id = a.partner_id "
            "WHERE p.is_active IS TRUE ORDER BY a.prefix ASC"
        )
    ).all()
    for alias in aliases:
        prefix = alias.prefix.upper()
        if prefix in by_prefix:
            logger.warning(
                "backfill flight aliases: prefix alias %r of partner %s ignored "
                "— already owned by partner %s",
                prefix,
                codes[alias.partner_id],
                codes[by_prefix[prefix]],
            )
            continue
        by_prefix[prefix] = alias.partner_id

    prefixes = sorted(by_prefix.items(), key=lambda item: len(item[0]), reverse=True)
    return partners, prefixes


def _owner_of(client_code: str, prefixes: list[tuple[str, int]]) -> int | None:
    """``PartnerResolver._match_lpm`` over a normalised client code."""
    normalised = client_code.strip().upper()
    if not normalised:
        return None
    for prefix, partner_id in prefixes:
        if normalised.startswith(prefix):
            return partner_id
    return None


def _first_appearances(
    conn: Connection, prefixes: list[tuple[str, int]]
) -> dict[int, dict[str, datetime]]:
    """``partner_id -> {real flight name: earliest created_at}``.

    ``created_at`` is NOT NULL in every source table, so every flight has one.
    """
    seen: dict[int, dict[str, datetime]] = {}
    for query in _FLIGHT_SOURCES:
        for client_code, real_name, first_seen in conn.execute(sa.text(query)):
            if not real_name.strip():
                continue
            partner_id = _owner_of(client_code, prefixes)
            if partner_id is None:
                continue
            flights = seen.setdefault(partner_id, {})
            if real_name not in flights or first_seen < flights[real_name]:
                flights[real_name] = first_seen
    return seen


def _appearance_order(item: tuple[str, datetime]) -> tuple[datetime, str]:
    real_name, first_seen = item
    return (first_seen, real_name)


def _next_suffix(conn: Connection, partner_id: int, prefix: str) -> int:
    """``FlightMaskService._next_auto_mask`` without the prefix."""
    masks = conn.execute(
        sa.text(
            "SELECT mask_flight_name FROM partner_flight_aliases "
            "WHERE partner_id = :partner_id AND mask_flight_name ~ :pattern"
        ),
        {"partner_id": partner_id, "pattern": rf"^{prefix}\d+$"},
    ).scalars()
    max_n = 0
    for mask in masks:
        match = _AUTO_SUFFIX_RE.match(mask[len(prefix) :])
        if match:
            max_n = max(max_n, int(match.group("digits")))
    return max_n + 1


def backfill_aliases(conn: Connection) -> dict[str, int]:
    """Create the missing aliases; return the number inserted per partner code."""
    partners, prefixes = _load_partners(conn)
    flights_by_partner = _first_appearances(conn, prefixes)

    inserted: dict[str, int] = {}
    for partner in partners:
        flights = flights_by_partner.get(partner.id, {})
        aliased = set(
            conn.execute(
                sa.text(
                    "SELECT real_flight_name FROM partner_flight_aliases "
                    "WHERE partner_id = :partner_id"
                ),
                {"partner_id": partner.id},
            ).scalars()
        )
        missing = [item for item in flights.items() if item[0] not in aliased]
        storable = [
            item for item in missing if len(item[0]) <= _REAL_FLIGHT_NAME_MAX_LENGTH
        ]
        if len(storable) < len(missing):
            logger.warning(
                "backfill flight aliases: partner %s — %d flight name(s) longer "
                "than %d characters skipped",
                partner.code,
                len(missing) - len(storable),
                _REAL_FLIGHT_NAME_MAX_LENGTH,
            )

        prefix = partner.code.upper()
        first_n = _next_suffix(conn, partner.id, prefix)
        rows = [
            {
                "partner_id": partner.id,
                "real_flight_name": real_name,
                "mask_flight_name": f"{prefix}{first_n + offset}",
                "stamp": BACKFILL_TIMESTAMP,
            }
            for offset, (real_name, _first_seen) in enumerate(
                sorted(storable, key=_appearance_order)
            )
        ]
        if rows:
            conn.execute(
                sa.text(
                    "INSERT INTO partner_flight_aliases "
                    "(partner_id, real_flight_name, mask_flight_name, "
                    "created_at, updated_at) "
                    "VALUES (:partner_id, :real_flight_name, :mask_flight_name, "
                    ":stamp, :stamp)"
                ),
                rows,
            )
        logger.info(
            "backfill flight aliases: partner %s — %d alias(es) created, "
            "%d flight(s) already aliased",
            partner.code,
            len(rows),
            len(flights) - len(missing),
        )
        inserted[partner.code] = len(rows)
    return inserted


def remove_backfilled_aliases(conn: Connection) -> int:
    """Delete the aliases this revision inserted and nobody edited since."""
    result = conn.execute(
        sa.text(
            "DELETE FROM partner_flight_aliases "
            "WHERE created_at = :stamp AND updated_at = :stamp"
        ),
        {"stamp": BACKFILL_TIMESTAMP},
    )
    logger.info("backfill flight aliases: %d alias(es) removed", result.rowcount)
    return result.rowcount


def upgrade() -> None:
    """Create a mask for every flight partners' clients already have."""
    backfill_aliases(op.get_bind())


def downgrade() -> None:
    """Remove the unedited aliases created by :func:`upgrade`."""
    remove_backfilled_aliases(op.get_bind())
