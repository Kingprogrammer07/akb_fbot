"""Client-code generator.

The bot is operated by AKB, so every generated code starts with the
partner prefix ``AKB``.  Format is unified across every region:

    AKB{region_code}-{district_subcode}/{seq}

District is **always** part of the rendered code so ``client_code`` lines
read identically for every region.  The sequence-numbering *scope*,
however, varies:

* Toshkent shahar (``region_code == "01"``)
    seq is scoped per ``(region, district)`` — Bektemir 1, Chilonzor 1
    and so on are all valid simultaneously.

* All other regions
    seq is scoped per region — Buxoro can have at most one ``/1`` even
    though several districts appear in its codes (Buxoro shahri, Vobkent,
    G'ijduvon …).

The legacy free-text values stored in ``clients.region`` /
``clients.district`` (``"toshkent_city"``, ``"uchtepa"`` …) are translated
to numeric codes via :mod:`src.api.utils.constants`.

The generator also fills gaps: if numbers ``1, 2, 4`` are taken it returns
``3``.  This matches the previous behaviour and keeps the code list
contiguous over time.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.utils.constants import (
    DISTRICTS,
    REGIONS,
    resolve_district_code,
    resolve_region_code,
)

# AKB is the only partner that registers clients via this bot.
PARTNER_PREFIX: str = "AKB"

# Tashkent shahar is the single region with per-district sequence scoping.
_TASHKENT_REGION_CODE: str = "01"


# ---------------------------------------------------------------------------
# Pure helpers (no DB)
# ---------------------------------------------------------------------------

def build_code_pattern(
    region_code: str, district_code: str
) -> tuple[str, str, str]:
    """Return ``(prefix, regex, scope_label)`` for the given location.

    * ``prefix`` — string before the ``/`` (e.g. ``"AKB01-9"`` or ``"AKB80-12"``).
    * ``regex``  — Postgres regex anchoring the full code at this scope.
    * ``scope_label`` — human-readable description used in error messages.

    For Toshkent the regex matches a single ``(region, district)`` so seq
    numbers reset per district.  For other regions the regex matches the
    full region (any district), so seq numbers stay unique inside the
    region.
    """
    if not district_code:
        raise ValueError("district_code is required")

    sub = _district_seq(district_code)
    if region_code == _TASHKENT_REGION_CODE:
        prefix = f"{PARTNER_PREFIX}{region_code}-{sub}"
        regex = f"^{prefix}/[0-9]+$"
        scope = f"region={region_code}, district={district_code}"
    else:
        prefix = f"{PARTNER_PREFIX}{region_code}-{sub}"
        # Region-wide scope: any district under this region counts for seq.
        regex = f"^{PARTNER_PREFIX}{region_code}-[0-9]+/[0-9]+$"
        scope = f"region={region_code}"
    return prefix, regex, scope


def _district_seq(district_code: str) -> str:
    """Extract the within-region sequence component of a district code.

    ``"01-9"`` → ``"9"``.  When already a bare sequence, returns it as-is.
    """
    if "-" in district_code:
        return district_code.split("-", 1)[1]
    return district_code


def _normalize_inputs(
    region: str | None, district: str | None
) -> tuple[str, str]:
    """Translate any caller-supplied region/district representation to codes.

    District is required for **every** region so the rendered code shape
    stays identical across the country.  The numeric ``district_code`` is
    validated to belong to the resolved ``region_code``.
    """
    region_code = resolve_region_code(region)
    if not region_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown region {region!r}",
        )

    district_code = resolve_district_code(district)
    if not district_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown district {district!r} for region {region_code}",
        )

    info = DISTRICTS.get(district_code)
    if not info or info["region_code"] != region_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"District {district!r} ({district_code}) does not belong "
                f"to region {region_code} ({REGIONS.get(region_code, region_code)})"
            ),
        )
    return region_code, district_code


# ---------------------------------------------------------------------------
# DB-bound generator
# ---------------------------------------------------------------------------

async def generate_client_code(
    session: AsyncSession,
    region: str | None,
    district: str | None,
) -> str:
    """Generate a fresh, unique ``client_code`` for the given location.

    Acquires ``SHARE ROW EXCLUSIVE`` on ``clients`` to serialise concurrent
    code generation; the lock is released on commit/rollback by the caller.
    """
    region_code, district_code = _normalize_inputs(region, district)
    prefix, regex, _scope = build_code_pattern(region_code, district_code)

    await session.execute(
        text("LOCK TABLE clients IN SHARE ROW EXCLUSIVE MODE")
    )

    next_num = await _next_seq(session, regex)
    return f"{prefix}/{next_num}"


async def preview_client_code(
    session: AsyncSession,
    region: str | None,
    district: str | None,
) -> str:
    """Like :func:`generate_client_code` but never takes a row lock.

    Used by the ``/preview-code`` endpoint so admins can see the next code
    live without blocking real registrations.  The returned value is
    advisory: a concurrent registration could consume it before the admin
    acts.  This matches the prior endpoint's behaviour.
    """
    region_code, district_code = _normalize_inputs(region, district)
    prefix, regex, _scope = build_code_pattern(region_code, district_code)
    next_num = await _next_seq(session, regex)
    return f"{prefix}/{next_num}"


async def _next_seq(session: AsyncSession, regex: str) -> int:
    """Return the smallest free sequence number ``>= 1`` for ``regex``.

    Inspects both ``clients.client_code`` and ``clients.extra_code`` so a
    user with an extra code does not accidentally cause the next primary
    code to collide with their alias.
    """
    query = text(
        """
        WITH target_codes AS (
            SELECT client_code AS code FROM clients WHERE client_code IS NOT NULL
            UNION ALL
            SELECT extra_code  AS code FROM clients WHERE extra_code  IS NOT NULL
        ),
        nums AS (
            SELECT CAST(SUBSTRING(code FROM '/([0-9]+)$') AS INT) AS num
            FROM target_codes
            WHERE code ~ :regex
        )
        SELECT COALESCE(
            -- 1. Smallest gap >= 1
            (SELECT n.num + 1
             FROM nums n
             LEFT JOIN nums n2 ON n.num + 1 = n2.num
             WHERE n.num >= 1 AND n2.num IS NULL
             ORDER BY n.num
             LIMIT 1),
            -- 2. Empty set or no gap → 1 / max+1
            (SELECT CASE WHEN COUNT(*) = 0 THEN 1 ELSE MAX(num) + 1 END FROM nums)
        )
        """
    )
    result = await session.execute(query, {"regex": regex})
    n = result.scalar_one_or_none()
    return int(n) if n is not None else 1
