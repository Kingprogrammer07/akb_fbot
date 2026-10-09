"""
``FlightDisplay`` mint mode.

Flights read from a client's own records may have no partner alias yet.  With
``mint_missing=True`` the renderer creates that alias instead of rendering a
placeholder, in a transaction of its own: rendering must never commit or roll
back the caller's session.  The default mode keeps never writing.

The concurrency tests hold an uncommitted alias open in one session so the mint
deterministically blocks on the unique index, then release it.
"""

import asyncio
import logging

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_flight_alias import PartnerFlightAlias
from src.infrastructure.services.flight_display import (
    FLIGHT_PLACEHOLDER,
    FlightDisplay,
    flight_label_for_client,
    flight_mask_for_client,
)
from src.infrastructure.services.flight_mask import FlightMaskService

AKB_CLIENT = "A01-1/1"


@pytest_asyncio.fixture
async def partners(db_session: AsyncSession) -> dict[str, Partner]:
    akb = Partner(code="AKB", display_name="AKB Cargo", prefix="A", is_dm_partner=True)
    triton = Partner(
        code="SYT", display_name="Triton", prefix="SYT", group_chat_id=-1001
    )
    db_session.add_all([akb, triton])
    await db_session.commit()
    return {"AKB": akb, "SYT": triton}


