"""Admin leftover cargo handler."""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from io import BytesIO
from typing import Optional

import pandas as pd
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters import IsAdmin, IsPrivate
from src.bot.utils.decorators import handle_errors
from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.config import config
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.database.models.cargo_item import CargoItem
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.flight_cargo import FlightCargo

logger = logging.getLogger(__name__)
leftover_cargo_router = Router(name="admin_leftover_cargo")

# Statistics display limits
MAX_FLIGHTS_IN_STATS = 5
MAX_REGIONS_IN_STATS = 5



async def get_all_sent_flight_cargos(session: AsyncSession) -> list[FlightCargo]:
    """Get all flight cargos where is_sent = true."""
    result = await session.execute(
        select(FlightCargo)
        .where(FlightCargo.is_sent == True)
        .order_by(FlightCargo.flight_name, FlightCargo.client_id)
    )
    return list(result.scalars().all())


async def get_all_used_cargo_items(session: AsyncSession) -> list[CargoItem]:
    """Get all cargo items where is_used = true."""
    result = await session.execute(
        select(CargoItem)
        .where(CargoItem.is_used == True)
        .order_by(CargoItem.flight_name, CargoItem.client_id)
    )
    return list(result.scalars().all())


# Removed: get_all_transactions() - now using ClientTransactionDAO.get_all_transactions()
# This ensures UZPOST and WALLET_ADJ transactions are properly filtered



async def check_transaction_exists(
    transactions: list[ClientTransaction],
    client_code: str,
    flight_name: str,
    row_number: Optional[int] = None
) -> Optional[ClientTransaction]:
    """
    Check if a transaction exists matching the criteria.
    
    Matching logic:
    - client_code must match (case-insensitive)
    - reys (flight_name) must match (case-insensitive)
    - If row_number provided, qator_raqami must match
    - If row_number not provided, any transaction with matching client_code and flight_name is considered a match
    """
    if not client_code or not flight_name:
        return None
    
    for transaction in transactions:
        if (transaction.client_code.upper() == client_code.upper() and
            transaction.reys.upper() == flight_name.upper()):
            if row_number is not None:
                if transaction.qator_raqami == row_number:
                    return transaction
            else:
                # If no row_number specified, match by client_code and flight_name
                # This means if ANY transaction exists for this client+flight, it's considered paid
                return transaction
    return None


