import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass

from sqlalchemy import func, select

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bot.utils.currency_cache import DEFAULT_USD_TO_UZS_RATE
from src.bot.utils.currency_converter import currency_converter
from src.config import config
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.partner import PartnerDAO
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.flight_cargo import FlightCargo

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PartnerRule:
    code: str
    prefix: str
    is_dm_partner: bool


@dataclass
class BackfillStats:
    scanned_groups: int = 0
    eligible: int = 0
    inserted: int = 0
    skipped_existing_flight_tx: int = 0
    skipped_existing_row_tx: int = 0
    skipped_non_partner: int = 0
    skipped_dm_partner: int = 0
    skipped_zero_amount: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill missing flight-level pending debts for sent partner cargos. "
            "Dry-run by default; pass --apply to insert rows."
        )
    )
    parser.add_argument("--apply", action="store_true", help="Write missing debts to DB.")
    parser.add_argument("--flight", help="Only process one flight name.")
    parser.add_argument("--client", help="Only process one client code.")
    parser.add_argument(
        "--include-dm-partners",
        action="store_true",
        help="Also process DM partners such as AKB. Default is non-DM partners only.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after N eligible inserts/planned inserts. 0 means no limit.",
    )
    return parser.parse_args()


def match_partner(client_code: str, rules: list[PartnerRule]) -> PartnerRule | None:
    code = client_code.strip().upper()
    for rule in rules:
        if code.startswith(rule.prefix):
            return rule
    return None


async def load_partner_rules(session) -> list[PartnerRule]:
    partners = await PartnerDAO.get_all(session)
    rules = [
        PartnerRule(
            code=partner.code,
            prefix=partner.prefix.strip().upper(),
            is_dm_partner=partner.is_dm_partner,
        )
        for partner in partners
        if partner.is_active and partner.prefix
    ]
    rules.sort(key=lambda item: len(item.prefix), reverse=True)
    return rules


async def load_sent_cargo_groups(session, flight: str | None, client: str | None):
    stmt = (
        select(FlightCargo.client_id, FlightCargo.flight_name)
        .where(FlightCargo.is_sent == True)  # noqa: E712
        .group_by(FlightCargo.client_id, FlightCargo.flight_name)
        .order_by(FlightCargo.flight_name, FlightCargo.client_id)
    )
    if flight:
        stmt = stmt.where(func.upper(FlightCargo.flight_name) == flight.upper())
    if client:
        stmt = stmt.where(func.upper(FlightCargo.client_id) == client.upper())

    result = await session.execute(stmt)
    return result.all()


