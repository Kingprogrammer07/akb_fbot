"""
Backfill revision ``d4b9e7a1c2f5``: a mask for every flight that partners'
clients already have.

The seed data covers the routing rules of ``PartnerResolver`` (longest prefix,
prefix aliases, a primary prefix winning an exact clash, inactive partners and
unknown codes ignored), flights spread over the four source tables with
different ``created_at`` values, a tie broken by name, and existing masks that
must or must not move the counter (``AKB-150`` and the lower-case ``akb9`` do
not).
"""

import importlib.util
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.infrastructure.database.models.cargo_item import CargoItem
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.expected_cargo import ExpectedFlightCargo
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_flight_alias import PartnerFlightAlias
from src.infrastructure.database.models.partner_prefix_alias import PartnerPrefixAlias

ROOT = Path(__file__).resolve().parent.parent
REVISION = "d4b9e7a1c2f5"
REVISION_FILE = (
    ROOT / "alembic" / "versions" / f"{REVISION}_backfill_partner_flight_aliases.py"
)

# (partner code, real flight name, mask) — created by the application.
PRE_EXISTING: list[tuple[str, str, str]] = [
    ("AKB", "M100", "AKB3"),
    ("AKB", "M101", "AKB-150"),
    ("AKB", "M102", "akb9"),
    ("GGX", "M900", "GGX2"),
]

# What the backfill must add, in creation order.
BACKFILLED: list[tuple[str, str, str]] = [
    ("AKB", "M400", "AKB4"),  # 2025-11-01
    ("AKB", "M200", "AKB5"),  # 2025-12-20, earliest of three tables
    ("AKB", "M300", "AKB6"),  # 2026-01-01
    ("AKB", "M150", "AKB7"),  # 2026-01-03, via ``AZ1``
    ("AKB", "M305", "AKB8"),  # 2026-01-04, tie broken by name
    ("AKB", "M310", "AKB9"),  # 2026-01-04
    ("GGX", "M200", "GGX3"),
    ("SYT", "T0", "SYT1"),  # 2026-01-20 in flight_cargos, 2026-03-01 expected
    ("SYT", "T1", "SYT2"),  # 2026-02-01
    ("XON", "M500", "XON1"),
]


def _at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _transaction(
    client_code: str, reys: str, created_at: datetime
) -> ClientTransaction:
    return ClientTransaction(
        telegram_id=1,
        client_code=client_code,
        qator_raqami=1,
        reys=reys,
        summa=0,
        vazn="1",
        created_at=created_at,
    )


def _snapshot_of(
    rows: list[tuple[str, str, str]], *, backfilled: bool
) -> list[tuple[str, str, str, bool]]:
    return [(code, real, mask, backfilled) for code, real, mask in rows]


def _through_alembic(operation: Callable[[], None]) -> Callable[[Connection], None]:
    """Run a revision's ``upgrade`` / ``downgrade`` with ``op`` bound to ``conn``."""

    def run(conn: Connection) -> None:
        with Operations.context(MigrationContext.configure(conn)):
            operation()

    return run


