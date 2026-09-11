"""Background notification scheduler for leftover cargo."""
import asyncio
import logging
from collections import defaultdict
from contextlib import aclosing
from dataclasses import dataclass
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.cargo_item import CargoItem
from src.bot.utils.i18n import i18n, get_user_language
from src.infrastructure.services.flight_display import FlightDisplay
from src.config import config
from src.infrastructure.database.dao.notification import NotificationDAO

logger = logging.getLogger(__name__)

# Rate limiting: max 10 concurrent sends
SEND_SEMAPHORE = asyncio.Semaphore(10)

# The leftover scheduler re-reads disabled or invalid settings, and retries
# after an error, once an hour.
NOTIFICATION_RECHECK_SECONDS = 3600

# Module-level task reference for graceful shutdown
notification_task: asyncio.Task | None = None
partial_payment_reminder_task: asyncio.Task | None = None


async def persist_notification(
    session,
    client_id: int,
    title: str,
    body: str,
    notif_type: str = "info"
):
    """
    Persist a notification record in the database.
    
    Called after successfully sending a Telegram message so the user
    can also see the notification in the WebApp history.
    """
    try:
        await NotificationDAO.create(
            session=session,
            client_id=client_id,
            title=title,
            body=body,
            notif_type=notif_type,
        )
        await session.commit()
    except Exception as e:
        logger.warning(f"Failed to persist notification for client {client_id}: {e}")
        # A failed flush leaves the transaction unusable; roll back so the
        # notifications persisted after this one are not lost as well.
        try:
            await session.rollback()
        except Exception as rollback_error:
            logger.warning(
                f"Rollback after the failed persist for client {client_id} "
                f"also failed: {rollback_error}"
            )


async def get_all_transactions(session) -> list[ClientTransaction]:
    """Get all client transactions."""
    from sqlalchemy import select
    result = await session.execute(
        select(ClientTransaction).order_by(ClientTransaction.client_code, ClientTransaction.reys)
    )
    return list(result.scalars().all())


async def get_all_sent_flight_cargos(session) -> list[FlightCargo]:
    """Get all flight cargos where is_sent = true."""
    from sqlalchemy import select
    result = await session.execute(
        select(FlightCargo)
        .where(FlightCargo.is_sent == True)
        .order_by(FlightCargo.flight_name, FlightCargo.client_id)
    )
    return list(result.scalars().all())


async def get_all_used_cargo_items(session) -> list[CargoItem]:
    """Get all cargo items where is_used = true."""
    from sqlalchemy import select
    result = await session.execute(
        select(CargoItem)
        .where(CargoItem.is_used == True)
        .order_by(CargoItem.flight_name, CargoItem.client_id)
    )
    return list(result.scalars().all())


async def check_transaction_exists(
    transactions: list[ClientTransaction],
    client_code: str,
    flight_name: str,
    row_number: Optional[int] = None
) -> Optional[ClientTransaction]:
    """Check if a transaction exists matching the criteria."""
    if not client_code or not flight_name:
        return None
    
    for transaction in transactions:
        if (transaction.client_code.upper() == client_code.upper() and
            transaction.reys.upper() == flight_name.upper()):
            if row_number is not None:
                if transaction.qator_raqami == row_number:
                    return transaction
            else:
                return transaction
    return None


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    """A rendered notification: sending it needs the bot only, never a session.

    An ``AsyncSession`` is not safe for concurrent use, so the senders below
    work in three phases: render every message sequentially on the session,
    send the messages concurrently, then persist the successful sends
    sequentially.
    """

    chat_id: int
    client_id: int
    client_code: str | None
    text: str
    title: str
    notif_type: str
    # None keeps the bot's default parse mode.
    parse_mode: str | None = None


async def _send_message(bot: Bot, message: OutgoingMessage) -> None:
    """Deliver ``message`` without overriding the bot's default parse mode."""
    if message.parse_mode is None:
        await bot.send_message(chat_id=message.chat_id, text=message.text)
    else:
        await bot.send_message(
            chat_id=message.chat_id,
            text=message.text,
            parse_mode=message.parse_mode,
        )


async def _persist_sent_messages(
    session: AsyncSession, sent_messages: list[OutgoingMessage]
) -> None:
    """Record delivered messages for the WebApp history, one at a time."""
    for message in sent_messages:
        await persist_notification(
            session=session,
            client_id=message.client_id,
            title=message.title,
            body=message.text,
            notif_type=message.notif_type,
        )


