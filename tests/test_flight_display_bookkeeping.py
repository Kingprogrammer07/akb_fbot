"""Bookkeeping transaction rows are never minted as flight aliases.

``client_transaction_data.reys`` also stores balance bookkeeping rows: the
``UZPOST*``, ``WALLET_ADJ:*`` and ``SYS_ADJ:*`` rows that
``apply_public_transaction_filter`` hides from users, and the ``BONUS:*`` and
``PENALTY:*`` rows users do see.  None is a flight, so minting a mask for one
would burn a counter number for good and let a typed mask resolve to a
bookkeeping row.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_flight_alias import PartnerFlightAlias
from src.infrastructure.services.flight_display import FlightDisplay


async def _akb(session: AsyncSession) -> Partner:
    partner = Partner(code="AKB", display_name="AKB", prefix="A", is_dm_partner=True)
    session.add(partner)
    await session.commit()
    return partner


async def _alias_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(PartnerFlightAlias))


@pytest.mark.parametrize(
    "reys",
    [
        "UZPOST",
        "UZPOST-2026-01",
        "WALLET_ADJ:refund",
        "SYS_ADJ:correction",
        "BONUS:referral",
        "PENALTY:late pickup",
    ],
)
async def test_bookkeeping_rows_are_never_minted(
    db_session: AsyncSession, reys: str
) -> None:
    partner = await _akb(db_session)

    display = FlightDisplay(partner, mint_missing=True)

    assert await display.mask(db_session, reys) is None
    assert await _alias_count(db_session) == 0


async def test_a_real_flight_is_still_minted(db_session: AsyncSession) -> None:
    partner = await _akb(db_session)

    display = FlightDisplay(partner, mint_missing=True)

    assert await display.mask(db_session, "M200") == "AKB1"
    assert await _alias_count(db_session) == 1
