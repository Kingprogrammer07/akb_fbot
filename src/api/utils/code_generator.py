"""Client-code generator.

The bot is operated by AKB, so every generated code starts with the
partner prefix ``A``.  Two formats are produced depending on the region:

* Toshkent shahar (``region_code == "01"``)
    → ``A{district_subcode:02d}-{seq}``
    seq is scoped per ``(region, district)`` so different districts can
    reuse the same number.  Example: Bektemir's 140th client →
    ``A01-140``, Chilonzor's 3rd → ``A02-3``.

* All other regions (Toshkent viloyati included)
    → ``A{REGION_PREFIX[2]}{seq}``
    Each region has a hand-picked, unique 3-character prefix beginning
    with ``A``.  seq is scoped per region — different districts within
    the region share the same counter.  Example: Buxoro G'ijduvon →
    ``ABU14``, Buxoro Vobkent (next registration) → ``ABU15``.

The legacy free-text values stored in ``clients.region`` /
``clients.district`` (``"toshkent_city"``, ``"uchtepa"`` …) are translated
to numeric codes via :mod:`src.api.utils.constants`.

The generator also fills gaps: if numbers ``1, 2, 4`` are taken it returns
``3`` so the code list stays contiguous over time.
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
PARTNER_PREFIX: str = "A"

# Tashkent shahar is the single region with district codes embedded
# numerically (``A07-{seq}``); other regions use a hand-picked
# 3-character prefix shared by every district inside that region.
_TASHKENT_REGION_CODE: str = "01"

# Per-region 3-char prefixes for the non-Tashkent-shahar codes.  Each
# entry is unique so two regions can never collide on the same prefix.
# When adding a new region, pick a 3-char string starting with ``A``
# that is not already in use.
_REGION_PREFIX: dict[str, str] = {
    "10": "ATV",  # Toshkent viloyati
    "20": "ASR",  # Sirdaryo
    "25": "AJZ",  # Jizzax
    "30": "ASM",  # Samarqand
    "40": "AFR",  # Farg'ona
    "50": "ANM",  # Namangan
    "60": "AAJ",  # Andijon
    "70": "AQD",  # Qashqadaryo
    "75": "ASD",  # Surxondaryo
    "80": "ABX",  # Buxoro
    "85": "ANV",  # Navoiy
    "90": "AXR",  # Xorazm
    "95": "AQR",  # Qoraqalpog'iston
}


# ---------------------------------------------------------------------------
# Pure helpers (no DB)
# ---------------------------------------------------------------------------


def build_code_pattern(
    region_code: str, district_code: str
) -> tuple[str, str, str]:
    """Return ``(prefix, regex, scope_label)`` for the given location.

    * ``prefix`` — string before the sequence number
        Toshkent: ``"A07"``  → final code ``"A07-{seq}"``.
        Others:   ``"ABU"``  → final code ``"ABU{seq}"``.
    * ``regex``  — Postgres regex anchoring the full code at this scope.
    * ``scope_label`` — human-readable description used in error messages.
    """
    if not district_code:
        raise ValueError("district_code is required")

    if region_code == _TASHKENT_REGION_CODE:
        sub = _district_seq(district_code)
        try:
            sub_num = int(sub)
        except ValueError as exc:
            raise ValueError(
                f"Toshkent district subcode must be numeric, got {sub!r}"
            ) from exc
        prefix = f"{PARTNER_PREFIX}{sub_num:02d}"
        regex = f"^{prefix}-[0-9]+$"
        scope = f"region={region_code}, district={district_code}"
        return prefix, regex, scope

    prefix = _REGION_PREFIX.get(region_code)
    if not prefix:
        raise ValueError(
            f"no region prefix configured for region_code={region_code!r}"
        )
    # Region-wide regex: any district under this region shares the prefix
    # so the seq counter is unique inside the whole region.
    regex = f"^{prefix}[0-9]+$"
    scope = f"region={region_code} (district={district_code} ignored for prefix)"
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

    District is required for **every** region.  The numeric district
    code is validated against ``region_code``.
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
    """Generate a fresh, unique ``client_code`` for the given location."""
    region_code, district_code = _normalize_inputs(region, district)
    prefix, regex, _scope = build_code_pattern(region_code, district_code)

    await session.execute(
        text("LOCK TABLE clients IN SHARE ROW EXCLUSIVE MODE")
    )

    is_tashkent = region_code == _TASHKENT_REGION_CODE
    next_num = await _next_seq(session, regex, dash_separator=is_tashkent)
    sep = "-" if is_tashkent else ""
    return f"{prefix}{sep}{next_num}"


async def preview_client_code(
    session: AsyncSession,
    region: str | None,
    district: str | None,
) -> str:
    """Like :func:`generate_client_code` but never takes a row lock."""
    region_code, district_code = _normalize_inputs(region, district)
    prefix, regex, _scope = build_code_pattern(region_code, district_code)
    is_tashkent = region_code == _TASHKENT_REGION_CODE
    next_num = await _next_seq(session, regex, dash_separator=is_tashkent)
    sep = "-" if is_tashkent else ""
    return f"{prefix}{sep}{next_num}"


async def _next_seq(
    session: AsyncSession,
    regex: str,
    dash_separator: bool,
) -> int:
    """Return the smallest free sequence number ``>= 1`` for ``regex``.

    Inspects both ``clients.client_code`` and ``clients.extra_code`` so a
    user with an extra code does not accidentally cause the next primary
    code to collide with their alias.

    ``dash_separator`` toggles which substring grabs the numeric suffix:

    * Tashkent format ``A07-150``    → match ``-([0-9]+)$``.
    * Non-Tashkent     ``AAM120``     → match ``([0-9]+)$``.
    """
    suffix_re = "-([0-9]+)$" if dash_separator else "([0-9]+)$"
    query = text(
        f"""
        WITH target_codes AS (
            SELECT client_code AS code FROM clients WHERE client_code IS NOT NULL
            UNION ALL
            SELECT extra_code  AS code FROM clients WHERE extra_code  IS NOT NULL
        ),
        nums AS (
            SELECT CAST(SUBSTRING(code FROM '{suffix_re}') AS INT) AS num
            FROM target_codes
            WHERE code ~ :regex
        )
        SELECT COALESCE(
            (SELECT n.num + 1
             FROM nums n
             LEFT JOIN nums n2 ON n.num + 1 = n2.num
             WHERE n.num >= 1 AND n2.num IS NULL
             ORDER BY n.num
             LIMIT 1),
            (SELECT CASE WHEN COUNT(*) = 0 THEN 1 ELSE MAX(num) + 1 END FROM nums)
        )
        """
    )
    result = await session.execute(query, {"regex": regex})
    n = result.scalar_one_or_none()
    return int(n) if n is not None else 1
