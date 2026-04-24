"""Admin referral data handler."""
import logging
from datetime import datetime
from io import BytesIO

import pandas as pd
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, Message
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters import IsAdmin, IsPrivate
from src.bot.utils.decorators import handle_errors
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.models.client import Client

logger = logging.getLogger(__name__)
referral_data_router = Router(name="referral_data")


async def get_referral_statistics(session: AsyncSession) -> dict:
    """
    Get referral statistics from database.
    
    Returns:
        dict with keys: total_users, total_referrers, total_invited_users, top_referrers
    """
    # Total users
    total_users_result = await session.execute(
        select(func.count(Client.id)).where(Client.telegram_id.isnot(None))
    )
    total_users = total_users_result.scalar_one() or 0
    
    # Total referrers (unique users who have referred someone)
    total_referrers_result = await session.execute(
        select(func.count(func.distinct(Client.referrer_telegram_id)))
        .where(Client.referrer_telegram_id.isnot(None))
    )
    total_referrers = total_referrers_result.scalar_one() or 0
    
    # Total invited users (users with referrer_telegram_id)
    total_invited_result = await session.execute(
        select(func.count(Client.id)).where(Client.referrer_telegram_id.isnot(None))
    )
    total_invited_users = total_invited_result.scalar_one() or 0
    
    # Top referrers (users with most referrals)
    top_referrers_query = (
        select(
            Client.referrer_telegram_id,
            func.count(Client.id).label('invited_count')
        )
        .where(Client.referrer_telegram_id.isnot(None))
        .group_by(Client.referrer_telegram_id)
        .order_by(func.count(Client.id).desc())
        .limit(10)
    )
    top_referrers_result = await session.execute(top_referrers_query)
    top_referrers = []
    
    for row in top_referrers_result:
        referrer_id = row.referrer_telegram_id
        invited_count = row.invited_count
        
        # Get referrer client info
        referrer = await ClientDAO.get_by_telegram_id(session, referrer_id)
        if referrer:
            top_referrers.append({
                'client_code': referrer.client_code or 'N/A',
                'full_name': referrer.full_name,
                'invited_count': invited_count
            })
    
    return {
        'total_users': total_users,
        'total_referrers': total_referrers,
        'total_invited_users': total_invited_users,
        'top_referrers': top_referrers
    }


async def get_referral_data_for_excel(session: AsyncSession) -> list[dict]:
    """
    Get referral data formatted for Excel export.
    Matches old implementation structure exactly.
    
    Returns:
        List of dicts with keys matching old implementation:
        - taklif_qilgan_odam_id (referrer telegram_id)
        - taklif_qilgan_odam_unique_id (referrer client_code)
        - taklif_qilingan_user_id (invited user telegram_id)
        - taklif_qilingan_user_unique_id (invited user client_code)
        - referrer_balance (count of referrals by referrer)
    """
    # Get all clients with referrer_telegram_id (invited users)
    invited_clients_result = await session.execute(
        select(Client)
        .where(Client.referrer_telegram_id.isnot(None))
    )
    invited_clients = list(invited_clients_result.scalars().all())
    
    result = []
    
    for client in invited_clients:
        # Get referrer info
        referrer = await ClientDAO.get_by_telegram_id(session, client.referrer_telegram_id)
        
        if referrer:
            # Count how many users this referrer has invited
            referrer_balance = await ClientDAO.count_referrals(session, referrer.telegram_id)
            
            result.append({
                "taklif_qilgan_odam_id": referrer.telegram_id,
                "taklif_qilgan_odam_unique_id": referrer.client_code or None,
                "taklif_qilingan_user_id": client.telegram_id,
                "taklif_qilingan_user_unique_id": client.client_code or None,
                "referrer_balance": referrer_balance
            })
    
    return result


def generate_excel_file(data: list[dict]) -> BytesIO:
    """
    Generate Excel file from referral data in memory.
    Matches old implementation column names and order exactly.
    
    Args:
        data: List of dicts with referral data
        
    Returns:
        BytesIO object containing Excel file
    """
    if not data:
        # Create empty DataFrame with correct columns matching old structure
        df = pd.DataFrame(columns=[
            "taklif_qilgan_odam_id",
            "taklif_qilgan_odam_unique_id",
            "taklif_qilingan_user_id",
            "taklif_qilingan_user_unique_id",
            "referrer_balance"
        ])
    else:
        df = pd.DataFrame(data)
    
    # Rename columns to match old implementation exactly
    column_titles = {
        "taklif_qilgan_odam_id": "Taklif qilgan odam Telegram ID",
        "taklif_qilgan_odam_unique_id": "Taklif qilgan odam Client ID",
        "taklif_qilingan_user_id": "Taklif qilingan user Telegram ID",
        "taklif_qilingan_user_unique_id": "Taklif qilingan user Client ID",
        "referrer_balance": "Taklif qilgan odamning referal soni"
    }
    
    existing_columns = {k: v for k, v in column_titles.items() if k in df.columns}
    df.rename(columns=existing_columns, inplace=True)
    
    # Create Excel file in memory
    excel_buffer = BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    
    excel_buffer.seek(0)
    return excel_buffer


@referral_data_router.message(
    IsPrivate(),
    IsAdmin(),
    F.text.in_(["🔗 Referal bazani olish", "🔗 Получить базу рефералов"])
)
@handle_errors
async def get_referral_data_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    _: callable
) -> None:
    """
    Handle referral data request from admin.
    
    Flow:
    1. Send text message with referral statistics
    2. Generate Excel file in background
    3. Send Excel file as document
    """
    await state.clear()
    
    try:
        # Get statistics
        stats = await get_referral_statistics(session)
        
        # Format statistics message using i18n
        stats_text = _("admin-referral-title") + "\n\n"
        stats_text += _("admin-referral-total-users", count=stats['total_users']) + "\n"
        stats_text += _("admin-referral-total-referrers", count=stats['total_referrers']) + "\n"
        stats_text += _("admin-referral-total-invited", count=stats['total_invited_users']) + "\n\n"
        
        if stats['top_referrers']:
            stats_text += _("admin-referral-top-referrers-title") + "\n"
            for i, referrer in enumerate(stats['top_referrers'][:5], 1):
                stats_text += _(
                    "admin-referral-top-referrer-item",
                    index=i,
                    code=referrer['client_code'],
                    name=referrer['full_name'],
                    count=referrer['invited_count']
                ) + "\n"
        else:
            stats_text += _("admin-referral-no-top-referrers") + "\n"
        
        stats_text += "\n" + _("admin-referral-excel-preparing")
        
        # Send statistics message
        await message.answer(stats_text, parse_mode='HTML')
        
        # Generate Excel file in background
        referral_data = await get_referral_data_for_excel(session)
        excel_buffer = generate_excel_file(referral_data)
        
        # Create filename with timestamp
        filename = f"referral_data_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
        
        # Send Excel file
        file = BufferedInputFile(
            file=excel_buffer.read(),
            filename=filename
        )
        
        await message.answer_document(
            document=file,
            caption=_("admin-referral-excel-ready")
        )
        
        logger.info(f"Admin {message.from_user.id} requested referral data. "
                   f"Total records: {len(referral_data)}")
        
    except Exception as e:
        await session.rollback()
        logger.error(f"Error generating referral data: {e}", exc_info=True)
        await message.answer(
            _("admin-referral-error", error=str(e)) + "\n" +
            _("admin-referral-error-retry")
        )