async def _aliases(engine: AsyncEngine) -> list[tuple[str, str]]:
    """Committed ``(real, mask)`` pairs in creation order."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(
                PartnerFlightAlias.real_flight_name,
                PartnerFlightAlias.mask_flight_name,
            ).order_by(PartnerFlightAlias.id)
        )
        return [(real, mask) for real, mask in rows]


async def _committed_flight_cargos(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        return await conn.scalar(select(func.count()).select_from(FlightCargo))


def _minted(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if "minted alias" in record.getMessage()
    ]


async def _wait_until_blocked(
    engine: AsyncEngine, task: asyncio.Task[str | None]
) -> None:
    """Return once ``task`` waits on a lock held by an uncommitted transaction."""
    async with engine.connect() as conn:
        for _ in range(200):
            if task.done():
                pytest.fail(f"the mint finished without blocking: {task.result()!r}")
            waiting = await conn.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
            # pg_stat_activity is a per-transaction snapshot.
            await conn.rollback()
            if waiting:
                return
            await asyncio.sleep(0.05)
    pytest.fail("the mint never blocked on the uncommitted alias")


# ---------------------------------------------------------------------------
# Default mode
# ---------------------------------------------------------------------------


async def test_default_mode_never_writes(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    display = await FlightDisplay.for_client(db_session, AKB_CLIENT)

    assert await display.mask(db_session, "M200") is None
    assert await display.label(db_session, "M200") == FLIGHT_PLACEHOLDER
    assert await display.label(db_session, "M300", ordinal=2) == "Reys #2"
    assert await flight_mask_for_client(db_session, AKB_CLIENT, "M200") is None
    assert (
        await flight_label_for_client(db_session, AKB_CLIENT, "M200")
        == FLIGHT_PLACEHOLDER
    )
    assert await _aliases(db_engine) == []


# ---------------------------------------------------------------------------
# Mint mode
# ---------------------------------------------------------------------------


async def test_mint_creates_missing_aliases_continuing_the_counter(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    partners: dict[str, Partner],
    caplog: pytest.LogCaptureFixture,
) -> None:
    akb_id = partners["AKB"].id
    db_session.add_all(
        [
            PartnerFlightAlias(
                partner_id=akb_id, real_flight_name="M100", mask_flight_name="AKB7"
            ),
            PartnerFlightAlias(
                partner_id=akb_id, real_flight_name="M101", mask_flight_name="AKB-150"
            ),
        ]
    )
    await db_session.commit()
    caplog.set_level(logging.INFO)

    display = await FlightDisplay.for_client(
        db_session, ["X1", AKB_CLIENT], mint_missing=True
    )

    assert await display.mask(db_session, "M100") == "AKB7"
    assert await display.mask(db_session, "M200") == "AKB8"
    assert await display.label(db_session, "M300", ordinal=2) == "AKB9"
    assert await display.mask(db_session, "M200") == "AKB8"
    assert await _aliases(db_engine) == [
        ("M100", "AKB7"),
        ("M101", "AKB-150"),
        ("M200", "AKB8"),
        ("M300", "AKB9"),
    ]
    # One line per created alias, naming the mask and never the real flight.
    assert _minted(caplog) == [
        "flight_display: minted alias AKB8 for partner AKB",
        "flight_display: minted alias AKB9 for partner AKB",
    ]


async def test_mint_stores_the_name_exactly_as_given(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    display = FlightDisplay(partners["AKB"], mint_missing=True)

    assert await display.mask(db_session, "M200 ") == "AKB1"
    assert await _aliases(db_engine) == [("M200 ", "AKB1")]


async def test_mint_skips_names_that_cannot_carry_an_alias(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    display = FlightDisplay(partners["AKB"], mint_missing=True)

    assert await display.mask(db_session, "   ") is None
    assert await display.label(db_session, "M" * 101) == FLIGHT_PLACEHOLDER
    assert await _aliases(db_engine) == []


async def test_client_without_partner_keeps_the_placeholder(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    display = await FlightDisplay.for_client(db_session, "X99", mint_missing=True)

    assert await display.mask(db_session, "M200") is None
    assert await display.label(db_session, "M200") == FLIGHT_PLACEHOLDER
    assert await display.label(db_session, "M300", ordinal=2) == "Reys #2"
    assert (
        await flight_label_for_client(db_session, "X99", "M200", mint_missing=True)
        == FLIGHT_PLACEHOLDER
    )
    assert await _aliases(db_engine) == []


async def test_one_off_helpers_mint_for_the_clients_partner(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    assert (
        await flight_mask_for_client(db_session, "SYT5", "T1", mint_missing=True)
        == "SYT1"
    )
    assert (
        await flight_label_for_client(db_session, ["a01-1/1"], "T1", mint_missing=True)
        == "AKB1"
    )
    assert await _aliases(db_engine) == [("T1", "SYT1"), ("T1", "AKB1")]


# ---------------------------------------------------------------------------
# Transaction independence
# ---------------------------------------------------------------------------


async def test_mint_neither_commits_nor_rolls_back_the_callers_session(
    db_engine: AsyncEngine, db_session: AsyncSession, partners: dict[str, Partner]
) -> None:
    db_session.add(
        FlightCargo(flight_name="M200", client_id=AKB_CLIENT, photo_file_ids="[]")
    )
    await db_session.flush()

    display = FlightDisplay(partners["AKB"], mint_missing=True)
    assert await display.mask(db_session, "M200") == "AKB1"

    # The alias is committed on its own ...
    assert await _aliases(db_engine) == [("M200", "AKB1")]
    # ... while the caller's flushed row is still pending in its transaction.
    assert db_session.in_transaction()
    assert await db_session.scalar(select(func.count()).select_from(FlightCargo)) == 1
    assert await _committed_flight_cargos(db_engine) == 0

    await db_session.rollback()
    assert await _committed_flight_cargos(db_engine) == 0
    assert await _aliases(db_engine) == [("M200", "AKB1")]


async def test_mint_from_a_connection_bound_session_uses_its_engine(
    db_engine: AsyncEngine, partners: dict[str, Partner]
) -> None:
    async with db_engine.connect() as conn:
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            display = FlightDisplay(partners["AKB"], mint_missing=True)
            assert await display.mask(session, "M200") == "AKB1"
        await conn.rollback()

    assert await _aliases(db_engine) == [("M200", "AKB1")]


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


async def test_concurrent_mints_of_one_flight_create_one_alias(
    db_engine: AsyncEngine,
    partners: dict[str, Partner],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with maker() as first, maker() as second:
        results = await asyncio.gather(
            FlightDisplay(partners["AKB"], mint_missing=True).mask(first, "M200"),
            FlightDisplay(partners["AKB"], mint_missing=True).mask(second, "M200"),
        )

    assert results == ["AKB1", "AKB1"]
    assert await _aliases(db_engine) == [("M200", "AKB1")]
    assert _minted(caplog) == ["flight_display: minted alias AKB1 for partner AKB"]


async def test_a_mint_that_loses_the_race_returns_the_winners_alias(
    db_engine: AsyncEngine,
    partners: dict[str, Partner],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    akb = partners["AKB"]
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with maker() as winner, maker() as caller:
        winner.add(
            PartnerFlightAlias(
                partner_id=akb.id, real_flight_name="M200", mask_flight_name="AKB1"
            )
        )
        await winner.flush()
        mint = asyncio.create_task(
            FlightDisplay(akb, mint_missing=True).mask(caller, "M200")
        )
        await _wait_until_blocked(db_engine, mint)
        await winner.commit()

        assert await mint == "AKB1"

    assert await _aliases(db_engine) == [("M200", "AKB1")]
    assert _minted(caplog) == []


async def test_a_mint_whose_mask_was_taken_concurrently_retries(
    db_engine: AsyncEngine,
    partners: dict[str, Partner],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    akb = partners["AKB"]
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with maker() as other, maker() as caller:
        other.add(
            PartnerFlightAlias(
                partner_id=akb.id, real_flight_name="M100", mask_flight_name="AKB1"
            )
        )
        await other.flush()
        mint = asyncio.create_task(
            FlightDisplay(akb, mint_missing=True).mask(caller, "M200")
        )
        await _wait_until_blocked(db_engine, mint)
        await other.commit()

        assert await mint == "AKB2"

    assert await _aliases(db_engine) == [("M100", "AKB1"), ("M200", "AKB2")]
    assert _minted(caplog) == ["flight_display: minted alias AKB2 for partner AKB"]


async def test_a_mint_that_keeps_colliding_gives_up_after_three_attempts(
    db_session: AsyncSession,
    partners: dict[str, Partner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    async def always_collide(
        session: AsyncSession, partner_id: int, partner_code: str, real_flight_name: str
    ) -> PartnerFlightAlias:
        attempts.append(real_flight_name)
        raise IntegrityError(
            "INSERT INTO partner_flight_aliases", {}, Exception("uq_pfa_partner_mask")
        )

    monkeypatch.setattr(FlightMaskService, "ensure_mask", staticmethod(always_collide))
    display = FlightDisplay(partners["AKB"], mint_missing=True)

    with pytest.raises(IntegrityError):
        await display.mask(db_session, "M200")
    assert attempts == ["M200", "M200", "M200"]
