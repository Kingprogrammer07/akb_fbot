"""Seed builders, expectations and read-backs for ``test_notification_scheduler``.

Not collected by pytest: the module name does not start with ``test_``.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from src.bot.utils.i18n import i18n
from src.infrastructure.database.models.cargo_item import CargoItem
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.notification import Notification
from src.infrastructure.database.models.partner import Partner
from src.infrastructure.database.models.partner_flight_alias import PartnerFlightAlias
from src.infrastructure.database.models.static_data import StaticData
from src.infrastructure.services.flight_display import FLIGHT_PLACEHOLDER
from src.infrastructure.tools.datetime_utils import get_current_time

REAL_FLIGHTS = ("M7001", "M7002", "M7003")
PARTNER_BY_PREFIX: dict[str, str | None] = {"A": "AKB", "P": "NAVO", "Z": None}
# Each partner is left exactly one flight without an alias, so the reminders
# mint one alias per partner and the minted masks are known in advance:
# ``{partner code}{highest N among its "{partner code}N" masks + 1}``.
MASKS: dict[tuple[str, str], str] = {
    ("AKB", "M7001"): "AKB1",
    ("AKB", "M7002"): "AKB2",
    ("NAVO", "M7001"): "NV1",
    ("NAVO", "M7003"): "NV3",
}
MINTED_MASKS: dict[tuple[str, str], str] = {
    ("AKB", "M7003"): "AKB3",
    ("NAVO", "M7002"): "NAVO1",
}
REMINDER_DAYS = (5, 2, 0)


@dataclass
class ReminderClient:
    telegram_id: int
    language: str
    partner_code: str | None
    due: list[tuple[str, int, datetime]]


@dataclass(frozen=True)
class LeftoverClient:
    telegram_id: int
    code: str
    """The client code its leftover rows carry."""
    language: str
    paid: int
    unpaid: int


def make_client(
    code: str, telegram_id: int | None, language: str, **codes: str
) -> Client:
    return Client(
        telegram_id=telegram_id,
        full_name=f"Client {code}",
        language_code=language,
        client_code=code,
        **codes,
    )


def make_transaction(
    code: str,
    telegram_id: int,
    flight: str,
    row: int,
    *,
    status: str = "partial",
    deadline: datetime | None = None,
    taken_away: bool = False,
) -> ClientTransaction:
    return ClientTransaction(
        telegram_id=telegram_id,
        client_code=code,
        qator_raqami=row,
        reys=flight,
        summa=1_500_000,
        vazn="10",
        payment_type="online",
        payment_status=status,
        paid_amount=500_000,
        total_amount=1_500_000,
        remaining_amount=1_000_000,
        payment_deadline=deadline,
        payment_balance_difference=0,
        is_taken_away=taken_away,
    )


def sent_cargo(code: str, flight: str) -> FlightCargo:
    return FlightCargo(
        flight_name=flight,
        client_id=code,
        photo_file_ids="[]",
        is_sent=True,
        is_sent_web=False,
    )


def used_item(code: str, flight: str) -> CargoItem:
    return CargoItem(
        flight_name=flight, client_id=code, checkin_status="post", is_used=True
    )


async def seed_partial_payments(engine: AsyncEngine) -> dict[int, ReminderClient]:
    """Every prefix x flight x due-day combination, plus rows that must be ignored."""
    now = get_current_time()
    rows: Iterator[int] = itertools.count(1)
    due_in = {days: now + timedelta(days=days, hours=6) for days in (*REMINDER_DAYS, 3)}
    eligible: dict[int, ReminderClient] = {}

    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        partners = {
            "AKB": Partner(
                code="AKB", display_name="AKB", prefix="A", is_dm_partner=True
            ),
            "NAVO": Partner(
                code="NAVO", display_name="Navo", prefix="P", group_chat_id=-100500
            ),
        }
        session.add_all(partners.values())
        await session.flush()
        session.add_all(
            PartnerFlightAlias(
                partner_id=partners[partner].id,
                real_flight_name=real,
                mask_flight_name=mask,
            )
            for (partner, real), mask in MASKS.items()
        )

        combinations = itertools.product(PARTNER_BY_PREFIX, REAL_FLIGHTS, REMINDER_DAYS)
        for index, (prefix, flight, days) in enumerate(combinations):
            code = f"{prefix}80/{index}"
            client = ReminderClient(
                telegram_id=910_000 + index,
                language=("uz", "ru")[index % 2],
                partner_code=PARTNER_BY_PREFIX[prefix],
                due=[(flight, days, due_in[days])],
            )
            eligible[client.telegram_id] = client
            session.add(make_client(code, client.telegram_id, client.language))
            session.add(
                make_transaction(
                    code, client.telegram_id, flight, next(rows), deadline=due_in[days]
                )
            )

        # The first client gets a second due reminder in the same message, plus
        # rows that must stay silent: 3 days left, overdue, and already paid.
        first = eligible[910_000]
        first.due.append(("M7002", 2, due_in[2]))
        for flight, deadline, status in (
            ("M7002", due_in[2], "partial"),
            ("M7003", due_in[3], "partial"),
            ("M7001", now - timedelta(hours=6), "partial"),
            ("M7003", due_in[5], "paid"),
        ):
            session.add(
                make_transaction(
                    "A80/0",
                    910_000,
                    flight,
                    next(rows),
                    status=status,
                    deadline=deadline,
                )
            )

        # A client with nothing due, and a due row whose telegram id has no client.
        session.add(make_client("A81/1", 920_001, "uz"))
        session.add(
            make_transaction("A81/1", 920_001, "M7001", next(rows), deadline=due_in[3])
        )
        session.add(
            make_transaction("A81/2", 920_002, "M7001", next(rows), deadline=due_in[5])
        )
        await session.commit()

    return eligible


async def seed_leftovers(engine: AsyncEngine) -> dict[int, LeftoverClient]:
    """Clients reached through paid, sent-cargo and used-item leftovers, plus skips."""
    rows: Iterator[int] = itertools.count(1)
    expected: dict[int, LeftoverClient] = {}

    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        for index in range(16):
            code = f"{'APZ'[index % 3]}90/{index}"
            telegram_id = 930_000 + index
            language = ("ru", "uz")[index % 2]
            # One client is known to its leftover rows only by its extra_code.
            lookup = f"{code}-X" if index == 5 else code
            extra = {"extra_code": lookup} if index == 5 else {}
            session.add(make_client(code, telegram_id, language, **extra))

            kind = index % 4
            if kind == 0:
                paid, unpaid = 2, 0
                for flight in ("M7001", "M7002"):
                    session.add(
                        make_transaction(lookup, telegram_id, flight, next(rows))
                    )
            elif kind == 1:
                paid, unpaid = 0, 1
                session.add(
                    make_transaction(
                        lookup, telegram_id, "M7001", next(rows), taken_away=True
                    )
                )
                session.add(sent_cargo(lookup, "M7003"))
            elif kind == 2:
                paid, unpaid = 1, 1
                session.add(make_transaction(lookup, telegram_id, "M7001", next(rows)))
                session.add(used_item(lookup, "M7002"))
            else:
                paid, unpaid = 1, 0
                session.add(make_transaction(lookup, telegram_id, "M7001", next(rows)))
                session.add(sent_cargo(lookup, "M7001"))
            expected[telegram_id] = LeftoverClient(
                telegram_id, lookup, language, paid, unpaid
            )

        # Skipped: a code with no client, and a client without a telegram id.
        session.add(make_transaction("Z99/404", 999_404, "M7001", next(rows)))
        session.add(make_client("A99/1", None, "uz"))
        session.add(used_item("A99/1", "M7001"))
        # Nothing left over: every row of this client was taken away.
        session.add(make_client("P99/7", 939_007, "uz"))
        session.add(
            make_transaction("P99/7", 939_007, "M7002", next(rows), taken_away=True)
        )
        await session.commit()

    return expected


async def seed_notification_settings(engine: AsyncEngine, period_days: int) -> None:
    """The settings row, with leftover notifications due every ``period_days`` days."""
    async with async_sessionmaker(engine)() as session:
        session.add(StaticData(notification=True, notification_period=period_days))
        await session.commit()


def expected_reminder_parts(client: ReminderClient) -> list[str]:
    masks = {**MASKS, **MINTED_MASKS}
    parts = []
    for flight, days, deadline in client.due:
        values = {
            "flight": masks.get((client.partner_code, flight), FLIGHT_PLACEHOLDER),
            "total": "1,500,000",
            "paid": "500,000",
            "remaining": "1,000,000",
            "deadline": deadline.strftime("%Y-%m-%d"),
        }
        if days == 0:
            parts.append(
                i18n.get(client.language, "reminder-partial-deadline-today", **values)
            )
        else:
            key = (
                "reminder-partial-deadline-2days"
                if days == 2
                else "reminder-partial-deadline-5days"
            )
            parts.append(i18n.get(client.language, key, days=days, **values))
    return sorted(parts)


def expected_leftover_text(client: LeftoverClient) -> str:
    language = client.language
    return (
        f"{i18n.get(language, 'notification-leftover-greeting')}\n\n"
        f"{i18n.get(language, 'notification-leftover-explanation')}\n\n"
        f"{i18n.get(language, 'notification-leftover-paid-count', count=client.paid)}\n"
        f"{i18n.get(language, 'notification-leftover-unpaid-count', count=client.unpaid)}\n\n"
        f"{i18n.get(language, 'notification-leftover-call-to-action')}"
    )


async def persisted_by_chat(
    engine: AsyncEngine,
) -> dict[int, list[tuple[str, str, str]]]:
    async with async_sessionmaker(engine)() as session:
        result = await session.execute(
            select(
                Client.telegram_id,
                Notification.title,
                Notification.type,
                Notification.body,
            ).join(Client, Client.id == Notification.client_id)
        )
    persisted: dict[int, list[tuple[str, str, str]]] = {}
    for telegram_id, title, notif_type, body in result.all():
        persisted.setdefault(telegram_id, []).append((title, notif_type, body))
    return persisted


async def aliases_by_partner(engine: AsyncEngine) -> dict[tuple[str, str], str]:
    """Every committed alias, as ``{(partner code, real flight): mask}``."""
    async with async_sessionmaker(engine)() as session:
        result = await session.execute(
            select(
                Partner.code,
                PartnerFlightAlias.real_flight_name,
                PartnerFlightAlias.mask_flight_name,
            ).join(Partner, Partner.id == PartnerFlightAlias.partner_id)
        )
        return {(partner, real): mask for partner, real, mask in result.all()}


async def idle_in_transaction_backends(engine: AsyncEngine) -> int:
    """Connections to the test database left idle inside an open transaction."""
    async with engine.connect() as connection:
        return await connection.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND state LIKE 'idle in transaction%'"
            )
        )
