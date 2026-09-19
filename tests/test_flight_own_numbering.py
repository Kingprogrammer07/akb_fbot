"""A flight already named in a partner's own numbering is never renumbered.

The China import names each worksheet after the number the client is told, so
``cargo_items.flight_name`` holds names that already are AKB's client-facing
identifiers (``AKB285``).  Masking them a second time renumbered every flight
AKB's clients see - in production ``AKB285`` reached them as ``AKB359`` - and
bound masks to the wrong flight, so a cashier typing ``AKB283`` landed on real
flight ``AKB209``.

A real name matching the partner's own ``CODE<digits>`` form is therefore shown
as it is, no alias is minted for it, and a stale alias for it is ignored.  Other
partners keep getting their own mask for that same flight: the name is AKB's,
not theirs.
"""

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.bot.handlers.admin._partner_alias_review import build_review
from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_flight_alias import PartnerFlightAlias
from src.infrastructure.services.flight_display import FlightDisplay
from src.infrastructure.services.flight_mask import FlightMaskService

AKB_CLIENT = "A01-1/1"
TRITON_CLIENT = "SYT10"
OWN_NAME = "AKB285"
"""A real flight name exactly as the China import writes it."""


@pytest_asyncio.fixture
async def partners(db_session: AsyncSession) -> dict[str, Partner]:
    akb = Partner(code="AKB", display_name="AKB Cargo", prefix="A", is_dm_partner=True)
    triton = Partner(
        code="SYT", display_name="Triton", prefix="SYT", group_chat_id=-1001
    )
    db_session.add_all([akb, triton])
    await db_session.commit()
    return {"AKB": akb, "SYT": triton}


async def _alias_count(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        return await conn.scalar(select(func.count()).select_from(PartnerFlightAlias))


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("partner_code", "real_flight_name", "expected"),
    [
        ("AKB", "AKB285", True),
        ("AKB", "akb285", True),
        ("AKB", " AKB285 ", True),
        ("SYT", "SYT12", True),
        # Not this partner's numbering.
        ("AKB", "M280", False),
        ("SYT", "AKB285", False),
        # Not a number behind the code.
        ("AKB", "AKB", False),
        ("AKB", "AKB-285", False),
        ("AKB", "AKB285-AKB286", False),
        ("AKB", "AKB285A", False),
        ("", "AKB285", False),
        ("AKB", "", False),
    ],
)
def test_is_own_mask_name(
    partner_code: str, real_flight_name: str, expected: bool
) -> None:
    assert (
        FlightMaskService.is_own_mask_name(partner_code, real_flight_name) is expected
    )


# ---------------------------------------------------------------------------
# What the client sees
# ---------------------------------------------------------------------------


async def test_own_numbering_reaches_the_client_unchanged(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    display = await FlightDisplay.for_client(db_session, AKB_CLIENT, mint_missing=True)

    assert await display.mask(db_session, OWN_NAME) == OWN_NAME
    assert await display.label(db_session, OWN_NAME) == OWN_NAME
    assert await _alias_count(db_engine) == 0


async def test_own_numbering_does_not_consume_a_mask_number(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    """Rendering ``AKB285`` must not push the next real flight to ``AKB286``."""
    display = await FlightDisplay.for_client(db_session, AKB_CLIENT, mint_missing=True)
    await display.mask(db_session, OWN_NAME)

    assert await display.mask(db_session, "M280") == "AKB1"
    assert await _alias_count(db_engine) == 1


async def test_stale_alias_for_own_numbering_is_ignored(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    """The rows the backfill left behind must not reach a client again."""
    db_session.add(
        PartnerFlightAlias(
            partner_id=partners["AKB"].id,
            real_flight_name=OWN_NAME,
            mask_flight_name="AKB359",
        )
    )
    await db_session.commit()

    display = await FlightDisplay.for_client(db_session, AKB_CLIENT, mint_missing=True)

    assert await display.mask(db_session, OWN_NAME) == OWN_NAME


async def test_another_partner_still_gets_its_own_mask(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    """``AKB285`` is AKB's number; a Triton client must not be shown it."""
    display = await FlightDisplay.for_client(
        db_session, TRITON_CLIENT, mint_missing=True
    )

    assert await display.mask(db_session, OWN_NAME) == "SYT1"
    assert await _alias_count(db_engine) == 1


async def test_names_outside_the_partner_numbering_still_get_a_mask(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    display = await FlightDisplay.for_client(db_session, AKB_CLIENT, mint_missing=True)

    assert await display.mask(db_session, "M280") == "AKB1"
    assert await _alias_count(db_engine) == 1


# ---------------------------------------------------------------------------
# The admin paths that mint on their own (flight notify, bulk send review)
# ---------------------------------------------------------------------------


async def test_display_flight_name_keeps_own_numbering(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    name = await FlightMaskService.display_flight_name(
        db_session, partners["AKB"], OWN_NAME
    )
    await db_session.commit()

    assert name == OWN_NAME
    assert await _alias_count(db_engine) == 0


async def test_display_flight_name_masks_everything_else(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    name = await FlightMaskService.display_flight_name(
        db_session, partners["SYT"], OWN_NAME
    )
    await db_session.commit()

    assert name == "SYT1"
    assert await _alias_count(db_engine) == 1


async def test_review_shows_own_numbering_without_minting(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    review = await build_review(db_session, OWN_NAME, [AKB_CLIENT, TRITON_CLIENT])
    await db_session.commit()

    masks = {
        segment.partner.code: segment.mask_flight_name for segment in review.segments
    }
    assert masks == {"AKB": OWN_NAME, "SYT": "SYT1"}
    assert await _alias_count(db_engine) == 1
