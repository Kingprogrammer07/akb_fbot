"""Background notification scheduler for leftover cargo."""
import asyncio
import logging
from collections import defaultdict
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.cargo_item import CargoItem
from src.bot.utils.i18n import i18n, get_user_language
from src.config import config
from src.infrastructure.database.dao.notification import NotificationDAO

logger = logging.getLogger(__name__)

# Rate limiting: max 10 concurrent sends
SEND_SEMAPHORE = asyncio.Semaphore(10)

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
                from datetime import datetime, timezone, timedelta
                
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
                    
                    clients_to_notify[client_key]['transactions'].append({
                        'tx': tx,
                        'days_remaining': days_remaining
                    })
                
                if not clients_to_notify:
                    logger.info("No clients need reminders at this time")
                    return
                
                logger.info(f"Sending reminders to {len(clients_to_notify)} clients")
                
                # Send notifications with rate limiting
                sent_count = 0
                skipped_count = 0
                blocked_count = 0
                error_count = 0
                
                async def send_reminder(client_data: dict):
                    nonlocal sent_count, skipped_count, blocked_count, error_count
                    
                    async with SEND_SEMAPHORE:
                        try:
                            client = client_data['client']
                            transactions = client_data['transactions']
                            
                            # Get language
                            language = get_user_language(client.language_code) if client.language_code else "uz"
                            
                            # Build message for all transactions
                            message_parts = []
                            
                            for item in transactions:
                                tx = item['tx']
                                days = item['days_remaining']
                                
                                total = float(tx.total_amount) if tx.total_amount else float(tx.summa or 0)
                                paid = float(tx.paid_amount) if tx.paid_amount else 0.0
                                remaining = float(tx.remaining_amount) if tx.remaining_amount else 0.0
                                deadline = tx.payment_deadline.strftime("%Y-%m-%d") if tx.payment_deadline else "N/A"
                                
                                if days == 0:
                                    reminder_text = i18n.get(language, "reminder-partial-deadline-today",
                                        flight=tx.reys,
                                        total=f"{total:,.0f}",
                                        paid=f"{paid:,.0f}",
                                        remaining=f"{remaining:,.0f}",
                                        deadline=deadline
                                    )
                                elif days == 2:
                                    reminder_text = i18n.get(language, "reminder-partial-deadline-2days",
                                        flight=tx.reys,
                                        total=f"{total:,.0f}",
                                        paid=f"{paid:,.0f}",
                                        remaining=f"{remaining:,.0f}",
                                        deadline=deadline,
                                        days=days
                                    )
                                else:  # 5 days
                                    reminder_text = i18n.get(language, "reminder-partial-deadline-5days",
                                        flight=tx.reys,
                                        total=f"{total:,.0f}",
                                        paid=f"{paid:,.0f}",
                                        remaining=f"{remaining:,.0f}",
                                        deadline=deadline,
                                        days=days
                                    )
                                
                                message_parts.append(reminder_text)
                            
                            # Send combined message
                            full_message = "\n\n".join(message_parts)
                            
                            await bot.send_message(
                                chat_id=client.telegram_id,
                                text=full_message
                            )
                            
                            sent_count += 1
                            logger.info(f"Sent partial payment reminder to {client.telegram_id} ({client.client_code})")
                            
                            # Persist notification to DB for WebApp
                            await persist_notification(
                                session=session,
                                client_id=client.id,
                                title="Payment Reminder",
                                body=full_message,
                                notif_type='payment',
                            )
                            
                        except TelegramForbiddenError:
                            blocked_count += 1
                            logger.warning(f"User {client_data['client'].telegram_id} blocked the bot")
                        except TelegramRetryAfter as e:
                            logger.warning(f"Rate limited, waiting {e.retry_after} seconds")
                            await asyncio.sleep(e.retry_after)
                            # Retry once
                            try:
                                await send_reminder(client_data)
                            except Exception as retry_e:
                                error_count += 1
                                logger.error(f"Error retrying reminder: {retry_e}")
                        except Exception as e:
                            error_count += 1
                            logger.error(f"Error sending reminder to {client_data['client'].telegram_id}: {e}", exc_info=True)
                
                # Send all reminders concurrently (with semaphore limiting)
                tasks = [send_reminder(data) for data in clients_to_notify.values()]
                await asyncio.gather(*tasks, return_exceptions=True)
                
                logger.info(
                    f"Partial payment reminders completed: "
                    f"sent={sent_count}, blocked={blocked_count}, errors={error_count}"
                )
                
            except Exception as e:
                logger.error(f"Error in send_partial_payment_reminders: {e}", exc_info=True)
            finally:
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
                
                # Fetch all clients at once
                clients_by_code = {}
                for code in client_codes:
                    client = await ClientDAO.get_by_client_code(session, code)
                    if client and client.telegram_id:
                        clients_by_code[code] = client
                
                # Send notifications with rate limiting
                sent_count = 0
                skipped_count = 0
                blocked_count = 0
                error_count = 0
                
                # Create tasks for sending (with semaphore for rate limiting)
                async def send_to_client(client_code: str, client, counts: dict):
                    nonlocal sent_count, skipped_count, blocked_count, error_count
                    
                    if not client or not client.telegram_id:
                        skipped_count += 1
                        return
                    
                    async with SEND_SEMAPHORE:
                        try:
                            # Get client language
                            language = get_user_language(client.language_code) if client.language_code else "uz"
                            
                            # Prepare message
                            paid_count = counts['paid']
                            unpaid_count = counts['unpaid']
                            
                            # Get translations
                            greeting = i18n.get(language, "notification-leftover-greeting")
                            explanation = i18n.get(language, "notification-leftover-explanation")
                            paid_text = i18n.get(
                                language,
                                "notification-leftover-paid-count",
                                count=paid_count
                            )
                            unpaid_text = i18n.get(
                                language,
                                "notification-leftover-unpaid-count",
                                count=unpaid_count
                            )
                            call_to_action = i18n.get(language, "notification-leftover-call-to-action")
                            
                            message_text = (
                                f"{greeting}\n\n"
                                f"{explanation}\n\n"
                                f"{paid_text}\n"
                                f"{unpaid_text}\n\n"
                                f"{call_to_action}"
                            )
                            
                            # Send message
                            await bot.send_message(
                                chat_id=client.telegram_id,
                                text=message_text,
                                parse_mode='HTML'
                            )
                            
                            sent_count += 1
                            logger.debug(f"Notification sent to client {client_code} (telegram_id: {client.telegram_id})")
                            
                            # Persist notification to DB for WebApp
                            await persist_notification(
                                session=session,
                                client_id=client.id,
                                title=i18n.get('uz', 'notification-leftover-greeting'),
                                body=message_text,
                                notif_type='cargo',
                            )
                            
                        except TelegramForbiddenError:
                            blocked_count += 1
                            logger.debug(f"Client {client_code} blocked the bot")
                        except TelegramRetryAfter as e:
                            # Wait and retry once
                            await asyncio.sleep(e.retry_after + 1)
                            try:
                                language = get_user_language(client.language_code) if client.language_code else "uz"
                                paid_count = counts['paid']
                                unpaid_count = counts['unpaid']
                                
                                greeting = i18n.get(language, "notification-leftover-greeting")
                                explanation = i18n.get(language, "notification-leftover-explanation")
                                paid_text = i18n.get(
                                    language,
                                    "notification-leftover-paid-count",
                                    count=paid_count
                                )
                                unpaid_text = i18n.get(
                                    language,
                                    "notification-leftover-unpaid-count",
                                    count=unpaid_count
                                )
                                call_to_action = i18n.get(language, "notification-leftover-call-to-action")
                                
                                message_text = (
                                    f"{greeting}\n\n"
                                    f"{explanation}\n\n"
                                    f"{paid_text}\n"
                                    f"{unpaid_text}\n\n"
                                    f"{call_to_action}"
                                )
                                
                                await bot.send_message(
                                    chat_id=client.telegram_id,
                                    text=message_text,
                                    parse_mode='HTML'
                                )
                                sent_count += 1
                            except Exception as retry_error:
                                error_count += 1
                                logger.warning(f"Failed to send notification to {client_code} after retry: {retry_error}")
                        except Exception as e:
                            error_count += 1
                            logger.warning(f"Error sending notification to {client_code}: {e}")
                        
                        # Small delay between sends to avoid rate limits
                        await asyncio.sleep(0.1)
                
                # Send notifications concurrently (with semaphore limiting)
                tasks = [
                    send_to_client(code, clients_by_code.get(code), client_leftovers[code])
                    for code in client_codes
                ]
                
                await asyncio.gather(*tasks, return_exceptions=True)
                
                # Log summary
                logger.info(
                    f"Leftover cargo notifications completed: "
                    f"sent={sent_count}, skipped={skipped_count}, "
                    f"blocked={blocked_count}, errors={error_count}"
                )
                
            except Exception as e:
                logger.error(f"Error in send_leftover_notifications: {e}", exc_info=True)
            finally:
                break