async def resolve_track_codes(
    session: AsyncSession,
    items: list[dict]
) -> None:
    """
    Resolve track_codes for leftover items using Google Sheets as the ONLY source.

    Modifies items in-place by adding/updating track_code field.

    Strategy:
    - Fetch ENTIRE flight sheet ONCE per flight (not per client)
    - Map data into memory, then assign track codes from cache
    - Fallback to find_client_group only for items without flight_name
    - If Google Sheets fails, continue with empty track_codes (no crash)

    Performance:
    - ONE API call per flight instead of one per client
    - Dramatically reduces 429 Too Many Requests errors
    """
    items_to_resolve = [
        i for i in items
        if (not i.get('track_code') or i.get('track_code') == '')
        and i.get('client_code')
    ]
    if not items_to_resolve:
        return

    # Group by flight_name
    flights_to_fetch = set(
        i['flight_name'].upper() for i in items_to_resolve if i.get('flight_name')
    )
    clients_without_flight = set(
        i['client_code'].upper() for i in items_to_resolve if not i.get('flight_name')
    )

    sheets_cache = {}
    try:
        sheets_checker = GoogleSheetsChecker(
            spreadsheet_id=config.google_sheets.SHEETS_ID,
            api_key=config.google_sheets.API_KEY,
        )

        # 1. Fetch entire flights in ONE API CALL PER FLIGHT
        for flight in flights_to_fetch:
            logger.info(f"Batch fetching entire flight sheet: {flight}")
            try:
                flight_clients = await sheets_checker.get_all_clients_in_flight(flight)
                for c_data in flight_clients:
                    sheets_cache[(flight, c_data['client_code'].upper())] = {
                        "track_codes": c_data['track_codes'],
                        "row_number": c_data['row_number']
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch flight {flight}: {e}")

        # 2. Fallback for clients without flight
        for client_code in clients_without_flight:
            try:
                result = await sheets_checker.find_client_group(client_code)
                if result.get("found") and result.get("matches"):
                    for match in result["matches"]:
                        f_name = match.get("flight_name", "").upper()
                        sheets_cache[(f_name, client_code)] = {
                            "track_codes": match.get("track_codes", []),
                            "row_number": match.get("row_number")
                        }
            except Exception as e:
                logger.warning(f"Failed fallback for {client_code}: {e}")

    except Exception as e:
        logger.warning(f"Sheets checker init failed: {e}")

    # Assign from cache
    for item in items_to_resolve:
        flight_name = item.get('flight_name', '').upper()
        client_code = item.get('client_code', '').upper()

        sheet_data = sheets_cache.get((flight_name, client_code))
        if not sheet_data:  # Try finding globally in cache if flight specific failed
            for (c_flight, c_code), data in sheets_cache.items():
                if c_code == client_code:
                    sheet_data = data
                    break

        if sheet_data and sheet_data.get("track_codes"):
            t_codes = sheet_data["track_codes"]
            item['track_code'] = ', '.join(t_codes) if isinstance(t_codes, list) else t_codes
            if not item.get("row_number"):
                item['row_number'] = sheet_data.get("row_number")


async def calculate_leftover_statistics(session: AsyncSession) -> dict:
    """
    Calculate leftover cargo statistics.
    
    Returns:
        dict with statistics including:
        - paid_not_taken_away: List of paid but not taken away transactions
        - unpaid_not_taken_away: List of unpaid leftover cargos
        - total_leftover: Total count
        - estimated_profit: Sum of paid but not taken away amounts
        - by_flight: Breakdown by flight_name
        - by_region: Breakdown by region (if available)
    """
    # Get all data
    all_transactions = await ClientTransactionDAO.get_all_transactions(session)
    all_sent_cargos = await get_all_sent_flight_cargos(session)
    all_used_items = await get_all_used_cargo_items(session)
    
    # A) PAID BUT NOT TAKEN AWAY
    # Exclude cash payments that are taken away (they should not appear in leftovers)
    paid_not_taken_away = [
        t for t in all_transactions
        if t.is_taken_away == False
        # Cash payments with is_taken_away=True are already handled, so we only need to check is_taken_away
    ]
    
    # B) UNPAID AND NOT TAKEN AWAY
    unpaid_not_taken_away = []
    
    # Check flight_cargos
    for cargo in all_sent_cargos:

        # Check if transaction exists for this cargo
        transaction = await check_transaction_exists(
            all_transactions,
            cargo.client_id,
            cargo.flight_name
        )

        if not transaction:
            # This is unpaid leftover
            unpaid_not_taken_away.append({
                'type': 'flight_cargo',
                'id': cargo.id,
                'client_code': cargo.client_id,
                'flight_name': cargo.flight_name,
                'row_number': None,
                'track_code': None,
                'source': 'flight_cargos'
            })
    # Check cargo_items
    for item in all_used_items:
        # Check if transaction exists for this item
        # For cargo_items, we match by client_id + flight_name
        # Note: cargo_items don't have row_number, so we match by client_code + flight_name only
        if item.client_id and item.flight_name:
            transaction = await check_transaction_exists(
                all_transactions,
                item.client_id,
                item.flight_name
            )
            if not transaction:
                # This is unpaid leftover
                unpaid_not_taken_away.append({
                    'type': 'cargo_item',
                    'id': item.id,
                    'client_code': item.client_id,
                    'flight_name': item.flight_name,
                    'row_number': None,
                    'track_code': item.track_code,
                    'source': 'cargo_items'
                })
    
    # NOTE: track_code resolution is done in background task for Excel generation
    # Statistics phase does NOT resolve track_codes to keep it fast
    
    # Calculate statistics
    total_paid_not_taken = len(paid_not_taken_away)
    total_unpaid_not_taken = len(unpaid_not_taken_away)
    total_leftover = total_paid_not_taken + total_unpaid_not_taken
    
    # Estimated profit (sum of paid but not taken away)
    estimated_profit = sum(float(t.summa) for t in paid_not_taken_away)
    
    # Breakdown by flight
    by_flight = defaultdict(lambda: {'paid': 0, 'unpaid': 0, 'total': 0})
    
    for t in paid_not_taken_away:
        by_flight[t.reys]['paid'] += 1
        by_flight[t.reys]['total'] += 1
    
    for item in unpaid_not_taken_away:
        flight = item.get('flight_name') or 'Unknown'
        by_flight[flight]['unpaid'] += 1
        by_flight[flight]['total'] += 1
    
    # Get client data for region breakdown
    by_region = defaultdict(lambda: {'paid': 0, 'unpaid': 0, 'total': 0})
    
    # Get unique client codes
    client_codes = set()
    for t in paid_not_taken_away:
        client_codes.add(t.client_code)
    for item in unpaid_not_taken_away:
        if item.get('client_code'):
            client_codes.add(item['client_code'])
    
    # Fetch client data for region
    clients_by_code = {}
    for code in client_codes:
        client = await ClientDAO.get_by_client_code(session, code)
        if client and client.region:
            clients_by_code[code] = client.region
    
    # Count by region
    for t in paid_not_taken_away:
        region = clients_by_code.get(t.client_code) or 'Unknown'
        by_region[region]['paid'] += 1
        by_region[region]['total'] += 1
    
    for item in unpaid_not_taken_away:
        code = item.get('client_code')
        region = clients_by_code.get(code) or 'Unknown' if code else 'Unknown'
        by_region[region]['unpaid'] += 1
        by_region[region]['total'] += 1
    
    return {
        'paid_not_taken_away': paid_not_taken_away,
        'unpaid_not_taken_away': unpaid_not_taken_away,
        'total_paid_not_taken': total_paid_not_taken,
        'total_unpaid_not_taken': total_unpaid_not_taken,
        'total_leftover': total_leftover,
        'estimated_profit': estimated_profit,
        'by_flight': dict(by_flight),
        'by_region': dict(by_region)
    }


async def generate_excel_in_background(
    bot: Bot,
    chat_id: int,
    message_id: int,
    message_text: str,
    stats: dict,
    translator: callable
) -> None:
    """
    Background task for Excel generation with progress updates.
    
    This function:
    1. Updates message with progress
    2. Resolves track_codes (DB + Google Sheets)
    3. Generates Excel
    4. Sends file
    
    Creates its own database session.
    """
    db_client = None
    try:
        # Create new database session for background task
        db_client = DatabaseClient(config.database.database_url)
        
        async for session in db_client.get_session():
            # STEP 1: Progress update - Track code resolution
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"{message_text}{translator('admin-leftover-progress-track-codes')}",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.warning(f"Failed to update progress message: {e}")
            
            # STEP 2: Resolve track_codes for unpaid items (includes Google Sheets)
            unpaid_items = stats['unpaid_not_taken_away'].copy()
            await resolve_track_codes(session, unpaid_items)
            stats['unpaid_not_taken_away'] = unpaid_items
            
            # STEP 3: Progress update - Excel generation
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"{message_text}{translator('admin-leftover-progress-excel')}",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.warning(f"Failed to update progress message: {e}")
            
            # STEP 4: Generate Excel data
            leftover_data = await get_leftover_data_for_excel(session, stats)
            
            # Translate column titles
            column_titles = {
                'client_code': translator("admin-leftover-column-client-code"),
                'full_name': translator("admin-leftover-column-full-name"),
                'region': translator("admin-leftover-column-region"),
                'address': translator("admin-leftover-column-address"),
                'phone': translator("admin-leftover-column-phone"),
                'passport_series': translator("admin-leftover-column-passport-series"),
                'pinfl': translator("admin-leftover-column-pinfl"),
                'flight_name': translator("admin-leftover-column-flight-name"),
                'row_number': translator("admin-leftover-column-row-number"),
                'track_code': translator("admin-leftover-column-track-code"),
                'cargo_source': translator("admin-leftover-column-cargo-source"),
                'is_paid': translator("admin-leftover-column-is-paid"),
                'is_taken_away': translator("admin-leftover-column-is-taken-away"),
                'taken_away_date': translator("admin-leftover-column-taken-away-date"),
                'payment_amount': translator("admin-leftover-column-payment-amount"),
                'payment_date': translator("admin-leftover-column-payment-date"),
            }
            
            excel_buffer = generate_excel_file(leftover_data, column_titles)
            
            # STEP 5: Final update + Send file
            filename = f"leftover_cargo_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
            file = BufferedInputFile(
                file=excel_buffer.read(),
                filename=filename
            )
            
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"{message_text}{translator('admin-leftover-excel-ready')}",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.warning(f"Failed to update final message: {e}")
            
            await bot.send_document(
                chat_id=chat_id,
                document=file,
                caption=translator("admin-leftover-excel-ready")
            )
            
            logger.info(f"Excel generation completed. Total records: {len(leftover_data)}")
            break  # Exit session context
            
    except Exception as e:
        logger.error(f"Error in background Excel generation: {e}", exc_info=True)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=translator("admin-leftover-error", error=str(e)) + "\n" +
                      translator("admin-leftover-error-retry")
            )
        except Exception as send_error:
            logger.error(f"Failed to send error message: {send_error}")
    finally:
        if db_client:
            await db_client.shutdown()


