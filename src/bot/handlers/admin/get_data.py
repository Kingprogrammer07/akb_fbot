"""Admin get data handler."""
import logging
from datetime import datetime
from io import BytesIO

import pandas as pd
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, Message
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.utils.constants import UZBEKISTAN_REGIONS
from src.bot.filters import IsAdmin, IsPrivate
from src.bot.utils.decorators import handle_errors
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.flight_cargo import FlightCargo

logger = logging.getLogger(__name__)
get_data_router = Router(name="admin_get_data")

async def get_client_statistics(session: AsyncSession) -> dict:
    """
    Get client statistics from database.
    
    Returns:
        dict with keys: total_clients, active_clients, inactive_clients,
        first_registration, last_registration
    """
    # Total clients
    total_clients = await ClientDAO.count_all(session)
    
    # Active clients (is_logged_in = True)
    active_result = await session.execute(
        select(func.count(Client.id))
        .where(Client.telegram_id.isnot(None), Client.is_logged_in == True)
    )
    active_clients = active_result.scalar_one() or 0
    
    # Inactive clients (is_logged_in = False or telegram_id is None)
    inactive_result = await session.execute(
        select(func.count(Client.id))
        .where(
            (Client.telegram_id.isnot(None)) & (Client.is_logged_in == False)
        )
    )
    inactive_clients = inactive_result.scalar_one() or 0
    
    # First registration date
    first_reg_result = await session.execute(
        select(func.min(Client.created_at))
        .where(Client.telegram_id.isnot(None))
    )
    first_registration = first_reg_result.scalar_one()
    
    # Last registration date
    last_reg_result = await session.execute(
        select(func.max(Client.created_at))
        .where(Client.telegram_id.isnot(None))
    )
    last_registration = last_reg_result.scalar_one()
    
    return {
        'total_clients': total_clients,
        'active_clients': active_clients,
        'inactive_clients': inactive_clients,
        'first_registration': first_registration,
        'last_registration': last_registration
    }


async def get_all_clients_data(session: AsyncSession) -> list[dict]:
    """
    Get all clients data formatted for Excel export.
    
    Uses LEFT OUTER JOIN with FlightCargo to get is_sent_web / is_sent_web_date
    at the database level (no N+1 queries).
    
    Returns:
        List of dicts with client data
    """
    stmt = (
        select(
            Client,
            # MAX o'rniga bool_or ishlatamiz
            func.bool_or(FlightCargo.is_sent_web).label('is_sent_web'),
            func.max(FlightCargo.is_sent_web_date).label('is_sent_web_date'),
        )
        .outerjoin(
            FlightCargo,
            or_(
                FlightCargo.client_id == Client.client_code,
                FlightCargo.client_id == Client.extra_code,
                FlightCargo.client_id == Client.legacy_code
            ),
        )
        .group_by(Client.id)
    )
    
    result = await session.execute(stmt)
    rows = result.all()
    
    data = []
    for row in rows:
        client = row[0]
        # bool_or dan qaytadigan natija uchun ham kichik xavfsizlik tekshiruvi
        is_sent_web = bool(row.is_sent_web) if row.is_sent_web is not None else False
        is_sent_web_date = row.is_sent_web_date
        
        data.append({
            'id': client.id,
            'telegram_id': client.telegram_id,
            'full_name': client.full_name,
            'phone': client.phone or None,
            'language_code': client.language_code,
            'role': client.role,
            'passport_series': client.passport_series or None,
            'pinfl': client.pinfl or None,
            'date_of_birth': client.date_of_birth.isoformat() if client.date_of_birth else None,
            'region': UZBEKISTAN_REGIONS.get(client.region, client.region) or None,
            'address': client.address or None,
            'client_code': client.client_code or None,
            'extra_code': client.extra_code or None,
            'legacy_code': client.legacy_code or None,
            'referrer_telegram_id': client.referrer_telegram_id or None,
            'referrer_client_code': client.referrer_client_code or None,
            'is_logged_in': client.is_logged_in,
            'is_sent_web': is_sent_web,
            'is_sent_web_date': is_sent_web_date.replace(tzinfo=None) if is_sent_web_date else None,
            'created_at': client.created_at.replace(tzinfo=None) if client.created_at else None,
            'updated_at': client.updated_at.replace(tzinfo=None) if client.updated_at else None,
            'last_seen_at': client.last_seen_at.replace(tzinfo=None) if client.last_seen_at else None,
        })
    
    return data