async def _snapshot(engine: AsyncEngine) -> list[tuple[str, str, str, bool]]:
    """``(partner code, real, mask, carries the sentinel)`` per alias."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT p.code, a.real_flight_name, a.mask_flight_name, "
                "a.created_at = :stamp AND a.updated_at = :stamp "
                "FROM partner_flight_aliases a JOIN partners p ON p.id = a.partner_id "
                "ORDER BY p.code, a.id"
            ),
            {"stamp": _at(2026, 9, 11)},
        )
        return [(code, real, mask, sentinel) for code, real, mask, sentinel in rows]


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"revision_{REVISION}", REVISION_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> None:
    akb = Partner(code="AKB", display_name="AKB", prefix="A", is_dm_partner=True)
    syt = Partner(code="SYT", display_name="Triton", prefix="SYT", group_chat_id=-1001)
    ggx = Partner(code="GGX", display_name="Xorazm", prefix="GGX", group_chat_id=-1002)
    xon = Partner(code="XON", display_name="Xon", prefix="G", group_chat_id=-1003)
    old = Partner(
        code="OLD",
        display_name="Retired",
        prefix="Z",
        group_chat_id=-1004,
        is_active=False,
    )
    db_session.add_all([akb, syt, ggx, xon, old])
    await db_session.flush()
    by_code = {"AKB": akb, "GGX": ggx}

    db_session.add_all(
        [
            PartnerPrefixAlias(partner_id=syt.id, prefix="Q"),
            # Longer than AKB's primary ``A``: ``AQ…`` codes are Triton's.
            PartnerPrefixAlias(partner_id=syt.id, prefix="AQ"),
            # Duplicates AKB's primary prefix: ignored, ``A…`` stays AKB's.
            PartnerPrefixAlias(partner_id=syt.id, prefix="A"),
            # Owned by an inactive partner: ignored, ``AZ…`` stays AKB's.
            PartnerPrefixAlias(partner_id=old.id, prefix="AZ"),
            *(
                PartnerFlightAlias(
                    partner_id=by_code[code].id,
                    real_flight_name=real,
                    mask_flight_name=mask,
                )
                for code, real, mask in PRE_EXISTING
            ),
            FlightCargo(
                client_id="a01-1/1 ",
                flight_name="M200",
                created_at=_at(2026, 1, 5),
                photo_file_ids="[]",
            ),
            FlightCargo(
                client_id="A02",
                flight_name="M100",
                created_at=_at(2025, 10, 1),
                photo_file_ids="[]",
            ),
            FlightCargo(
                client_id="GGX12",
                flight_name="M200",
                created_at=_at(2026, 1, 2),
                photo_file_ids="[]",
            ),
            FlightCargo(
                client_id="SYT9",
                flight_name="T0",
                created_at=_at(2026, 1, 20),
                photo_file_ids="[]",
            ),
            # Same client and flight again, later: the earliest row must count.
            FlightCargo(
                client_id="SYT9",
                flight_name="T0",
                created_at=_at(2026, 4, 1),
                photo_file_ids="[]",
            ),
            CargoItem(client_id="A03", flight_name="M300", created_at=_at(2026, 1, 1)),
            CargoItem(
                client_id="A01-1/1", flight_name="M200", created_at=_at(2026, 1, 10)
            ),
            CargoItem(client_id="A04", flight_name=None, created_at=_at(2020, 1, 1)),
            CargoItem(client_id="Z1", flight_name="Z-FL", created_at=_at(2025, 1, 1)),
            _transaction("AZ1", "M150", _at(2026, 1, 3)),
            _transaction("Q12", "T1", _at(2026, 2, 1)),
            _transaction("A5", "M400", _at(2025, 11, 1)),
            _transaction("A6", "   ", _at(2020, 1, 1)),
            _transaction("A6", "L" * 101, _at(2020, 1, 1)),
            _transaction("X99", "M999", _at(2020, 1, 1)),
            # Bookkeeping rows share the reys column but are not flights: they must
            # get no alias and consume no counter number, even as the earliest rows.
            _transaction("A5", "UZPOST", _at(2019, 1, 1)),
            _transaction("A5", "WALLET_ADJ:refund", _at(2019, 1, 2)),
            _transaction("A5", "SYS_ADJ:correction", _at(2019, 1, 3)),
            _transaction("A5", "BONUS:referral", _at(2019, 1, 4)),
            _transaction("A5", "PENALTY:late pickup", _at(2019, 1, 5)),
            ExpectedFlightCargo(
                client_code="AQ7",
                flight_name="T0",
                track_code="TR1",
                created_at=_at(2026, 3, 1),
            ),
            ExpectedFlightCargo(
                client_code="A7",
                flight_name="M200",
                track_code="TR2",
                created_at=_at(2025, 12, 20),
            ),
            ExpectedFlightCargo(
                client_code="A9",
                flight_name="M310",
                track_code="TR3",
                created_at=_at(2026, 1, 4),
            ),
            ExpectedFlightCargo(
                client_code="A8",
                flight_name="M305",
                track_code="TR4",
                created_at=_at(2026, 1, 4),
            ),
            ExpectedFlightCargo(
                client_code="A10",
                flight_name="M888",
                track_code="TR5",
                is_placeholder=True,
                created_at=_at(2020, 1, 1),
            ),
            ExpectedFlightCargo(
                client_code="G5",
                flight_name="M500",
                track_code="TR6",
                created_at=_at(2026, 1, 1),
            ),
        ]
    )
    await db_session.commit()


def test_revision_extends_the_previous_head(migration: ModuleType) -> None:
    assert migration.revision == REVISION
    assert migration.down_revision == "c3f8a2d6e1b4"

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1
    assert REVISION in {
        rev.revision for rev in script.iterate_revisions(heads[0], "base")
    }


async def test_backfill_masks_partner_flights_in_order_of_first_appearance(
    db_engine: AsyncEngine, seeded: None, migration: ModuleType
) -> None:
    async with db_engine.begin() as conn:
        inserted = await conn.run_sync(migration.backfill_aliases)

    assert inserted == {"AKB": 6, "GGX": 1, "SYT": 2, "XON": 1}
    expected = _snapshot_of(PRE_EXISTING, backfilled=False) + _snapshot_of(
        BACKFILLED, backfilled=True
    )
    assert await _snapshot(db_engine) == sorted(expected, key=lambda row: row[0])


async def test_running_the_upgrade_again_inserts_nothing(
    db_engine: AsyncEngine, seeded: None, migration: ModuleType
) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(_through_alembic(migration.upgrade))
    after_upgrade = await _snapshot(db_engine)

    async with db_engine.begin() as conn:
        inserted = await conn.run_sync(migration.backfill_aliases)

    assert inserted == {"AKB": 0, "GGX": 0, "SYT": 0, "XON": 0}
    assert len(after_upgrade) == len(PRE_EXISTING) + len(BACKFILLED)
    assert await _snapshot(db_engine) == after_upgrade


async def test_downgrade_removes_only_unedited_backfilled_aliases(
    db_engine: AsyncEngine, seeded: None, migration: ModuleType
) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(_through_alembic(migration.upgrade))
        await conn.execute(
            text(
                "UPDATE partner_flight_aliases SET updated_at = now() "
                "WHERE mask_flight_name = 'AKB5'"
            )
        )

    async with db_engine.begin() as conn:
        await conn.run_sync(_through_alembic(migration.downgrade))

    assert await _snapshot(db_engine) == [
        ("AKB", "M100", "AKB3", False),
        ("AKB", "M101", "AKB-150", False),
        ("AKB", "M102", "akb9", False),
        ("AKB", "M200", "AKB5", False),
        ("GGX", "M900", "GGX2", False),
    ]