async def notification_scheduler_task(bot: Bot):
    """
    Background task that runs notification scheduler.
    
    This task:
    1. Checks static_data.notification
    2. If enabled, sleeps for notification_period days
    3. Calls send_leftover_notifications()
    4. Repeats
    
    Args:
        bot: Bot instance (required for notifications)
    """
    async with DatabaseClient(config.database.database_url) as db_client:
        try:
            while True:
                try:
                    async for session in db_client.get_session():
                        try:
                            # Get notification settings
                            static_data = await StaticDataDAO.get_first(session)
                            
                            if not static_data:
                                try:
                                    await asyncio.sleep(3600)
                                except asyncio.CancelledError:
                                    logger.info("Notification scheduler cancelled during sleep")
                                    raise
                                continue
                            
                            if not static_data.notification:
                                try:
                                    await asyncio.sleep(3600)
                                except asyncio.CancelledError:
                                    logger.info("Notification scheduler cancelled during sleep")
                                    raise
                                continue
                            
                            period_days = static_data.notification_period
                            if not period_days or period_days < 1 or period_days > 15:
                                try:
                                    await asyncio.sleep(3600)
                                except asyncio.CancelledError:
                                    logger.info("Notification scheduler cancelled during sleep")
                                    raise
                                continue
                            
                            # Sleep for the specified period
                            sleep_seconds = period_days * 24 * 60 * 60
                            logger.info(f"Notification scheduler: sleeping for {period_days} days")
                            try:
                                await asyncio.sleep(sleep_seconds)
                            except asyncio.CancelledError:
                                logger.info("Notification scheduler cancelled during sleep")
                                raise
                            
                            # After sleep, trigger notification
                            logger.info("Notification period elapsed, triggering notifications")
                            await send_leftover_notifications(bot)
                            
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            logger.error(f"Error in notification scheduler loop: {e}", exc_info=True)
                            try:
                                await asyncio.sleep(3600)
                            except asyncio.CancelledError:
                                logger.info("Notification scheduler cancelled during sleep")
                                raise
                        finally:
                            break  # Exit inner loop to get new session
                            
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Error in notification scheduler: {e}", exc_info=True)
                    try:
                        await asyncio.sleep(3600)
                    except asyncio.CancelledError:
                        logger.info("Notification scheduler cancelled during sleep")
                        raise
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