async def get_leftover_data_for_excel(
    session: AsyncSession,
    stats: dict
) -> list[dict]:
    """
    Get all leftover cargo data formatted for Excel export.
    
    Returns:
        List of dicts with cargo data including client info
    """
    result = []
    
    # Get all client codes
    client_codes = set()
    for t in stats['paid_not_taken_away']:
        client_codes.add(t.client_code)
    for item in stats['unpaid_not_taken_away']:
        if item.get('client_code'):
            client_codes.add(item['client_code'])
    
    # Fetch all clients
    clients_by_code = {}
    for code in client_codes:
        client = await ClientDAO.get_by_client_code(session, code)
        if client:
            clients_by_code[code] = client
    
    # Prepare paid items for track_code resolution
    paid_items_for_resolution = []
    for transaction in stats['paid_not_taken_away']:
        paid_items_for_resolution.append({
            'client_code': transaction.client_code,
            'flight_name': transaction.reys,
            'row_number': transaction.qator_raqami,
            'track_code': None,  # Will be resolved
            'transaction': transaction  # Keep reference for later
        })
    
    # Resolve track_codes for paid items (includes Google Sheets fallback)
    await resolve_track_codes(session, paid_items_for_resolution)
    
    # Process paid but not taken away
    for item_data in paid_items_for_resolution:
        transaction = item_data['transaction']
        client = clients_by_code.get(transaction.client_code)
        result.append({
            'client_code': transaction.client_code,
            'full_name': client.full_name if client else None,
            'region': client.region if client else None,
            'address': client.address if client else None,
            'phone': client.phone if client else None,
            'passport_series': client.passport_series if client else None,
            'pinfl': client.pinfl if client else None,
            'flight_name': transaction.reys,
            'row_number': transaction.qator_raqami,
            'track_code': item_data.get('track_code'),  # Use resolved track_code
            'cargo_source': 'client_transaction_data',
            'is_paid': 'YES',
            'is_taken_away': 'NO',
            'taken_away_date': None,
            'payment_amount': float(transaction.summa),
            'payment_date': transaction.created_at.replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S') if transaction.created_at else None,
        })
    
    # Process unpaid not taken away (track_codes already resolved in background task)
    for item in stats['unpaid_not_taken_away']:
        client_code = item.get('client_code')
        client = clients_by_code.get(client_code) if client_code else None
        
        # Get additional data based on source
        flight_name = item.get('flight_name')
        row_number = item.get('row_number')
        track_code = item.get('track_code')  # Already resolved
        
        result.append({
            'client_code': client_code,
            'full_name': client.full_name if client else None,
            'region': client.region if client else None,
            'address': client.address if client else None,
            'phone': client.phone if client else None,
            'passport_series': client.passport_series if client else None,
            'pinfl': client.pinfl if client else None,
            'flight_name': flight_name,
            'row_number': row_number,
            'track_code': track_code,
            'cargo_source': item.get('source', 'unknown'),
            'is_paid': 'NO',
            'is_taken_away': 'NO',
            'taken_away_date': None,
            'payment_amount': None,
            'payment_date': None,
        })
    
    return result