async def load_group_cargos(
    session,
    lookup_codes: list[str],
    flight_name: str,
) -> list[FlightCargo]:
    upper_codes = [code.upper() for code in lookup_codes if code]
    if not upper_codes:
        return []

    result = await session.execute(
        select(FlightCargo).where(
            func.upper(FlightCargo.client_id).in_(upper_codes),
            func.upper(FlightCargo.flight_name) == flight_name.upper(),
            FlightCargo.is_sent == True,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def has_per_cargo_transaction(
    session,
    lookup_codes: list[str],
    flight_name: str,
) -> bool:
    upper_codes = [code.upper() for code in lookup_codes if code]
    if not upper_codes:
        return False

    result = await session.execute(
        select(ClientTransaction.id)
        .where(
            func.upper(ClientTransaction.client_code).in_(upper_codes),
            func.upper(ClientTransaction.reys) == flight_name.upper(),
            ClientTransaction.qator_raqami != 0,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def has_flight_level_transaction(
    session,
    lookup_codes: list[str],
    flight_name: str,
) -> bool:
    upper_codes = [code.upper() for code in lookup_codes if code]
    if not upper_codes:
        return False

    result = await session.execute(
        select(ClientTransaction.id)
        .where(
            func.upper(ClientTransaction.client_code).in_(upper_codes),
            func.upper(ClientTransaction.reys) == flight_name.upper(),
            ClientTransaction.qator_raqami == 0,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def main() -> None:
    args = parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("Mode: %s", mode)

    stats = BackfillStats()

    async with DatabaseClient(config.database.database_url) as db_client:
        async with db_client.session_factory() as session:
            partner_rules = await load_partner_rules(session)

            static_data = await StaticDataDAO.get_first(session)
            extra_charge = float(static_data.extra_charge) if static_data else 0.0

            try:
                rate = await currency_converter.get_rate_async(session, "USD", "UZS")
            except Exception:
                rate = DEFAULT_USD_TO_UZS_RATE
                logger.warning("USD rate fallback used: %s", rate)

            groups = await load_sent_cargo_groups(session, args.flight, args.client)
            logger.info("Found %d sent client+flight group(s).", len(groups))

            for raw_client_code, flight_name in groups:
                stats.scanned_groups += 1
                client_code = raw_client_code.strip().upper()

                partner = match_partner(client_code, partner_rules)
                if partner is None:
                    stats.skipped_non_partner += 1
                    continue
                if partner.is_dm_partner and not args.include_dm_partners:
                    stats.skipped_dm_partner += 1
                    continue

                client = await ClientDAO.get_by_client_code(session, client_code)
                lookup_codes = client.active_codes if client else [client_code]
                transaction_code = client.payment_code if client else client_code

                if await has_flight_level_transaction(session, lookup_codes, flight_name):
                    stats.skipped_existing_flight_tx += 1
                    continue

                if await has_per_cargo_transaction(session, lookup_codes, flight_name):
                    stats.skipped_existing_row_tx += 1
                    logger.warning(
                        "SKIP %s %s: per-cargo transaction exists; manual review needed.",
                        client_code,
                        flight_name,
                    )
                    continue

                cargos = await load_group_cargos(session, lookup_codes, flight_name)
                total_weight = 0.0
                total_price_uzs = 0.0
                cargo_ids: list[int] = []
                for cargo in cargos:
                    cargo_ids.append(cargo.id)
                    weight = float(cargo.weight_kg or 0)
                    price_per_kg_usd = float(cargo.price_per_kg or 0)
                    total_weight += weight
                    total_price_uzs += price_per_kg_usd * rate * weight

                total_payment = total_price_uzs + extra_charge
                if total_payment <= 0:
                    stats.skipped_zero_amount += 1
                    logger.warning(
                        "SKIP %s %s: calculated total_payment <= 0",
                        client_code,
                        flight_name,
                    )
                    continue

                stats.eligible += 1
                telegram_id = client.telegram_id if client and client.telegram_id else 0

                logger.info(
                    "%s debt %s %s partner=%s cargos=%d weight=%.2f amount=%.2f tg=%s",
                    "INSERT" if args.apply else "WOULD INSERT",
                    transaction_code,
                    flight_name,
                    partner.code,
                    len(cargo_ids),
                    total_weight,
                    total_payment,
                    telegram_id,
                )

                if args.apply:
                    await ClientTransactionDAO.create(
                        session,
                        {
                            "telegram_id": telegram_id,
                            "client_code": transaction_code,
                            "qator_raqami": 0,
                            "reys": flight_name,
                            "summa": 0,
                            "vazn": str(round(total_weight, 2)),
                            "payment_type": "online",
                            "payment_status": "pending",
                            "paid_amount": 0,
                            "total_amount": total_payment,
                            "remaining_amount": total_payment,
                            "payment_balance_difference": -total_payment,
                            "is_taken_away": False,
                        },
                    )
                    stats.inserted += 1

                if args.limit and stats.eligible >= args.limit:
                    logger.info("Limit reached: %d", args.limit)
                    break

            if args.apply:
                await session.commit()
            else:
                await session.rollback()

    logger.info(
        "Done. scanned=%d eligible=%d inserted=%d existing_flight_tx=%d "
        "existing_row_tx=%d non_partner=%d dm_partner=%d zero_amount=%d",
        stats.scanned_groups,
        stats.eligible,
        stats.inserted,
        stats.skipped_existing_flight_tx,
        stats.skipped_existing_row_tx,
        stats.skipped_non_partner,
        stats.skipped_dm_partner,
        stats.skipped_zero_amount,
    )
    if not args.apply:
        logger.info("Dry-run only. Re-run with --apply to insert eligible debts.")


if __name__ == "__main__":
    asyncio.run(main())