async def _render_partial_payment_reminder(
    session: AsyncSession,
    client: Client,
    reminders: list[tuple[ClientTransaction, int]],
) -> OutgoingMessage:
    """Combine one client's due reminders into a single message."""
    language = get_user_language(client.language_code) if client.language_code else "uz"

    # Partner mask only - these reminders go straight to the client, so the
    # real flight name must not appear in them.  Every flight rendered below is
    # the ``reys`` of this client's own transaction rows, so a missing alias is
    # minted rather than rendered as a placeholder.
    display = await FlightDisplay.for_client(
        session, client.active_codes, mint_missing=True
    )

    message_parts: list[str] = []
    for tx, days in reminders:
        display_flight = await display.label(session, tx.reys)

        total = float(tx.total_amount) if tx.total_amount else float(tx.summa or 0)
        paid = float(tx.paid_amount) if tx.paid_amount else 0.0
        remaining = float(tx.remaining_amount) if tx.remaining_amount else 0.0
        deadline = tx.payment_deadline.strftime("%Y-%m-%d") if tx.payment_deadline else "N/A"

        if days == 0:
            reminder_text = i18n.get(language, "reminder-partial-deadline-today",
                flight=display_flight,
                total=f"{total:,.0f}",
                paid=f"{paid:,.0f}",
                remaining=f"{remaining:,.0f}",
                deadline=deadline
            )
        elif days == 2:
            reminder_text = i18n.get(language, "reminder-partial-deadline-2days",
                flight=display_flight,
                total=f"{total:,.0f}",
                paid=f"{paid:,.0f}",
                remaining=f"{remaining:,.0f}",
                deadline=deadline,
                days=days
            )
        else:  # 5 days
            reminder_text = i18n.get(language, "reminder-partial-deadline-5days",
                flight=display_flight,
                total=f"{total:,.0f}",
                paid=f"{paid:,.0f}",
                remaining=f"{remaining:,.0f}",
                deadline=deadline,
                days=days
            )

        message_parts.append(reminder_text)

    return OutgoingMessage(
        chat_id=client.telegram_id,
        client_id=client.id,
        client_code=client.client_code,
        text="\n\n".join(message_parts),
        title="Payment Reminder",
        notif_type="payment",
    )


def _render_leftover_notification(
    client_code: str, client: Client, counts: dict[str, int]
) -> OutgoingMessage:
    """Build the leftover-cargo message for one client code."""
    language = get_user_language(client.language_code) if client.language_code else "uz"

    greeting = i18n.get(language, "notification-leftover-greeting")
    explanation = i18n.get(language, "notification-leftover-explanation")
    paid_text = i18n.get(
        language,
        "notification-leftover-paid-count",
        count=counts['paid']
    )
    unpaid_text = i18n.get(
        language,
        "notification-leftover-unpaid-count",
        count=counts['unpaid']
    )
    call_to_action = i18n.get(language, "notification-leftover-call-to-action")

    message_text = (
        f"{greeting}\n\n"
        f"{explanation}\n\n"
        f"{paid_text}\n"
        f"{unpaid_text}\n\n"
        f"{call_to_action}"
    )

    return OutgoingMessage(
        chat_id=client.telegram_id,
        client_id=client.id,
        client_code=client_code,
        text=message_text,
        title=i18n.get('uz', 'notification-leftover-greeting'),
        notif_type='cargo',
        parse_mode='HTML',
    )