def generate_excel_file(data: list[dict], column_titles: dict[str, str]) -> BytesIO:
    """
    Generate Excel file from leftover cargo data in memory.
    
    Args:
        data: List of dicts with cargo data
        column_titles: Dict mapping column keys to translated titles
        
    Returns:
        BytesIO object containing Excel file
    """
    if not data:
        # Create empty DataFrame with correct columns
        df = pd.DataFrame(columns=[
            'client_code', 'full_name', 'region', 'address', 'phone',
            'passport_series', 'pinfl', 'flight_name', 'row_number',
            'track_code', 'cargo_source', 'is_paid', 'is_taken_away',
            'taken_away_date', 'payment_amount', 'payment_date'
        ])
    else:
        df = pd.DataFrame(data)
    
    # Rename columns
    existing_columns = {k: v for k, v in column_titles.items() if k in df.columns}
    df.rename(columns=existing_columns, inplace=True)
    
    # Replace None with empty string
    df = df.fillna('')
    
    # Create Excel file in memory
    excel_buffer = BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    
    excel_buffer.seek(0)
    return excel_buffer


@leftover_cargo_router.message(
    IsPrivate(),
    IsAdmin(),
    F.text.in_(["📦 Qoldiq tovarlarni olish", "📦 Получить остатки товаров"])
)
@handle_errors
async def get_leftover_cargo_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    _: callable
) -> None:
    """
    Handle leftover cargo request from admin.
    
    PHASE 1 (Fast, blocking):
    - Calculate statistics using ONLY database tables
    - Send statistics message immediately
    
    PHASE 2 (Background, non-blocking):
    - Resolve track_codes (DB + Google Sheets)
    - Generate Excel
    - Send file
    """
    await state.clear()
    
    try:
        # PHASE 1: Get statistics (FAST, DB only, no Google Sheets)
        stats = await calculate_leftover_statistics(session)
        
        # Format statistics message using i18n
        stats_text = _("admin-leftover-title") + "\n\n"
        
        stats_text += _("admin-leftover-paid-not-taken", count=stats['total_paid_not_taken']) + "\n"
        stats_text += _("admin-leftover-unpaid-not-taken", count=stats['total_unpaid_not_taken']) + "\n"
        stats_text += _("admin-leftover-total", count=stats['total_leftover']) + "\n\n"
        
        if stats['estimated_profit'] > 0:
            stats_text += _("admin-leftover-estimated-profit", amount=f"{stats['estimated_profit']:,.2f}") + "\n\n"
        
        # Breakdown by flight (limited to top N)
        if stats['by_flight']:
            stats_text += _("admin-leftover-by-flight-title") + "\n"
            # Sort by total DESC and take top N
            sorted_flights = sorted(
                stats['by_flight'].items(),
                key=lambda x: x[1]['total'],
                reverse=True
            )[:MAX_FLIGHTS_IN_STATS]
            
            for flight, counts in sorted_flights:
                stats_text += _(
                    "admin-leftover-by-flight-item",
                    flight=flight,
                    paid=counts['paid'],
                    unpaid=counts['unpaid'],
                    total=counts['total']
                ) + "\n"
            
            if len(stats['by_flight']) > MAX_FLIGHTS_IN_STATS:
                stats_text += _(
                    "admin-leftover-more-flights",
                    count=len(stats['by_flight']) - MAX_FLIGHTS_IN_STATS
                ) + "\n"
            stats_text += "\n"
        
        # Breakdown by region (limited to top N)
        if stats['by_region']:
            stats_text += _("admin-leftover-by-region-title") + "\n"
            # Sort by total DESC and take top N
            sorted_regions = sorted(
                stats['by_region'].items(),
                key=lambda x: x[1]['total'],
                reverse=True
            )[:MAX_REGIONS_IN_STATS]
            
            for region, counts in sorted_regions:
                stats_text += _(
                    "admin-leftover-by-region-item",
                    region=region,
                    paid=counts['paid'],
                    unpaid=counts['unpaid'],
                    total=counts['total']
                ) + "\n"
            
            if len(stats['by_region']) > MAX_REGIONS_IN_STATS:
                stats_text += _(
                    "admin-leftover-more-regions",
                    count=len(stats['by_region']) - MAX_REGIONS_IN_STATS
                ) + "\n"
            stats_text += "\n"
        
        

        
        # Send statistics message (PHASE 1 complete)
        stats_message = await message.answer(
            stats_text + _("admin-leftover-excel-preparing"),
            parse_mode='HTML'
        )
        
        # PHASE 2: Start background task for Excel generation
        asyncio.create_task(
            generate_excel_in_background(
                bot=bot,
                chat_id=message.chat.id,
                message_id=stats_message.message_id,
                message_text=stats_text,
                stats=stats,
                translator=_
            )
        )
        
        logger.info(f"Admin {message.from_user.id} requested leftover cargo data. "
                   f"Statistics sent, Excel generation started in background.")
        
    except Exception as e:
        await session.rollback()
        logger.error(f"Error generating leftover cargo statistics: {e}", exc_info=True)
        await message.answer(
            _("admin-leftover-error", error=str(e)) + "\n" +
            _("admin-leftover-error-retry")
        )


