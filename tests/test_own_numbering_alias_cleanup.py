"""Cleanup revision ``e2d7b5c1a940``: the masks minted over a partner's own numbering.

Only an alias whose real flight name is the owning partner's own
``CODE<digits>`` form - the shape the auto-generator produces - and whose mask
says something else may go.  The masks that carry the layer's whole purpose
stay: ``M280 -> AKB280`` for AKB, and another partner's mask for that same AKB
flight.
"""

import importlib.util
from collections.abc import Callable
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

from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_flight_alias import PartnerFlightAlias

ROOT = Path(__file__).resolve().parent.parent
REVISION = "e2d7b5c1a940"
REVISION_FILE = (
    ROOT / "alembic" / "versions" / f"{REVISION}_drop_own_numbering_flight_aliases.py"
)

# (partner code, real flight name, mask) — seeded before the revision runs.
DOOMED: list[tuple[str, str, str]] = [
    ("AKB", "AKB285", "AKB359"),  # the production case
    ("AKB", "akb284", "AKB358"),  # the import writes the code in any case
    ("SYT", "SYT12", "SYT99"),  # every partner, not just AKB
]
KEPT: list[tuple[str, str, str]] = [
    ("AKB", "M280", "AKB280"),  # the mask layer doing its job
    ("AKB", "AKB150", "AKB150"),  # already rendered as itself
    ("AKB", "AKB-285", "AKB360"),  # not the auto-generated form
    ("AKB", "AKB285X", "AKB361"),  # digits must run to the end
    ("SYT", "AKB285", "SYT7"),  # AKB's flight under Triton's own mask
    ("Q.X", "Q.X1", "Q.X5"),  # a code that is not a plain regex literal
]


def _through_alembic(operation: Callable[[], None]) -> Callable[[Connection], None]:
    """Run a revision's ``upgrade`` / ``downgrade`` with ``op`` bound to ``conn``."""

    def run(conn: Connection) -> None:
        with Operations.context(MigrationContext.configure(conn)):
            operation()

    return run


async def _snapshot(engine: AsyncEngine) -> list[tuple[str, str, str]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT p.code, a.real_flight_name, a.mask_flight_name "
                "FROM partner_flight_aliases a JOIN partners p ON p.id = a.partner_id "
                "ORDER BY p.code, a.id"
            )
        )
        return [(code, real, mask) for code, real, mask in rows]


@pytest.fixture
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"revision_{REVISION}", REVISION_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> None:
    partners = {
        "AKB": Partner(code="AKB", display_name="AKB", prefix="A", is_dm_partner=True),
        "SYT": Partner(
            code="SYT", display_name="Triton", prefix="SYT", group_chat_id=-1001
        ),
        "Q.X": Partner(
            code="Q.X", display_name="Odd", prefix="QX", group_chat_id=-1002
        ),
    }
    db_session.add_all(partners.values())
    await db_session.commit()

    for code, real, mask in DOOMED + KEPT:
        db_session.add(
            PartnerFlightAlias(
                partner_id=partners[code].id,
                real_flight_name=real,
                mask_flight_name=mask,
            )
        )
    await db_session.commit()


def test_revision_extends_the_previous_head(migration: ModuleType) -> None:
    assert migration.revision == REVISION
    assert migration.down_revision == "d4b9e7a1c2f5"

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert heads == [REVISION]


async def test_only_own_numbering_masks_are_dropped(
    db_engine: AsyncEngine, seeded: None, migration: ModuleType
) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(_through_alembic(migration.upgrade))

    assert await _snapshot(db_engine) == sorted(KEPT, key=lambda row: row[0])


async def test_running_the_upgrade_again_deletes_nothing(
    db_engine: AsyncEngine, seeded: None, migration: ModuleType
) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(_through_alembic(migration.upgrade))
    after_upgrade = await _snapshot(db_engine)

    async with db_engine.begin() as conn:
        await conn.run_sync(_through_alembic(migration.upgrade))

    assert await _snapshot(db_engine) == after_upgrade


async def test_downgrade_restores_nothing_and_keeps_the_rest(
    db_engine: AsyncEngine, seeded: None, migration: ModuleType
) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(_through_alembic(migration.upgrade))
        await conn.run_sync(_through_alembic(migration.downgrade))

    assert await _snapshot(db_engine) == sorted(KEPT, key=lambda row: row[0])


async def test_every_dropped_pair_is_logged(
    db_engine: AsyncEngine,
    seeded: None,
    migration: ModuleType,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The deploy log keeps what each number used to mean for the curators."""
    with caplog.at_level("INFO", logger="alembic.runtime.migration"):
        async with db_engine.begin() as conn:
            await conn.run_sync(_through_alembic(migration.upgrade))

    logged = "\n".join(record.getMessage() for record in caplog.records)
    for _code, real, mask in DOOMED:
        assert f"{real} as {mask}" in logged
    assert f"dropped {len(DOOMED)} own-numbering flight aliases" in logged