async def send_partial_payment_reminders(bot: Bot):
    """
    Send automatic reminders for partial payments.
    
    Sends reminders when:
    - 5 days left until deadline
    - 2 days left until deadline
    - 0 days left (last day)
    
    Args:
        bot: Bot instance for sending messages
    """
    logger.info("Starting partial payment reminder notifications")
    
    if not bot:
        logger.error("Bot instance not available for reminders")
        return
    
    async with DatabaseClient(config.database.database_url) as db_client:
        async for session in db_client.get_session():
            try:
                from sqlalchemy import select
                from datetime import timezone
                
                # Get all partial payments with deadlines
                from src.infrastructure.tools.datetime_utils import get_current_time
                now = get_current_time()
                result = await session.execute(
                    select(ClientTransaction)
                    .where(
                        ClientTransaction.payment_status == "partial",
                        ClientTransaction.remaining_amount > 0,
                        ClientTransaction.payment_deadline.isnot(None),
                        ClientTransaction.telegram_id.isnot(None)
                    )
                )
                partial_transactions = list(result.scalars().all())
                
                if not partial_transactions:
                    logger.info("No partial payments found for reminders")
                    return
                
                logger.info(f"Found {len(partial_transactions)} partial payments to check")
                
                # Group by telegram_id to send one message per client
                clients_to_notify = {}
                
                for tx in partial_transactions:
                    if not tx.payment_deadline or not tx.telegram_id:
                        continue
                    
                    # Calculate days remaining (ensure both are timezone-aware)
                    if tx.payment_deadline.tzinfo is None:
                        # If deadline is naive, assume UTC
                        deadline_utc = tx.payment_deadline.replace(tzinfo=timezone.utc)
                    else:
                        deadline_utc = tx.payment_deadline
                    
                    days_remaining = (deadline_utc - now).days
                    
                    # Check if we should send reminder (5, 2, or 0 days left)
                    if days_remaining not in [5, 2, 0]:
                        continue
                    
                    # Get client for language
                    client = await ClientDAO.get_by_telegram_id(session, tx.telegram_id)
                    if not client:
                        continue
                    
                    # Use client_code as key to group multiple transactions
                    client_key = tx.telegram_id
                    
                    if client_key not in clients_to_notify:
                        clients_to_notify[client_key] = {
                            'client': client,
                            'transactions': []
                        }
                    
                    clients_to_notify[client_key]['transactions'].append((tx, days_remaining))
                
                if not clients_to_notify:
                    logger.info("No clients need reminders at this time")
                    return
                
                logger.info(f"Sending reminders to {len(clients_to_notify)} clients")

                sent_count = 0
                blocked_count = 0
                error_count = 0

                # Phase 1: render every reminder, masks included, on the session.
                # Only this phase and the persist phase may use the session.
                messages: list[OutgoingMessage] = []
                for client_data in clients_to_notify.values():
                    client = client_data['client']
                    try:
                        # A savepoint per client: a database error rolls back only
                        # this render.  session.rollback() would expire every client
                        # and transaction loaded above, and AsyncSession cannot
                        # lazy-load them back for the next render.
                        async with session.begin_nested():
                            message = await _render_partial_payment_reminder(
                                session, client, client_data['transactions']
                            )
                        messages.append(message)
                    except Exception as e:
                        error_count += 1
                        logger.error(f"Error sending reminder to {client.telegram_id}: {e}", exc_info=True)

                # Phase 2: send concurrently (with semaphore limiting), bot only
                async def send_reminder(message: OutgoingMessage) -> bool:
                    nonlocal sent_count, blocked_count, error_count

                    async with SEND_SEMAPHORE:
                        try:
                            try:
                                await _send_message(bot, message)
                            except TelegramRetryAfter as e:
                                logger.warning(f"Rate limited, waiting {e.retry_after} seconds")
                                await asyncio.sleep(e.retry_after)
                                # Retry once, inside the slot this task already holds
                                await _send_message(bot, message)
                        except TelegramForbiddenError:
                            blocked_count += 1
                            logger.warning(f"User {message.chat_id} blocked the bot")
                            return False
                        except Exception as e:
                            error_count += 1
                            logger.error(f"Error sending reminder to {message.chat_id}: {e}", exc_info=True)
                            return False

                    sent_count += 1
                    logger.info(f"Sent partial payment reminder to {message.chat_id} ({message.client_code})")
                    return True

                results = await asyncio.gather(*(send_reminder(message) for message in messages))

                # Phase 3: persist the successful sends, one at a time
                await _persist_sent_messages(
                    session,
                    [message for message, sent in zip(messages, results, strict=True) if sent],
                )

                logger.info(
                    f"Partial payment reminders completed: "
                    f"sent={sent_count}, blocked={blocked_count}, errors={error_count}"
                )
                
            except Exception as e:
                logger.error(f"Error in send_partial_payment_reminders: {e}", exc_info=True)
            # Not in ``finally``: a break there would swallow CancelledError.
            break


