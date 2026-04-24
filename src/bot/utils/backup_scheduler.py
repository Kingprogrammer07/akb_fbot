"""Background scheduler for automatic daily database backups and maintenance tasks."""

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

from aiogram import Bot
from aiogram.types import BufferedInputFile

from src.bot.utils.db_backup import create_database_backup, cleanup_backup_file
from src.config import config

logger = logging.getLogger(__name__)

INACTIVITY_DAYS = 30


async def send_backup_to_channel(bot: Bot, channel_id: int, backup_path: Path) -> None:
    """
    Send backup file to specified channel.

    Args:
        bot: Bot instance
        channel_id: Telegram channel ID
        backup_path: Path to backup file
    """
    try:
        # Read backup file
        with open(backup_path, "rb") as f:
            backup_data = f.read()

        # Create BufferedInputFile for sending
        file = BufferedInputFile(file=backup_data, filename=backup_path.name)

        from src.infrastructure.tools.datetime_utils import get_current_business_time

        # Send to channel
        await bot.send_document(
            chat_id=channel_id,
            document=file,
            caption=f"📦 Database backup - {get_current_business_time().strftime('%Y-%m-%d %H:%M:%S')}",
            request_timeout=300,  # Set 5-minute timeout for large backup files
        )

        logger.info(f"Backup sent to channel {channel_id}: {backup_path.name}")

    except Exception as e:
        logger.error(
            f"Failed to send backup to channel {channel_id}: {e}", exc_info=True
        )
        raise


async def auto_deactivate_inactive_clients() -> int:
    """
    Sets is_logged_in=False for clients who have not interacted with the bot
    for more than INACTIVITY_DAYS days.

    Activity is determined by ``clients.last_seen_at``.  Clients whose
    ``last_seen_at`` is NULL (registered before the column was added) are
    NOT touched — we only deactivate clients for whom we have a real signal.

    Returns the number of rows updated.
    """
    from sqlalchemy import update as sa_update, text as sa_text
    from src.infrastructure.database.client import DatabaseClient
    from src.infrastructure.database.models.client import Client
    from src.infrastructure.tools.datetime_utils import get_current_time

    cutoff = get_current_time() - timedelta(days=INACTIVITY_DAYS)

    db_client = DatabaseClient(config.database.database_url)
    try:
        async with db_client.session_factory() as session:
            # Only deactivate clients where last_seen_at is known and older than cutoff.
            # NULL last_seen_at means we have no signal yet → leave them untouched.
            result = await session.execute(
                sa_update(Client)
                .where(
                    Client.is_logged_in == True,
                    Client.last_seen_at.isnot(None),
                    Client.last_seen_at < cutoff,
                )
                .values(is_logged_in=False)
                .returning(Client.id)
            )
            updated = len(result.fetchall())
            await session.commit()
            return updated
    finally:
        await db_client.shutdown()


