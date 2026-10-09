"""
The process-wide partner cache must not depend on the session that filled it.

``PartnerResolver`` cached the ORM ``Partner`` instances of whichever session
happened to load them.  Once that session rolled back (or committed with
``expire_on_commit``) and closed, every cached partner was expired and
detached, so the next caller, on a healthy session of its own, got
``DetachedInstanceError`` from ``partner.code`` until the cache was reloaded.
"""

import dataclasses
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.infrastructure.database.dao.partner import PartnerDAO
from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_prefix_alias import PartnerPrefixAlias
from src.infrastructure.services.partner_resolver import PartnerResolver

RESOLVER_LOGGER = "src.infrastructure.services.partner_resolver"

AKB: dict[str, str | int | bool | None] = {
    "code": "AKB",
    "display_name": "AKB Cargo",
    "prefix": "A",
    "group_chat_id": None,
    "is_dm_partner": True,
    "is_active": True,
}
NAVO: dict[str, str | int | bool | None] = {
    "code": "NAVO",
    "display_name": "Navo Cargo",
    "prefix": "P",
    "group_chat_id": -1001234567890,
    "is_dm_partner": False,
    "is_active": True,
}
NAVO_ALIAS = "SYT"
NAVO_CLIENT_CODE = "P80/1"

ROUTING_ATTRIBUTES = (
    "id",
    "code",
    "display_name",
    "prefix",
    "group_chat_id",
    "is_dm_partner",
    "is_active",
)

SessionEnding = Callable[[AsyncSession], Awaitable[None]]


async def roll_back(session: AsyncSession) -> None:
    await session.rollback()


async def commit(session: AsyncSession) -> None:
    await session.commit()


# How the session that filled the cache ends -> (expire_on_commit, ending)
LOADING_SESSION_ENDINGS: dict[str, tuple[bool, SessionEnding]] = {
    "rolled-back": (False, roll_back),
    "committed-with-expire-on-commit": (True, commit),
}


async def seed_partners(
    engine: AsyncEngine, *navo_prefix_aliases: str
) -> dict[str, int]:
    """Insert AKB and Navo, plus extra Navo prefixes; return their ids by code."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        akb, navo = Partner(**AKB), Partner(**NAVO)
        session.add_all([akb, navo])
        await session.flush()
        session.add_all(
            [
                PartnerPrefixAlias(partner_id=navo.id, prefix=prefix)
                for prefix in navo_prefix_aliases
            ]
        )
        await session.commit()
        return {"AKB": akb.id, "NAVO": navo.id}


def routing_view(partner: object) -> dict[str, object]:
    return {name: getattr(partner, name) for name in ROUTING_ATTRIBUTES}


@contextmanager
def recorded_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    """Collect the SQL ``engine`` sends while the block runs."""
    statements: list[str] = []

    def _record(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)


@pytest.mark.parametrize(
    ("expire_on_commit", "end_session"),
    list(LOADING_SESSION_ENDINGS.values()),
    ids=list(LOADING_SESSION_ENDINGS),
)
async def test_cached_partners_outlive_the_session_that_loaded_them(
    db_engine: AsyncEngine, expire_on_commit: bool, end_session: SessionEnding
) -> None:
    ids = await seed_partners(db_engine, NAVO_ALIAS)
    resolver = PartnerResolver()

    async with AsyncSession(db_engine, expire_on_commit=expire_on_commit) as session_a:
        await resolver.resolve_by_client_code(session_a, NAVO_CLIENT_CODE)
        await end_session(session_a)

    with recorded_statements(db_engine) as statements:
        async with AsyncSession(db_engine) as session_b:
            by_prefix = await resolver.resolve_by_client_code(
                session_b, NAVO_CLIENT_CODE
            )
            by_alias = await resolver.resolve_by_client_code(
                session_b, f"{NAVO_ALIAS}80/1"
            )
            by_code = await resolver.get_by_code(session_b, "navo")
            active = await resolver.all_active(session_b)
        views = [routing_view(p) for p in (by_prefix, by_alias, by_code, *active)]

    navo = {"id": ids["NAVO"], **NAVO}
    akb = {"id": ids["AKB"], **AKB}
    assert views == [navo, navo, navo, akb, navo]
    assert statements == []


async def test_cached_partners_are_read_only(db_engine: AsyncEngine) -> None:
    """Every request shares the cache; one caller must not re-route another's clients."""
    await seed_partners(db_engine)
    resolver = PartnerResolver()

    async with AsyncSession(db_engine) as session:
        partner = await resolver.resolve_by_client_code(session, NAVO_CLIENT_CODE)

    with pytest.raises(dataclasses.FrozenInstanceError):
        partner.group_chat_id = -1009999999999


async def test_refresh_leaves_the_callers_own_partner_attached(
    db_engine: AsyncEngine,
) -> None:
    """
    Partner admin flows edit a partner, commit, and refresh the cache through
    the same session while still holding their instance; the refresh must not
    take that instance away from their session.
    """
    await seed_partners(db_engine)
    resolver = PartnerResolver()
    new_group_chat_id = -1009876543210

    async with AsyncSession(db_engine, expire_on_commit=False) as session:
        navo = await PartnerDAO.get_by_code(session, "NAVO")
        assert navo is not None
        await PartnerDAO.update(session, navo, {"group_chat_id": new_group_chat_id})
        await session.commit()
        await resolver.refresh(session)

        assert navo in session
        cached = await resolver.get_by_code(session, "NAVO")

    assert cached is not None
    assert cached.group_chat_id == new_group_chat_id


async def test_alias_duplicating_another_partners_prefix_is_ignored_and_logged(
    db_engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    await seed_partners(db_engine, "A")
    resolver = PartnerResolver()

    with caplog.at_level(logging.ERROR, logger=RESOLVER_LOGGER):
        async with AsyncSession(db_engine) as session:
            partner = await resolver.resolve_by_client_code(session, "A01-1/1")

    assert partner.code == "AKB"
    assert [r.getMessage() for r in caplog.records if r.name == RESOLVER_LOGGER] == [
        "PartnerResolver: prefix alias 'A' of partner NAVO ignored — "
        "already owned by partner AKB"
    ]