async def send_leftover_notifications(bot: Bot):
    """
    Send notifications to clients with leftover cargo.
    
    This function:
    1. Collects leftover cargo data (paid not taken, unpaid not taken)
    2. Groups by client_code
    3. Sends one notification per client with rate limiting
    4. Handles errors gracefully
    
    Args:
        bot: Bot instance for sending messages
    """
    logger.info("Starting leftover cargo notifications")
    
    if not bot:
        logger.error("Bot instance not available for notifications")
        return
    
    async with DatabaseClient(config.database.database_url) as db_client:
        async for session in db_client.get_session():
            try:
                # Get all leftover data using same logic as calculate_leftover_statistics
                all_transactions = await get_all_transactions(session)
                all_sent_cargos = await get_all_sent_flight_cargos(session)
                all_used_items = await get_all_used_cargo_items(session)
                
                # A) PAID BUT NOT TAKEN AWAY
                paid_not_taken_away = [
                    t for t in all_transactions
                    if t.is_taken_away == False
                ]
                
                # B) UNPAID AND NOT TAKEN AWAY
                unpaid_not_taken_away = []
                
                # Check flight_cargos
                for cargo in all_sent_cargos:
                    transaction = await check_transaction_exists(
                        all_transactions,
                        cargo.client_id,
                        cargo.flight_name
                    )
                    if not transaction:
                        unpaid_not_taken_away.append({
                            'client_code': cargo.client_id,
                            'flight_name': cargo.flight_name,
                        })
                
                # Check cargo_items
                for item in all_used_items:
                    if item.client_id and item.flight_name:
                        transaction = await check_transaction_exists(
                            all_transactions,
                            item.client_id,
                            item.flight_name
                        )
                        if not transaction:
                            unpaid_not_taken_away.append({
                                'client_code': item.client_id,
                                'flight_name': item.flight_name,
                            })
                
                # Group by client_code
                client_leftovers = defaultdict(lambda: {'paid': 0, 'unpaid': 0})
                
                for t in paid_not_taken_away:
                    client_leftovers[t.client_code]['paid'] += 1
                
                for item in unpaid_not_taken_away:
                    client_code = item.get('client_code')
                    if client_code:
                        client_leftovers[client_code]['unpaid'] += 1
                
                # Get unique client codes
                client_codes = list(client_leftovers.keys())
                
                if not client_codes:
                    logger.info("No leftover cargo found, skipping notifications")
                    return
                
                logger.info(f"Found {len(client_codes)} clients with leftover cargo")
                
                sent_count = 0
                skipped_count = 0
                blocked_count = 0
                error_count = 0

                # Phase 1: resolve each client and render its message on the session.
                # Only this phase and the persist phase may use the session.
                messages: list[OutgoingMessage] = []
                for code in client_codes:
                    try:
                        # A savepoint per code, as in the partial-payment render
                        # phase: a database error rolls back only this lookup
                        # instead of aborting the transaction for every later one.
                        async with session.begin_nested():
                            client = await ClientDAO.get_by_client_code(session, code)
                        if not client or not client.telegram_id:
                            skipped_count += 1
                            continue
                        messages.append(
                            _render_leftover_notification(code, client, client_leftovers[code])
                        )
                    except Exception as e:
                        error_count += 1
                        logger.error(
                            f"Error preparing leftover notification for {code}: {e}",
                            exc_info=True,
                        )

                # Phase 2: send concurrently (with semaphore limiting), bot only
                async def send_to_client(message: OutgoingMessage) -> bool:
                    nonlocal sent_count, blocked_count, error_count

                    async with SEND_SEMAPHORE:
                        try:
                            await _send_message(bot, message)
                        except TelegramForbiddenError:
                            blocked_count += 1
                            logger.debug(f"Client {message.client_code} blocked the bot")
                            return False
                        except TelegramRetryAfter as e:
                            # Wait and retry once, inside the slot this task already holds
                            await asyncio.sleep(e.retry_after + 1)
                            try:
                                await _send_message(bot, message)
                            except Exception as retry_error:
                                error_count += 1
                                logger.warning(f"Failed to send notification to {message.client_code} after retry: {retry_error}")
                                return False
                        except Exception as e:
                            error_count += 1
                            logger.warning(f"Error sending notification to {message.client_code}: {e}")
                            return False
                        finally:
                            # Small delay between sends to avoid rate limits
                            await asyncio.sleep(0.1)

                    sent_count += 1
                    logger.debug(f"Notification sent to client {message.client_code} (telegram_id: {message.chat_id})")
                    return True

                results = await asyncio.gather(*(send_to_client(message) for message in messages))

                # Phase 3: persist the successful sends, one at a time
                await _persist_sent_messages(
                    session,
                    [message for message, sent in zip(messages, results, strict=True) if sent],
                )
                
                # Log summary
                logger.info(
                    f"Leftover cargo notifications completed: "
                    f"sent={sent_count}, skipped={skipped_count}, "
                    f"blocked={blocked_count}, errors={error_count}"
                )
                
            except Exception as e:
                logger.error(f"Error in send_leftover_notifications: {e}", exc_info=True)
            # Not in ``finally``: a break there would swallow CancelledError.
            break


async def _read_notification_period_days(db_client: DatabaseClient) -> int | None:
    """Return the leftover-notification period in days, or ``None`` when it is off.

    ``None`` stands for a missing settings row, disabled notifications, or a
    period outside 1-15 days.  The session is closed before this returns, so no
    pooled connection sits idle in a transaction while the scheduler sleeps.
    """
    async with aclosing(db_client.get_session()) as sessions:
        session = await anext(sessions)
        static_data = await StaticDataDAO.get_first(session)
        if not static_data or not static_data.notification:
            return None
        period_days = static_data.notification_period

    if not period_days or period_days < 1 or period_days > 15:
        return None
    return period_days