async def run_daily_ostatka_send(bot: Bot) -> None:
    """Send all unsent A- cargos to the ostatka group, then post a digest.

    For each A- flight that has unsent cargo:
      1. Groups cargo by client_id and runs OstatkaBulkSender (which also
         posts a per-flight stats summary after processing each flight).
      2. Once all flights are processed, posts the aggregate daily digest.

    Only flights whose names are in the ``ostatka_daily_flight_names``
    whitelist on the StaticData singleton are sent.  An empty list means
    nothing is sent, so the feature is effectively a no-op until the admin
    selects at least one flight in ⚙️ Sozlamalar → Reys tanlash.
    """
    import json
    import uuid
    from collections import defaultdict

    from sqlalchemy import select as sa_select

    from src.bot.handlers.admin.ostatka_sender import (
        OstatkaBulkSender,
        OSTATKA_FLIGHT_PREFIX,
    )
    from src.bot.utils.ostatka_stats import send_daily_ostatka_stats
    from src.infrastructure.database.client import DatabaseClient
    from src.infrastructure.database.dao.static_data import StaticDataDAO
    from src.infrastructure.database.models.flight_cargo import FlightCargo

    logger.info("[Ostatka] Starting daily A- cargo send...")

    # Read the whitelist of selected flights
    selected_flights: list[str] = []
    try:
        async with DatabaseClient(config.database.database_url) as db:
            async with db.session_factory() as session:
                static_data = await StaticDataDAO.get_first(session)
                raw = getattr(static_data, "ostatka_daily_flight_names", "[]") or "[]"
                selected_flights = [n.upper() for n in json.loads(raw) if n]
    except Exception as exc:
        logger.error("[Ostatka] Failed to read selected flights list: %s", exc, exc_info=True)
        return

    if not selected_flights:
        logger.info("[Ostatka] No flights selected for daily send — skipping")
        return

    # Collect unsent A- cargo rows for selected flights only
    async with DatabaseClient(config.database.database_url) as db:
        async with db.session_factory() as session:
            rows = (
                await session.execute(
                    sa_select(
                        FlightCargo.flight_name,
                        FlightCargo.id,
                        FlightCargo.client_id,
                    ).where(
                        FlightCargo.flight_name.ilike(f"{OSTATKA_FLIGHT_PREFIX}%"),
                        FlightCargo.is_sent == False,  # noqa: E712
                    )
                )
            ).all()

    # Filter to whitelisted flights only
    rows = [r for r in rows if r.flight_name.upper() in selected_flights]

    if not rows:
        logger.info("[Ostatka] No unsent A- cargos found for selected flights")
        # Still post a stats digest so the group gets the daily overview
        try:
            await send_daily_ostatka_stats(bot)
        except Exception as exc:
            logger.error("[Ostatka] Post-send stats failed: %s", exc, exc_info=True)
        return

    # Group: flight_name → client_id → [cargo_id, ...]
    flights: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        flights[row.flight_name][row.client_id].append(row.id)

    group_chat_id = config.telegram.AKB_OSTATKA_GROUP_ID
    total_sent = total_failed = 0

    for flight_name, clients_data in sorted(flights.items()):
        task_id = f"daily_{flight_name}_{uuid.uuid4().hex[:8]}"
        sender = OstatkaBulkSender(
            bot=bot,
            flight_name=flight_name,
            clients_data=dict(clients_data),
            admin_chat_id=group_chat_id,
            task_id=task_id,
        )
        try:
            stats = await sender.run()
            total_sent += stats.sent
            total_failed += stats.failed + stats.blocked
            logger.info(
                "[Ostatka] Daily send for %s: sent=%d failed=%d blocked=%d",
                flight_name,
                stats.sent,
                stats.failed,
                stats.blocked,
            )
        except Exception as exc:
            logger.error(
                "[Ostatka] Daily send failed for flight %s: %s",
                flight_name,
                exc,
                exc_info=True,
            )

    logger.info(
        "[Ostatka] Daily send complete: total_sent=%d total_failed=%d",
        total_sent,
        total_failed,
    )

    # Final aggregate stats digest
    try:
        await send_daily_ostatka_stats(bot)
    except Exception as exc:
        logger.error("[Ostatka] Post-send stats failed: %s", exc, exc_info=True)


async def daily_backup_task(bot: Bot) -> None:
    """
    Background task that runs daily database backups AND maintenance jobs.

    Runs immediately on first start, then every 24 hours.
    """
    channel_id = config.telegram.DATABASE_BACKUP_CHANNEL_ID

    if not channel_id:
        logger.warning(
            "DATABASE_BACKUP_CHANNEL_ID not configured. Daily backups disabled."
        )
        return

    logger.info(f"Daily backup scheduler started. Channel ID: {channel_id}")

    first_run = True

    while True:
        try:
            if not first_run:
                logger.info("Waiting 24 hours until next backup...")
                await asyncio.sleep(24 * 60 * 60)

            first_run = False

            # --- Maintenance: deactivate inactive clients ---
            try:
                deactivated = await auto_deactivate_inactive_clients()
                if deactivated:
                    logger.info(
                        f"[Maintenance] {deactivated} mijoz {INACTIVITY_DAYS} kundan "
                        "oshgan inaktivlik sababli is_logged_in=False qilindi."
                    )
            except Exception as e:
                logger.error(f"auto_deactivate_inactive_clients failed: {e}", exc_info=True)

            # --- DB backup ---
            # Backup failure should not stop other daily jobs in this loop.
            backup_path = None
            try:
                logger.info("Starting scheduled database backup...")
                backup_path = create_database_backup()
                await send_backup_to_channel(bot, channel_id, backup_path)
                logger.info("Scheduled backup completed successfully")
            except Exception as e:
                logger.error(f"Scheduled backup failed: {e}", exc_info=True)
            finally:
                if backup_path is not None:
                    cleanup_backup_file(backup_path)

            # --- Daily ostatka send + digest ---
            # When the admin has enabled ``ostatka_daily_notifications`` AND
            # selected at least one A- flight in Sozlamalar → Reys tanlash,
            # run the full OstatkaBulkSender pipeline for each whitelisted
            # flight, then post the aggregate digest.  Failures here must
            # NOT break the backup loop.
            try:
                from src.bot.utils.ostatka_stats import is_daily_ostatka_enabled

                if await is_daily_ostatka_enabled():
                    await run_daily_ostatka_send(bot)
                    logger.info("Daily ostatka pipeline finished")
            except Exception as e:
                logger.error(f"daily ostatka pipeline failed: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error in daily backup task: {e}", exc_info=True)
            logger.info("Waiting 1 hour before retrying backup...")
            await asyncio.sleep(3600)


def start_backup_scheduler(bot: Bot) -> None:
    """Start the daily backup + maintenance scheduler as a background task."""
    logger.info("Starting database backup scheduler")
    asyncio.create_task(daily_backup_task(bot))