def generate_excel_file(data: list[dict], column_titles: dict[str, str]) -> BytesIO:
    """
    Generate Excel file from client data in memory.
    
    Args:
        data: List of dicts with client data
        column_titles: Dict mapping column keys to translated titles
        
    Returns:
        BytesIO object containing Excel file
    """
    if not data:
        # Create empty DataFrame with correct columns
        df = pd.DataFrame(columns=[
            'id', 'telegram_id', 'full_name', 'phone', 'language_code',
            'role', 'passport_series', 'pinfl', 'date_of_birth',
            'region', 'address', 'client_code', 'extra_code', 'legacy_code',
            'referrer_telegram_id', 'referrer_client_code', 'is_logged_in',
            'is_sent_web', 'is_sent_web_date', 'created_at', 'updated_at', 'last_seen_at'
        ])
    else:
        df = pd.DataFrame(data)
    
    # Rename columns to more readable format
    existing_columns = {k: v for k, v in column_titles.items() if k in df.columns}
    df.rename(columns=existing_columns, inplace=True)
    
    # Format datetime columns
    created_at_col = column_titles.get('created_at')
    if created_at_col and created_at_col in df.columns:
        df[created_at_col] = pd.to_datetime(df[created_at_col], errors='coerce')
        df[created_at_col] = df[created_at_col].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    date_of_birth_col = column_titles.get('date_of_birth')
    if date_of_birth_col and date_of_birth_col in df.columns:
        df[date_of_birth_col] = pd.to_datetime(df[date_of_birth_col], errors='coerce')
        df[date_of_birth_col] = df[date_of_birth_col].dt.strftime('%Y-%m-%d')
    
    is_sent_web_date_col = column_titles.get('is_sent_web_date')
    if is_sent_web_date_col and is_sent_web_date_col in df.columns:
        df[is_sent_web_date_col] = pd.to_datetime(df[is_sent_web_date_col], errors='coerce')
        df[is_sent_web_date_col] = df[is_sent_web_date_col].dt.strftime('%Y-%m-%d %H:%M:%S')

    for ts_col_key in ('updated_at', 'last_seen_at'):
        ts_col = column_titles.get(ts_col_key)
        if ts_col and ts_col in df.columns:
            df[ts_col] = pd.to_datetime(df[ts_col], errors='coerce')
            df[ts_col] = df[ts_col].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # Create Excel file in memory
    excel_buffer = BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    
    excel_buffer.seek(0)
    return excel_buffer


@get_data_router.message(
    IsPrivate(),
    IsAdmin(),
    F.text.in_(["📁 Ma'lumot olish", "📁 Получить данные"])
)
@handle_errors
async def get_data_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    _: callable
) -> None:
    """
    Handle get data request from admin.
    
    Flow:
    1. Send text message with client statistics
    2. Generate Excel file in background
    3. Send Excel file as document
    """
    await state.clear()
    
    try:
        # Get statistics
        stats = await get_client_statistics(session)
        
        # Format statistics message using i18n
        stats_text = _("admin-data-title") + "\n\n"
        stats_text += _("admin-data-total-clients", count=stats['total_clients']) + "\n"
        stats_text += _("admin-data-active-clients", count=stats['active_clients']) + "\n"
        stats_text += _("admin-data-inactive-clients", count=stats['inactive_clients']) + "\n"
        stats_text += "Telegram idsi mavjud bo'lmaganlar: " + str(int(stats['total_clients']) - int(stats['inactive_clients'])) + "\n\n"
        
        if stats['first_registration']:
            first_date = stats['first_registration'].strftime('%Y-%m-%d %H:%M')
            stats_text += _("admin-data-first-registration", date=first_date) + "\n"
        else:
            stats_text += _("admin-data-first-registration", date=_("admin-data-not-available")) + "\n"
        
        if stats['last_registration']:
            last_date = stats['last_registration'].strftime('%Y-%m-%d %H:%M')
            stats_text += _("admin-data-last-registration", date=last_date) + "\n"
        else:
            stats_text += _("admin-data-last-registration", date=_("admin-data-not-available")) + "\n"
        
        stats_text += "\n" + _("admin-data-excel-preparing")
        
        # Send statistics message
        await message.answer(stats_text, parse_mode='HTML')
        
        # Generate Excel file in background
        clients_data = await get_all_clients_data(session)
        
        # Translate column titles in handler
        column_titles = {
            'id': _("admin-data-column-id"),
            'telegram_id': _("admin-data-column-telegram-id"),
            'full_name': _("admin-data-column-full-name"),
            'phone': _("admin-data-column-phone"),
            'language_code': _("admin-data-column-language"),
            'role': _("admin-data-column-role"),
            'passport_series': _("admin-data-column-passport-series"),
            'pinfl': _("admin-data-column-pinfl"),
            'date_of_birth': _("admin-data-column-date-of-birth"),
            'region': _("admin-data-column-region"),
            'address': _("admin-data-column-address"),
            'client_code': _("admin-data-column-client-code"),
            'referrer_telegram_id': _("admin-data-column-referrer-telegram-id"),
            'referrer_client_code': _("admin-data-column-referrer-client-code"),
            'is_logged_in': _("admin-data-column-is-logged-in"),
            'extra_code': "Qo'shimcha Kod (Extra Code)",
            'legacy_code': "Eski Kod (Legacy Code)",
            'is_sent_web': "Web orqali jo'natilganmi",
            'is_sent_web_date': "Web jo'natilgan sana",
            'created_at': _("admin-data-column-created-at"),
            'updated_at': "Yangilangan sana",
            'last_seen_at': "Oxirgi faollik (Bot)"
        }
        
        excel_buffer = generate_excel_file(clients_data, column_titles)
        
        # Create filename with timestamp
        filename = f"clients_data_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
        
        # Send Excel file
        file = BufferedInputFile(
            file=excel_buffer.read(),
            filename=filename
        )
        
        await message.answer_document(
            document=file,
            caption=_("admin-data-excel-ready")
        )
        
        logger.info(f"Admin {message.from_user.id} requested client data. "
                   f"Total records: {len(clients_data)}")
        
    except Exception as e:
        await session.rollback()
        logger.error(f"Error generating client data: {e}", exc_info=True)
        await message.answer(
            _("admin-data-error", error=str(e)) + "\n" +
            _("admin-data-error-retry")
        )