async def _notification_scheduler_sleep(seconds: int) -> None:
    """Sleep for ``seconds``; log a cancellation that arrives meanwhile and re-raise it."""
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        logger.info("Notification scheduler cancelled during sleep")
        raise


async def notification_scheduler_task(bot: Bot):
    """
    Background task that runs notification scheduler.

    This task:
    1. Checks static_data.notification
    2. If enabled, sleeps for notification_period days
    3. Calls send_leftover_notifications()
    4. Repeats

    Each iteration opens a session only to read the settings and closes it
    before sleeping: a session held through a sleep of up to 15 days would pin
    a pooled connection idle in a transaction, which PostgreSQL may terminate.

    Args:
        bot: Bot instance (required for notifications)
    """
    async with DatabaseClient(config.database.database_url) as db_client:
        try:
            while True:
                try:
                    period_days = await _read_notification_period_days(db_client)
                    if period_days is None:
                        await _notification_scheduler_sleep(NOTIFICATION_RECHECK_SECONDS)
                        continue

                    logger.info(f"Notification scheduler: sleeping for {period_days} days")
                    await _notification_scheduler_sleep(period_days * 24 * 60 * 60)

                    logger.info("Notification period elapsed, triggering notifications")
                    await send_leftover_notifications(bot)
                except Exception as e:
                    logger.error(f"Error in notification scheduler loop: {e}", exc_info=True)
                    await _notification_scheduler_sleep(NOTIFICATION_RECHECK_SECONDS)
        except asyncio.CancelledError:
            logger.info("Notification scheduler stopped")
            raise


async def partial_payment_reminder_scheduler_task(bot: Bot):
    """
    Background task that runs partial payment reminder scheduler daily.
    
    This task:
    1. Runs once per day (every 24 hours)
    2. Calls send_partial_payment_reminders()
    3. Repeats
    
    Args:
        bot: Bot instance (required for reminders)
    """
    try:
        while True:
            try:
                # Run reminders check
                logger.info("Running partial payment reminder check")
                await send_partial_payment_reminders(bot)
                
                # Sleep for 24 hours (86400 seconds)
                logger.info("Partial payment reminder scheduler: sleeping for 24 hours")
                try:
                    await asyncio.sleep(86400)  # 24 hours
                except asyncio.CancelledError:
                    logger.info("Partial payment reminder scheduler cancelled during sleep")
                    raise
                    
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error in partial payment reminder scheduler: {e}", exc_info=True)
                try:
                    await asyncio.sleep(3600)  # Wait 1 hour on error
                except asyncio.CancelledError:
                    logger.info("Partial payment reminder scheduler cancelled during error sleep")
                    raise
                    
    except asyncio.CancelledError:
        logger.info("Partial payment reminder scheduler stopped")
        raise


def start_notification_scheduler(bot: Bot):
    """
    Start the notification scheduler as a background task.
    
    Args:
        bot: Bot instance
    """
    global notification_task, partial_payment_reminder_task
    
    logger.info("Starting notification scheduler")
    notification_task = asyncio.create_task(notification_scheduler_task(bot))
    
    logger.info("Starting partial payment reminder scheduler")
    partial_payment_reminder_task = asyncio.create_task(partial_payment_reminder_scheduler_task(bot))


async def stop_notification_scheduler():
    """
    Stop the notification scheduler gracefully.
    
    Cancels the background task and waits for it to finish.
    """
    global notification_task, partial_payment_reminder_task
    
    if notification_task and not notification_task.done():
        logger.info("Stopping notification scheduler...")
        notification_task.cancel()
        try:
            await notification_task
        except asyncio.CancelledError:
            logger.info("Notification scheduler stopped successfully")
        except Exception as e:
            logger.warning(f"Error while stopping notification scheduler: {e}")
        finally:
            notification_task = None
    
    if partial_payment_reminder_task and not partial_payment_reminder_task.done():
        logger.info("Stopping partial payment reminder scheduler...")
        partial_payment_reminder_task.cancel()
        try:
            await partial_payment_reminder_task
        except asyncio.CancelledError:
            logger.info("Partial payment reminder scheduler stopped successfully")
        except Exception as e:
            logger.warning(f"Error while stopping partial payment reminder scheduler: {e}")
        finally:
            partial_payment_reminder_task = None

