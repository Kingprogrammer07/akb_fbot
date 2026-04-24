"""Admin databases import handler."""
from datetime import timedelta
from aiogram import Router, F
from aiogram.types import Message, WebAppInfo, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from src.bot.filters.is_private_chat import IsPrivate
from src.bot.filters.is_admin import IsAdmin
from src.config import config
from src.infrastructure.database.models import CargoItem
from src.infrastructure.tools.datetime_utils import get_current_time

admin_databases_router = Router(name="admin_databases")


@admin_databases_router.message(
    IsPrivate(),
    IsAdmin(),
    F.text.in_(["📥 Bazalar", "📥 Базы данны"])
)
async def admin_databases_handler(
    message: Message,
    _: callable
):
    """
    Handle databases import menu.

    Sends:
    1. WebApp button to import page
    2. Database cleanup buttons
    """
    # Create keyboard with buttons
    builder = InlineKeyboardBuilder()

    # Row 1: WebApp button
    builder.row(
        InlineKeyboardButton(
            text=_("btn-open-import-page"),
            web_app=WebAppInfo(url=config.telegram.webapp_import_url)
        )
    )

    # Row 2: Clear all database
    builder.row(
        InlineKeyboardButton(
            text=_("btn-clear-all-database"),
            callback_data="admin_db_clear_all"
        )
    )

    # Row 3: Clear recent imports (last 5 minutes)
    builder.row(
        InlineKeyboardButton(
            text=_("btn-clear-recent-imports"),
            callback_data="admin_db_clear_recent"
        )
    )

    # Send instructions with buttons
    await message.answer(
        _("admin-databases-title"),
        reply_markup=builder.as_markup()
    )


@admin_databases_router.callback_query(
    IsAdmin(),
    F.data == "admin_db_clear_all"
)
async def admin_clear_all_database_confirm(
    callback: CallbackQuery,
    _: callable
):
    """Show confirmation for clearing all database."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_("btn-confirm-action"),
            callback_data="admin_db_clear_all_confirmed"
        ),
        InlineKeyboardButton(
            text=_("btn-cancel-action"),
            callback_data="admin_db_clear_cancelled"
        )
    )

    await callback.message.edit_text(
        _("admin-db-clear-all-warning"),
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@admin_databases_router.callback_query(
    IsAdmin(),
    F.data == "admin_db_clear_all_confirmed"
)
async def admin_clear_all_database_execute(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession
):
    """Execute clearing all cargo items from database."""
    try:
        # Count items before deletion
        count_stmt = select(CargoItem)
        result = await session.execute(count_stmt)
        count = len(result.scalars().all())

        # Delete all cargo items
        delete_stmt = delete(CargoItem)
        await session.execute(delete_stmt)
        await session.commit()

        await callback.message.edit_text(
            _("admin-db-cleared-all", count=count)
        )
        await callback.answer("✅ Baza tozalandi", show_alert=True)

    except Exception as e:
        await session.rollback()
        await callback.message.edit_text(
            f"❌ Xatolik yuz berdi: {str(e)}"
        )
        await callback.answer("❌ Xatolik", show_alert=True)


@admin_databases_router.callback_query(
    IsAdmin(),
    F.data == "admin_db_clear_recent"
)
async def admin_clear_recent_imports_confirm(
    callback: CallbackQuery,
    _: callable
):
    """Show confirmation for clearing recent imports (last 5 minutes)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_("btn-confirm-action"),
            callback_data="admin_db_clear_recent_confirmed"
        ),
        InlineKeyboardButton(
            text=_("btn-cancel-action"),
            callback_data="admin_db_clear_cancelled"
        )
    )

    await callback.message.edit_text(
        _("admin-db-clear-recent-warning"),
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@admin_databases_router.callback_query(
    IsAdmin(),
    F.data == "admin_db_clear_recent_confirmed"
)
async def admin_clear_recent_imports_execute(
    callback: CallbackQuery,
    _: callable,
    session: AsyncSession
):
    """Execute clearing cargo items added in last 5 minutes."""
    try:
        # Calculate 5 minutes ago timestamp (Tashkent timezone)
        five_minutes_ago = get_current_time() - timedelta(minutes=5)

        # Count items before deletion
        count_stmt = select(CargoItem).where(CargoItem.created_at >= five_minutes_ago)
        result = await session.execute(count_stmt)
        count = len(result.scalars().all())

        # Delete cargo items from last 5 minutes
        delete_stmt = delete(CargoItem).where(CargoItem.created_at >= five_minutes_ago)
        await session.execute(delete_stmt)
        await session.commit()

        await callback.message.edit_text(
            _("admin-db-cleared-recent", count=count)
        )
        await callback.answer("✅ Oxirgi yozuvlar tozalandi", show_alert=True)

    except Exception as e:
        await session.rollback()
        await callback.message.edit_text(
            f"❌ Xatolik yuz berdi: {str(e)}"
        )
        await callback.answer("❌ Xatolik", show_alert=True)


@admin_databases_router.callback_query(
    IsAdmin(),
    F.data == "admin_db_clear_cancelled"
)
async def admin_clear_database_cancelled(
    callback: CallbackQuery,
    _: callable
):
    """Handle cancellation of database clearing."""
    await callback.message.edit_text(
        _("admin-db-clear-cancelled")
    )
    await callback.answer()
