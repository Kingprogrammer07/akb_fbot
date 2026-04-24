"""Statistics aggregation service."""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Dict
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.stats_daily_clients import StatsDailyClientsDAO
from src.infrastructure.database.dao.stats_daily_cargo import StatsDailyCargoDAO
from src.infrastructure.database.dao.stats_daily_payments import StatsDailyPaymentsDAO
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.analytics_event import AnalyticsEvent
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.client_payment_event import ClientPaymentEvent
from src.infrastructure.database.models.client_transaction import ClientTransaction

logger = logging.getLogger(__name__)


class StatsAggregationService:
    """Service for aggregating statistics into daily tables."""

    @staticmethod
    async def aggregate_daily_clients(
        session: AsyncSession,
        target_date: date
    ) -> None:
        """
        Aggregate client statistics for a specific date.
        
        Calculates:
        - Number of client registrations on this date
        - Number of client approvals on this date
        - Number of client logins on this date
        - Total active clients (with client_code) as of this date
        
        NOTE: Does NOT commit - caller must commit transaction.
        """
        # Get registrations count from analytics_events
        # Convert business date (Tashkent calendar) to UTC datetime range for query
        # Database stores UTC timestamps, but business logic uses Tashkent dates
        from src.infrastructure.tools.datetime_utils import tashkent_date_to_utc_range
        start_datetime, end_datetime = tashkent_date_to_utc_range(target_date)
        
        registrations_result = await session.execute(
            select(func.count(AnalyticsEvent.id))
            .where(
                and_(
                    AnalyticsEvent.event_type == 'client_registration',
                    AnalyticsEvent.created_at >= start_datetime,
                    AnalyticsEvent.created_at <= end_datetime
                )
            )
        )
        registrations_count = registrations_result.scalar_one() or 0

        # Get approvals count from analytics_events
        # Use same Tashkent timezone boundaries for consistency
        approvals_result = await session.execute(
            select(func.count(AnalyticsEvent.id))
            .where(
                and_(
                    AnalyticsEvent.event_type == 'client_approval',
                    AnalyticsEvent.created_at >= start_datetime,
                    AnalyticsEvent.created_at <= end_datetime
                )
            )
        )
        approvals_count = approvals_result.scalar_one() or 0

        # Get logins count from analytics_events (if we track them)
        # For now, we'll use client.is_logged_in updates, but we can add login events later
        logins_count = 0  # TODO: Add login event tracking if needed

        # Get total active clients (with client_code) as of this date
        # Use end of business day in UTC (from Tashkent date)
        _, end_of_day = tashkent_date_to_utc_range(target_date)
        active_clients_result = await session.execute(
            select(func.count(Client.id))
            .where(
                and_(
                    Client.client_code.isnot(None),
                    Client.created_at <= end_of_day
                )
            )
        )
        active_clients_count = active_clients_result.scalar_one() or 0

        # Upsert statistics (no commit - caller handles transaction)
        await StatsDailyClientsDAO.upsert(
            session=session,
            stat_date=target_date,
            registrations_count=registrations_count,
            approvals_count=approvals_count,
            logins_count=logins_count,
            active_clients_count=active_clients_count
        )
        logger.debug(f"Aggregated daily client stats for {target_date}")

    @staticmethod
    async def aggregate_daily_cargo(
        session: AsyncSession,
        target_date: date,
        flight_name: Optional[str] = None
    ) -> None:
        """
        Aggregate cargo statistics for a specific date and optionally flight.
        
        Calculates:
        - Number of cargo uploads
        - Number of unique clients
        - Total photos uploaded (parsed from JSON)
        - Total weight and average weight
        
        NOTE: Does NOT commit - caller must commit transaction.
        """
        # Build date filter: convert business date (Tashkent) to UTC datetime range
        from src.infrastructure.tools.datetime_utils import tashkent_date_to_utc_range
        start_datetime, end_datetime = tashkent_date_to_utc_range(target_date)
        
        conditions = [
            FlightCargo.created_at >= start_datetime,
            FlightCargo.created_at <= end_datetime
        ]
        
        if flight_name:
            conditions.append(FlightCargo.flight_name == flight_name)

        # Get all cargo records for this date to parse photo counts
        cargos_result = await session.execute(
            select(FlightCargo)
            .where(and_(*conditions))
        )
        cargos = list(cargos_result.scalars().all())

        # Calculate statistics
        uploads_count = len(cargos)
        
        # Count unique clients
        unique_client_ids = set(cargo.client_id for cargo in cargos if cargo.client_id)
        unique_clients_count = len(unique_client_ids)
        
        # Parse photo_file_ids JSON and count total photos
        total_photos_count = 0
        for cargo in cargos:
            if cargo.photo_file_ids:
                try:
                    # Parse JSON array of file_ids
                    photo_ids = json.loads(cargo.photo_file_ids)
                    if isinstance(photo_ids, list):
                        total_photos_count += len(photo_ids)
                    elif isinstance(photo_ids, str):
                        # Single file_id stored as string (legacy format)
                        total_photos_count += 1
                except (json.JSONDecodeError, TypeError):
                    # Invalid JSON - treat as single photo (legacy format)
                    total_photos_count += 1

        # Calculate total and average weight (only from non-NULL values)
        weights = [float(cargo.weight_kg) for cargo in cargos if cargo.weight_kg is not None]
        total_weight_kg = sum(weights) if weights else None
        avg_weight_kg = (sum(weights) / len(weights)) if weights else None

        # Convert to Decimal for storage (model expects Numeric)
        total_weight_decimal = Decimal(str(total_weight_kg)) if total_weight_kg is not None else None
        avg_weight_decimal = Decimal(str(avg_weight_kg)) if avg_weight_kg is not None else None

        # Upsert statistics (no commit - caller handles transaction)
        await StatsDailyCargoDAO.upsert(
            session=session,
            stat_date=target_date,
            uploads_count=uploads_count,
            unique_clients_count=unique_clients_count,
            total_photos_count=total_photos_count,
            total_weight_kg=float(total_weight_decimal) if total_weight_decimal else None,
            avg_weight_kg=float(avg_weight_decimal) if avg_weight_decimal else None,
            flight_name=flight_name
        )
        logger.debug(f"Aggregated daily cargo stats for {target_date}, flight={flight_name}")

    @staticmethod
    async def aggregate_daily_payments(
        session: AsyncSession,
        target_date: date,
        payment_type: Optional[str] = None
    ) -> None:
        """
        Aggregate payment statistics for a specific date and optionally payment type.
        
        SOURCE OF TRUTH: client_payment_events ONLY
        - approvals_count = COUNT(client_payment_events) for the date
        - total_amount = SUM(client_payment_events.amount)
        - Full vs Partial: Group by transaction_id, compare sum(events.amount) to transaction.total_amount
        
        NOTE: Does NOT commit - caller must commit transaction.
        """
        # Build date filter: convert business date (Tashkent) to UTC datetime range
        from src.infrastructure.tools.datetime_utils import tashkent_date_to_utc_range
        start_datetime, end_datetime = tashkent_date_to_utc_range(target_date)
        
        # Filter payment events by date and optionally payment_type
        payment_conditions = [
            ClientPaymentEvent.created_at >= start_datetime,
            ClientPaymentEvent.created_at <= end_datetime
        ]
        
        if payment_type:
            payment_conditions.append(ClientPaymentEvent.payment_type == payment_type)

        # Get all payment events for this date (SOURCE OF TRUTH)
        payment_events_result = await session.execute(
            select(ClientPaymentEvent)
            .where(and_(*payment_conditions))
        )
        payment_events = list(payment_events_result.scalars().all())

        # Basic counts and totals from events
        approvals_count = len(payment_events)
        total_amount = sum(Decimal(str(event.amount)) for event in payment_events)
        
        # Calculate average (safe division)
        avg_amount = (total_amount / approvals_count) if approvals_count > 0 else None

        # Group events by transaction_id to determine full vs partial
        # Full payment: sum(events.amount) >= transaction.total_amount
        # Partial payment: sum(events.amount) < transaction.total_amount
        transaction_totals: Dict[int, Decimal] = {}  # transaction_id -> total_paid
        transaction_amounts: Dict[int, Decimal] = {}  # transaction_id -> transaction.total_amount
        
        # Get all unique transaction_ids from events
        transaction_ids = list(set(event.transaction_id for event in payment_events))
        
        if transaction_ids:
            # Fetch transaction records to get total_amount
            transactions_result = await session.execute(
                select(ClientTransaction)
                .where(ClientTransaction.id.in_(transaction_ids))
            )
            transactions = {tx.id: tx for tx in transactions_result.scalars().all()}
            
            # Calculate total paid per transaction from events
            for event in payment_events:
                tx_id = event.transaction_id
                amount = Decimal(str(event.amount))
                transaction_totals[tx_id] = transaction_totals.get(tx_id, Decimal('0')) + amount
                
                # Store transaction total_amount if not already stored
                if tx_id not in transaction_amounts:
                    tx = transactions.get(tx_id)
                    if tx and tx.total_amount is not None:
                        transaction_amounts[tx_id] = Decimal(str(tx.total_amount))
                    else:
                        # If transaction.total_amount is NULL, use summa as fallback
                        # This handles legacy data where total_amount might not be set
                        if tx and tx.summa is not None:
                            transaction_amounts[tx_id] = Decimal(str(tx.summa))
                        else:
                            # No total available - cannot determine full/partial
                            transaction_amounts[tx_id] = None

        # Classify transactions as full or partial
        # First, determine classification for each transaction
        transaction_classification: Dict[int, bool] = {}  # transaction_id -> is_full
        
        for tx_id in transaction_totals.keys():
            total_paid = transaction_totals.get(tx_id, Decimal('0'))
            transaction_total = transaction_amounts.get(tx_id)
            
            # Determine if full or partial
            if transaction_total is not None:
                # Compare total_paid to transaction_total
                # Use >= to handle rounding differences (if paid >= required, it's full)
                is_full = total_paid >= transaction_total
            else:
                # Cannot determine - treat as partial (conservative approach)
                is_full = False
            
            transaction_classification[tx_id] = is_full
        
        # Count transactions and sum amounts from events
        full_payments_count = sum(1 for is_full in transaction_classification.values() if is_full)
        partial_payments_count = sum(1 for is_full in transaction_classification.values() if not is_full)
        
        # Sum amounts from events, grouped by transaction classification
        full_payments_amount = Decimal('0')
        partial_payments_amount = Decimal('0')
        
        for event in payment_events:
            tx_id = event.transaction_id
            amount = Decimal(str(event.amount))
            is_full = transaction_classification.get(tx_id, False)
            
            if is_full:
                full_payments_amount += amount
            else:
                partial_payments_amount += amount

        # Convert Decimal to float for storage (model expects Numeric which stores as float)
        total_amount_float = float(total_amount)
        full_payments_amount_float = float(full_payments_amount)
        partial_payments_amount_float = float(partial_payments_amount)
        avg_amount_float = float(avg_amount) if avg_amount is not None else None

        # Upsert statistics (no commit - caller handles transaction)
        await StatsDailyPaymentsDAO.upsert(
            session=session,
            stat_date=target_date,
            approvals_count=approvals_count,
            total_amount=total_amount_float,
            full_payments_count=full_payments_count,
            partial_payments_count=partial_payments_count,
            full_payments_amount=full_payments_amount_float,
            partial_payments_amount=partial_payments_amount_float,
            avg_amount=avg_amount_float,
            payment_type=payment_type
        )
        logger.debug(f"Aggregated daily payment stats for {target_date}, type={payment_type}")

    @staticmethod
    async def aggregate_all_for_date(
        session: AsyncSession,
        target_date: date
    ) -> None:
        """
        Aggregate all statistics for a specific date.
        
        Wraps all aggregations in a single database transaction.
        All sub-functions do NOT commit - this function handles the transaction.
        
        Transaction flow:
        BEGIN
          aggregate_daily_clients
          aggregate_daily_cargo (overall + per flight)
          aggregate_daily_payments (overall + per type)
        COMMIT
        
        On any failure, rolls back completely.
        """
        try:
            # Aggregate clients
            await StatsAggregationService.aggregate_daily_clients(session, target_date)
            
            # Aggregate cargo (overall - flight_name = NULL)
            await StatsAggregationService.aggregate_daily_cargo(session, target_date, flight_name=None)
            
            # Aggregate cargo per flight (get distinct flights for this date)
            # Convert business date (Tashkent) to UTC datetime range
            from src.infrastructure.tools.datetime_utils import tashkent_date_to_utc_range
            start_datetime, end_datetime = tashkent_date_to_utc_range(target_date)
            
            flights_result = await session.execute(
                select(func.distinct(FlightCargo.flight_name))
                .where(
                    and_(
                        FlightCargo.created_at >= start_datetime,
                        FlightCargo.created_at <= end_datetime
                    )
                )
            )
            flights = [row[0] for row in flights_result.fetchall() if row[0]]
            
            for flight_name in flights:
                await StatsAggregationService.aggregate_daily_cargo(session, target_date, flight_name=flight_name)
            
            # Aggregate payments (overall - payment_type = NULL)
            await StatsAggregationService.aggregate_daily_payments(session, target_date, payment_type=None)
            
            # Aggregate payments by type
            await StatsAggregationService.aggregate_daily_payments(session, target_date, payment_type='online')
            await StatsAggregationService.aggregate_daily_payments(session, target_date, payment_type='cash')
            
            # Commit all aggregations in single transaction
            await session.commit()
            logger.info(f"Completed aggregation for all stats on {target_date}")

        except Exception as e:
            # Rollback entire transaction on any failure
            await session.rollback()
            logger.error(f"Failed to aggregate all stats for {target_date}: {e}", exc_info=True)
            raise

    @staticmethod
    async def aggregate_date_range(
        session: AsyncSession,
        start_date: date,
        end_date: date
    ) -> None:
        """
        Aggregate statistics for a date range.
        
        Processes each date in the range sequentially.
        Each date is processed in its own transaction (via aggregate_all_for_date).
        """
        current_date = start_date
        while current_date <= end_date:
            try:
                await StatsAggregationService.aggregate_all_for_date(session, current_date)
            except Exception as e:
                logger.error(f"Failed to aggregate stats for {current_date}: {e}")
                # Continue with next date even if one fails
            current_date += timedelta(days=1)