# ========== NOTIFICATION SETTINGS ==========

@leftover_cargo_router.message(
    IsPrivate(),
    IsAdmin(),
    F.text.in_(["📢 Bildirishnomalar", "📢 Уведомления"])
)
@handle_errors
async def leftover_notifications_menu_handler(
    message: Message,
    session: AsyncSession,
    _: callable
) -> None:
    """Handle notification settings button from admin menu."""
    # Get current settings
    static_data = await StaticDataDAO.get_first(session)
    if not static_data:
        # Create default if not exists
        static_data = await StaticDataDAO.create(session)
        await session.commit()
    
    notification_enabled = static_data.notification if static_data else False
    notification_period = static_data.notification_period if static_data else None
    
    # Build message
    text = _("admin-leftover-notifications-title") + "\n\n"
    text += _("admin-leftover-notifications-status") + ": "
    text += _("admin-leftover-notifications-on") if notification_enabled else _("admin-leftover-notifications-off")
    text += "\n"
    
    if notification_period:
        text += _("admin-leftover-notifications-period") + ": " + str(notification_period) + " " + _("admin-leftover-notifications-days")
    else:
        text += _("admin-leftover-notifications-period") + ": " + _("admin-leftover-notifications-not-set")
    
    # Build keyboard
    keyboard = InlineKeyboardBuilder()
    
    # Toggle button
    toggle_text = _("admin-leftover-notifications-turn-off") if notification_enabled else _("admin-leftover-notifications-turn-on")
    keyboard.row(
        InlineKeyboardButton(
            text=toggle_text,
            callback_data=f"leftover:notif_toggle"
        )
    )
    
    # Period buttons (1, 3, 5, 7, 10, 13, 15)
    periods = [1, 3, 5, 7, 10, 13, 15]
    buttons = []
    for period in periods:
        button_text = str(period)
        if notification_period == period:
            button_text = f"✓ {button_text}"
        buttons.append(
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"leftover:notif_period_{period}"
            )
        )
    
    # Add period buttons in rows of 3
    for i in range(0, len(buttons), 3):
        keyboard.row(*buttons[i:i+3])
    
    # Back button
    keyboard.row(
        InlineKeyboardButton(
            text=_("admin-leftover-notifications-back"),
            callback_data="leftover:notif_back"
        )
    )
    
    await message.answer(
        text,
        reply_markup=keyboard.as_markup()
    )

@leftover_cargo_router.callback_query(
    IsAdmin(),
    F.data == "leftover:notifications"
)
@handle_errors
async def notification_settings_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable
) -> None:
    """Show notification settings panel."""
    # Get current settings
    static_data = await StaticDataDAO.get_first(session)
    if not static_data:
        # Create default if not exists
        static_data = await StaticDataDAO.create(session)
        await session.commit()
    
    notification_enabled = static_data.notification if static_data else False
    notification_period = static_data.notification_period if static_data else None
    
    # Build message
    text = _("admin-leftover-notifications-title") + "\n\n"
    text += _("admin-leftover-notifications-status") + ": "
    text += _("admin-leftover-notifications-on") if notification_enabled else _("admin-leftover-notifications-off")
    text += "\n"
    
    if notification_period:
        text += _("admin-leftover-notifications-period") + ": " + str(notification_period) + " " + _("admin-leftover-notifications-days")
    else:
        text += _("admin-leftover-notifications-period") + ": " + _("admin-leftover-notifications-not-set")
    
    # Build keyboard
    keyboard = InlineKeyboardBuilder()
    
    # Toggle button
    toggle_text = _("admin-leftover-notifications-turn-off") if notification_enabled else _("admin-leftover-notifications-turn-on")
    keyboard.row(
        InlineKeyboardButton(
            text=toggle_text,
            callback_data=f"leftover:notif_toggle"
        )
    )
    
    # Period buttons (1, 3, 5, 7, 10, 13, 15)
    periods = [1, 3, 5, 7, 10, 13, 15]
    buttons = []
    for period in periods:
        button_text = str(period)
        if notification_period == period:
            button_text = f"✓ {button_text}"
        buttons.append(
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"leftover:notif_period_{period}"
            )
        )
    
    # Add period buttons in rows of 3
    for i in range(0, len(buttons), 3):
        keyboard.row(*buttons[i:i+3])
    
    # Back button
    keyboard.row(
        InlineKeyboardButton(
            text=_("admin-leftover-notifications-back"),
            callback_data="leftover:notif_back"
        )
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@leftover_cargo_router.callback_query(
    IsAdmin(),
    F.data == "leftover:notif_toggle"
)
@handle_errors
async def notification_toggle_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable
) -> None:
    """Toggle notification on/off."""
    static_data = await StaticDataDAO.get_first(session)
    if not static_data:
        static_data = await StaticDataDAO.create(session)
    
    new_value = not static_data.notification
    await StaticDataDAO.update(
        session,
        data_id=static_data.id,
        notification=new_value
    )
    await session.commit()
    
    await callback.answer(_("admin-leftover-notifications-updated"))
    # Refresh the settings panel
    await notification_settings_handler(callback, session, _)


@leftover_cargo_router.callback_query(
    IsAdmin(),
    F.data.startswith("leftover:notif_period_")
)
@handle_errors
async def notification_period_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable
) -> None:
    """Set notification period."""
    period = int(callback.data.split("_")[-1])
    
    static_data = await StaticDataDAO.get_first(session)
    if not static_data:
        static_data = await StaticDataDAO.create(session)
    
    # Setting period automatically enables notifications
    await StaticDataDAO.update(
        session,
        data_id=static_data.id,
        notification=True,
        notification_period=period
    )
    await session.commit()
    
    await callback.answer(_("admin-leftover-notifications-period-set", period=period))
    # Refresh the settings panel
    await notification_settings_handler(callback, session, _)


@leftover_cargo_router.callback_query(
    IsAdmin(),
    F.data == "leftover:notif_back"
)
@handle_errors
async def notification_back_handler(
    callback: CallbackQuery,
    _: callable
) -> None:
    """Go back from notification settings."""
    await callback.answer()
    # Just delete the message, user can request leftover cargo again
    try:
        await callback.message.delete()
    except Exception:
        pass

