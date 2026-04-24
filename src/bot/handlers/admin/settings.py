"""Admin settings handler."""
import logging
import subprocess
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters import IsPrivate, IsSuperAdmin
from src.bot.states.admin_settings import AdminSettingsStates
from src.bot.utils.decorators import handle_errors
from src.bot.utils.currency_converter import currency_converter
from src.bot.utils.db_backup import create_database_backup, cleanup_backup_file
from src.bot.utils.responses import reply_with_admin_panel
from src.bot.keyboards.reply_kb.admin_menu import get_admin_main_menu
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.dao.payment_card import PaymentCardDAO
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.database.models.payment_card import PaymentCard
from src.infrastructure.services.client import ClientService
from src.infrastructure.services.payment_card import PaymentCardService
from src.infrastructure.services.static_data import StaticDataService

logger = logging.getLogger(__name__)
settings_router = Router(name="admin_settings")

# Constants
CARDS_PER_PAGE = 5
ADMINS_PER_PAGE = 5


def mask_card_number(card_number: str) -> str:
    """Mask card number showing only last 4 digits."""
    if len(card_number) < 4:
        return "****"
    return f"**** {card_number[-4:]}"


def get_settings_main_keyboard(
    translator: callable,
    ostatka_daily_enabled: bool = False,
) -> InlineKeyboardBuilder:
    """Get main settings menu keyboard.

    Args:
        translator:            Fluent translator callable (``_``).
        ostatka_daily_enabled: Current state of the ``ostatka_daily_notifications``
                               singleton flag.  Rendered inline on the toggle
                               label so the admin sees the current state
                               without first opening a submenu.
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-foto-hisobot"),
            callback_data="settings:foto_hisobot"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-extra-charge"),
            callback_data="settings:extra_charge"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-price-per-kg"),
            callback_data="settings:price_per_kg"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-usd-rate"),
            callback_data="settings:usd_rate"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-cards"),
            callback_data="settings:cards"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-add-admin"),
            callback_data="settings:add_admin"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-remove-admin"),
            callback_data="settings:remove_admin_list"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-backup"),
            callback_data="settings:backup"
        )
    )
    status_label = translator(
        "admin-settings-ostatka-enabled"
        if ostatka_daily_enabled
        else "admin-settings-ostatka-disabled"
    )
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-ostatka-daily", status=status_label),
            callback_data="settings:ostatka_daily_toggle"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-ostatka-flights"),
            callback_data="settings:ostatka_flights"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-back"),
            callback_data="settings:back"
        )
    )
    builder.adjust(2)
    return builder


async def _load_ostatka_daily_flag(session: AsyncSession) -> bool:
    """Safely read the singleton ``ostatka_daily_notifications`` flag.

    Returns ``False`` when the row is missing or the column has not been
    migrated yet, mirroring the conservative default on StaticData.
    """
    data = await StaticDataDAO.get_first(session)
    if data is None:
        return False
    return bool(getattr(data, "ostatka_daily_notifications", False))


def get_back_to_settings_keyboard(translator: callable) -> InlineKeyboardBuilder:
    """Get back to settings keyboard."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-back-to-settings"),
            callback_data="settings:main"
        )
    )
    return builder


def get_cards_keyboard(
    cards: list[PaymentCard],
    page: int,
    total_pages: int,
    translator: callable
) -> InlineKeyboardBuilder:
    """Get payment cards list keyboard with pagination."""
    builder = InlineKeyboardBuilder()
    
    # Cards buttons (5 per page)
    start_idx = page * CARDS_PER_PAGE
    end_idx = start_idx + CARDS_PER_PAGE
    page_cards = cards[start_idx:end_idx]
    
    for card in page_cards:
        status_text = translator("admin-settings-cards-active") if card.is_active else translator("admin-settings-cards-inactive")
        toggle_text = translator("admin-settings-cards-deactivate") if card.is_active else translator("admin-settings-cards-activate")
        
        builder.row(
            InlineKeyboardButton(
                text=f"{card.full_name} - {mask_card_number(card.card_number)} ({status_text})",
                callback_data=f"settings:card_toggle:{card.id}"
            )
        )
        builder.row(
            InlineKeyboardButton(
                text=toggle_text,
                callback_data=f"settings:card_delete:{card.id}"
            )
        )
    
    # Pagination controls
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️",
                callback_data=f"settings:cards_page:{page - 1}"
            )
        )
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="▶️",
                callback_data=f"settings:cards_page:{page + 1}"
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)
    
    # Add card and back buttons
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-cards-add"),
            callback_data="settings:card_add"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-back-to-settings"),
            callback_data="settings:main"
        )
    )
    
    return builder


def get_remove_admin_keyboard(
    admins: list,
    page: int,
    total_pages: int,
    translator: callable
) -> InlineKeyboardBuilder:
    """Get admin removal list keyboard with pagination."""
    builder = InlineKeyboardBuilder()

    start_idx = page * ADMINS_PER_PAGE
    end_idx = start_idx + ADMINS_PER_PAGE
    page_admins = admins[start_idx:end_idx]

    for admin in page_admins:
        code = admin.client_code or "N/A"
        builder.row(
            InlineKeyboardButton(
                text=f"{admin.full_name} - {code} ❌",
                callback_data=f"settings:fire_admin:{admin.id}"
            )
        )

    # Pagination controls
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️",
                callback_data=f"settings:remove_admin_page:{page - 1}"
            )
        )
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="▶️",
                callback_data=f"settings:remove_admin_page:{page + 1}"
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-back-to-settings"),
            callback_data="settings:main"
        )
    )

    return builder


@settings_router.message(
    IsPrivate(),
    IsSuperAdmin(),
    F.text.in_(["⚙️ Sozlamalar", "⚙️ Настройки"])
)
@handle_errors
async def settings_main_handler(
    message: Message,
    _: callable,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Handle settings main menu."""
    await state.clear()

    ostatka_enabled = await _load_ostatka_daily_flag(session)
    kyb = get_settings_main_keyboard(_, ostatka_daily_enabled=ostatka_enabled)

    await message.answer(
        _("admin-settings-title"),
        reply_markup=kyb.as_markup()
    )


@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:main"
)
@handle_errors
async def settings_main_callback(
    callback: CallbackQuery,
    _: callable,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Return to settings main menu."""
    await state.clear()

    ostatka_enabled = await _load_ostatka_daily_flag(session)
    kyb = get_settings_main_keyboard(_, ostatka_daily_enabled=ostatka_enabled)

    await callback.message.edit_text(
        _("admin-settings-title"),
        reply_markup=kyb.as_markup()
    )
    await callback.answer()


@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:ostatka_daily_toggle"
)
@handle_errors
async def ostatka_daily_toggle_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable,
) -> None:
    """Flip the ``ostatka_daily_notifications`` singleton flag.

    Re-renders the main settings menu in place so the inline status on the
    button (``Yoqildi`` / ``O'chirildi``) reflects the new value without
    forcing the admin to leave and re-open the settings screen.
    """
    current = await _load_ostatka_daily_flag(session)
    new_value = not current

    service = StaticDataService()
    result = await service.update_ostatka_daily_notifications(session, new_value)

    if not result.get("success"):
        await callback.answer(_("admin-settings-error"), show_alert=True)
        return

    status_label = _(
        "admin-settings-ostatka-enabled"
        if new_value
        else "admin-settings-ostatka-disabled"
    )
    await callback.answer(
        _("admin-settings-ostatka-toggle-success", status=status_label),
        show_alert=False,
    )

    kyb = get_settings_main_keyboard(_, ostatka_daily_enabled=new_value)
    try:
        await callback.message.edit_reply_markup(reply_markup=kyb.as_markup())
    except Exception as exc:
        # A "message is not modified" edge-case when the keyboard happens to
        # be rendered identically (e.g. race between two admins) must not
        # surface as a loud error.  The state is already persisted, so the
        # next settings open will show the correct value.
        logger.debug("ostatka toggle: edit_reply_markup no-op: %s", exc)


@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:back"
)
@handle_errors
async def settings_back_callback(
    callback: CallbackQuery,
    state: FSMContext
) -> None:
    """Go back to admin menu."""
    await state.clear()
    await callback.message.delete()
    await callback.answer()


# ========== FOTO HISOBOT ==========

@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:foto_hisobot"
)
@handle_errors
async def foto_hisobot_edit_handler(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    _: callable
) -> None:
    """Show foto_hisobot edit screen."""
    static_data = await StaticDataDAO.get_by_id(session, 1)
    current_value = static_data.foto_hisobot if static_data else None

    text = _("admin-settings-foto-hisobot-title") + "\n\n"
    if current_value:
        text += _("admin-settings-current-value") + ":\n"
        text += f"<code>{current_value}</code>\n\n"
    else:
        text += _("admin-settings-no-value") + "\n\n"
    
    text += _("admin-settings-foto-hisobot-prompt")
    
    keyboard = get_back_to_settings_keyboard(_)
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard.as_markup(),
        parse_mode='HTML'
    )
    await callback.answer()
    
    await state.set_state(AdminSettingsStates.waiting_for_foto_hisobot)


@settings_router.message(
    IsSuperAdmin(),
    IsPrivate(),
    AdminSettingsStates.waiting_for_foto_hisobot
)
@handle_errors
async def foto_hisobot_save_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    _: callable
) -> None:
    """Save foto_hisobot."""
    new_value = message.text
    
    service = StaticDataService()
    result = await service.update_foto_hisobot(session, new_value)
    await session.commit()
    
    if result['success']:
        await message.answer(_("admin-settings-foto-hisobot-success"))
    else:
        await message.answer(_("admin-settings-error"))
    
    await state.clear()
    
    # Return to settings menu
    kyb = get_settings_main_keyboard(
        _, ostatka_daily_enabled=await _load_ostatka_daily_flag(session)
    )
    await message.answer(
        _("admin-settings-title"),
        reply_markup=kyb.as_markup()
    )


# ========== EXTRA CHARGE ==========
@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:extra_charge"
)
@handle_errors
async def extra_charge_edit_handler(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    _: callable
) -> None:
    """Show extra_charge edit screen."""
    static_data = await StaticDataDAO.get_by_id(session, 1)
    current_value = static_data.extra_charge if static_data else None
    
    # Get USD to UZS rate
    try:
        usd_rate = await currency_converter.get_rate_async(session, "USD", "UZS")
    except Exception:
        await session.rollback()
        usd_rate = 12000  # Fallback
    
    text = _("admin-settings-extra-charge-title") + "\n\n"
    
    if current_value is not None:
        text += _("admin-settings-extra-charge-current", amount=current_value) + "\n"
    else:
        text += _("admin-settings-extra-charge-current", amount=0) + "\n"
    
    text += _("admin-settings-extra-charge-rate", rate=int(usd_rate)) + "\n\n"
    text += _("admin-settings-extra-charge-prompt")
    
    keyboard = get_back_to_settings_keyboard(_)
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard.as_markup(),
        parse_mode='HTML'
    )
    await callback.answer()
    
    await state.set_state(AdminSettingsStates.waiting_for_extra_charge)


@settings_router.message(
    IsSuperAdmin(),
    IsPrivate(),
    AdminSettingsStates.waiting_for_extra_charge
)
@handle_errors
async def extra_charge_save_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    _: callable
) -> None:
    """Save extra_charge."""
    try:
        new_value = int(message.text.strip())
        
        if new_value < 0:
            await message.answer(_("admin-settings-extra-charge-invalid-negative"))
            return
        
        service = StaticDataService()
        result = await service.update_extra_charge(session, new_value)
        await session.commit()
        
        if result['success']:
            await message.answer(_("admin-settings-extra-charge-success"))
        else:
            await message.answer(_("admin-settings-error"))
        
    except ValueError:
        await session.rollback()
        await message.answer(_("admin-settings-extra-charge-invalid-format"))
        return
    
    await state.clear()
    
    # Return to settings menu
    kyb = get_settings_main_keyboard(
        _, ostatka_daily_enabled=await _load_ostatka_daily_flag(session)
    )
    await message.answer(
        _("admin-settings-title"),
        reply_markup=kyb.as_markup()
    )


# ========== PRICE PER KG ==========

@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:price_per_kg"
)
@handle_errors
async def price_per_kg_edit_handler(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    _: callable
) -> None:
    """Show price_per_kg edit screen."""
    static_data = await StaticDataDAO.get_by_id(session, 1)
    current_value = static_data.price_per_kg if static_data else None
    
    # Get USD to UZS rate
    try:
        usd_rate = await currency_converter.get_rate_async(session, "USD", "UZS")
    except Exception:
        await session.rollback()
        usd_rate = 12000  # Fallback
    
    text = _("admin-settings-price-per-kg-title") + "\n\n"
    
    if current_value is not None:
        text += _("admin-settings-price-per-kg-current", amount=current_value) + "\n"
        # Convert to UZS
        price_uzs = current_value * usd_rate
        text += _("admin-settings-price-per-kg-converted", amount=int(price_uzs)) + "\n"
        
        # Calculate final (price_per_kg + extra_charge)
        extra_charge = static_data.extra_charge or 0
        final_amount = price_uzs + extra_charge
        text += _("admin-settings-price-per-kg-final", amount=int(final_amount)) + "\n"
    else:
        text += _("admin-settings-price-per-kg-current", amount=0) + "\n"
    
    text += _("admin-settings-price-per-kg-rate", rate=int(usd_rate)) + "\n\n"
    text += _("admin-settings-price-per-kg-prompt")
    
    keyboard = get_back_to_settings_keyboard(_)
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard.as_markup(),
        parse_mode='HTML'
    )
    await callback.answer()
    
    await state.set_state(AdminSettingsStates.waiting_for_price_per_kg)


@settings_router.message(
    IsSuperAdmin(),
    IsPrivate(),
    AdminSettingsStates.waiting_for_price_per_kg
)
@handle_errors
async def price_per_kg_save_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    _: callable
) -> None:
    """Save price_per_kg."""
    try:
        new_value = float(message.text.strip())
        
        if new_value <= 0:
            await message.answer(_("admin-settings-price-per-kg-invalid"))
            return
        
        service = StaticDataService()
        result = await service.update_price_per_kg(session, new_value)
        await session.commit()
        
        if result['success']:
            await message.answer(_("admin-settings-price-per-kg-success"))
        else:
            await message.answer(_("admin-settings-error"))
        
    except ValueError:
        await session.rollback()
        await message.answer(_("admin-settings-price-per-kg-invalid-format"))
        return
    
    await state.clear()
    
    # Return to settings menu
    kyb = get_settings_main_keyboard(
        _, ostatka_daily_enabled=await _load_ostatka_daily_flag(session)
    )
    await message.answer(
        _("admin-settings-title"),
        reply_markup=kyb.as_markup()
    )


# ========== PAYMENT CARDS ==========

@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:cards"
)
@settings_router.callback_query(
    IsSuperAdmin(),
    F.data.startswith("settings:cards_page:")
)
@handle_errors
async def cards_list_handler(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    _: callable
) -> None:
    """Show payment cards list."""
    await state.clear()
    
    # Get page number
    page = 0
    if callback.data.startswith("settings:cards_page:"):
        try:
            page = int(callback.data.split(":")[-1])
        except ValueError:
            await session.rollback()
            page = 0
    
    # Get all cards
    cards = await PaymentCardDAO.get_all(session)
    
    if not cards:
        text = _("admin-settings-cards-empty")
        # Show both "Add card" and "Back" buttons when no cards exist
        keyboard = InlineKeyboardBuilder()
        keyboard.row(
            InlineKeyboardButton(
                text=_("admin-settings-cards-add"),
                callback_data="settings:card_add"
            )
        )
        keyboard.row(
            InlineKeyboardButton(
                text=_("admin-settings-btn-back-to-settings"),
                callback_data="settings:main"
            )
        )
        await callback.message.edit_text(
            text,
            reply_markup=keyboard.as_markup()
        )
        await callback.answer()
        return
    
    # Calculate pagination
    total_pages = (len(cards) + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    
    # Build cards list text
    start_idx = page * CARDS_PER_PAGE
    end_idx = start_idx + CARDS_PER_PAGE
    page_cards = cards[start_idx:end_idx]
    
    text = _("admin-settings-cards-title") + "\n\n"
    
    for card in page_cards:
        status_text = _("admin-settings-cards-active") if card.is_active else _("admin-settings-cards-inactive")
        text += f"• {card.full_name}\n"
        text += f"  {mask_card_number(card.card_number)}\n"
        text += f"  {status_text}\n\n"
    
    if total_pages > 1:
        text += _("admin-settings-cards-page", page=page + 1, total=total_pages)
    
    keyboard = get_cards_keyboard(cards, page, total_pages, _)
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard.as_markup(),
        parse_mode='HTML'
    )
    await callback.answer()


@settings_router.callback_query(
    IsSuperAdmin(),
    F.data.startswith("settings:card_toggle:")
)
@handle_errors
async def card_toggle_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable
) -> None:
    """Toggle card active status."""
    try:
        card_id = int(callback.data.split(":")[-1])
    except ValueError:
        await session.rollback()
        await callback.answer(_("admin-settings-error"), show_alert=True)
        return
    
    # Check if this is the last active card
    all_cards = await PaymentCardDAO.get_all(session)
    active_cards = [c for c in all_cards if c.is_active]
    target_card = next((c for c in all_cards if c.id == card_id), None)
    
    if not target_card:
        await callback.answer(_("admin-settings-cards-not-found"), show_alert=True)
        return
    
    # If trying to deactivate last active card
    if target_card.is_active and len(active_cards) == 1:
        await callback.answer(
            _("admin-settings-cards-last-active-warning"),
            show_alert=True
        )
        return
    
    # Toggle status
    service = PaymentCardService()
    updated_card = await service.toggle_card_status(session, card_id)
    await session.commit()
    
    if updated_card:
        # Refresh the cards list - get current page from state or default to 0
        # We'll refresh by calling the cards handler with page 0
        # In a real scenario, we'd store the current page, but for simplicity, refresh to page 0
        all_cards = await PaymentCardDAO.get_all(session)
        total_pages = (len(all_cards) + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
        
        # Build cards list text
        page = 0
        start_idx = page * CARDS_PER_PAGE
        end_idx = start_idx + CARDS_PER_PAGE
        page_cards = all_cards[start_idx:end_idx]
        
        text = _("admin-settings-cards-title") + "\n\n"
        
        for card in page_cards:
            status_text = _("admin-settings-cards-active") if card.is_active else _("admin-settings-cards-inactive")
            text += f"• {card.full_name}\n"
            text += f"  {mask_card_number(card.card_number)}\n"
            text += f"  {status_text}\n\n"
        
        if total_pages > 1:
            text += _("admin-settings-cards-page", page=page + 1, total=total_pages)
        
        keyboard = get_cards_keyboard(all_cards, page, total_pages, _)
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard.as_markup(),
            parse_mode='HTML'
        )
        await callback.answer(_("admin-settings-cards-toggle-success"))
    else:
        await callback.answer(_("admin-settings-error"), show_alert=True)


@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:card_add"
)
@handle_errors
async def card_add_start_handler(
    callback: CallbackQuery,
    state: FSMContext,
    _: callable
) -> None:
    """Start add card flow."""
    text = _("admin-settings-cards-add-prompt-name")
    
    keyboard = get_back_to_settings_keyboard(_)
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()
    
    await state.set_state(AdminSettingsStates.waiting_for_card_full_name)


@settings_router.message(
    IsSuperAdmin(),
    IsPrivate(),
    AdminSettingsStates.waiting_for_card_full_name
)
@handle_errors
async def card_add_name_handler(
    message: Message,
    state: FSMContext,
    _: callable
) -> None:
    """Save card full name and ask for card number."""
    full_name = message.text.strip()
    
    if not full_name:
        await message.answer(_("admin-settings-cards-add-invalid-name"))
        return
    
    await state.update_data(full_name=full_name)
    
    await message.answer(_("admin-settings-cards-add-prompt-number"))
    
    await state.set_state(AdminSettingsStates.waiting_for_card_number)


@settings_router.message(
    IsSuperAdmin(),
    IsPrivate(),
    AdminSettingsStates.waiting_for_card_number
)
@handle_errors
async def card_add_number_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    _: callable
) -> None:
    """Save card number and create card."""
    card_number = message.text.strip().replace(" ", "").replace("-", "")
    
    # Validation
    if not card_number.isdigit():
        await message.answer(_("admin-settings-cards-add-invalid-number-format"))
        return
    
    if len(card_number) < 16 or len(card_number) > 19:
        await message.answer(_("admin-settings-cards-add-invalid-number-length"))
        return
    
    # Check if card already exists
    all_cards = await PaymentCardDAO.get_all(session)
    if any(c.card_number == card_number for c in all_cards):
        await message.answer(_("admin-settings-cards-add-duplicate"))
        return
    
    # Get full_name from state
    data = await state.get_data()
    full_name = data.get('full_name')
    
    # Create card
    service = PaymentCardService()
    try:
        card = await service.create_card(session, full_name, card_number)
        await session.commit()
        
        await message.answer(_("admin-settings-cards-add-success"))
    except Exception as e:
        await session.rollback()
        logger.error(f"Error creating card: {e}")
        await message.answer(_("admin-settings-error"))
    
    await state.clear()
    
    # Return to settings menu
    kyb = get_settings_main_keyboard(
        _, ostatka_daily_enabled=await _load_ostatka_daily_flag(session)
    )
    await message.answer(
        _("admin-settings-title"),
        reply_markup=kyb.as_markup()
    )


# ========== ADMIN MANAGEMENT ==========

@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:add_admin"
)
@handle_errors
async def add_admin_start_handler(
    callback: CallbackQuery,
    state: FSMContext,
    _: callable
) -> None:
    """Start add admin flow."""
    text = _("admin-settings-add-admin-prompt")
    
    keyboard = get_back_to_settings_keyboard(_)
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()
    
    await state.set_state(AdminSettingsStates.waiting_for_admin_identifier)


@settings_router.message(
    IsSuperAdmin(),
    IsPrivate(),
    AdminSettingsStates.waiting_for_admin_identifier
)
@handle_errors
async def add_admin_process_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    _: callable
) -> None:
    """Process admin identifier and add admin."""
    from sqlalchemy import select
    from src.infrastructure.database.models.client import Client
    
    identifier = message.text.strip()
    
    # Determine identifier type and validate
    client = None
    method = None
    
    # Check if Telegram ID (numeric, >= 6 digits)
    if identifier.isdigit() and len(identifier) >= 6:
        try:
            telegram_id = int(identifier)
            client = await ClientDAO.get_by_telegram_id(session, telegram_id)
            method = "Telegram ID"
        except ValueError:
            await session.rollback()
            pass
    
    # Check if username (starts with @ or just text)
    if not client:
        username = identifier.lstrip('@').lower()
        if username:
            # Search by username
            result = await session.execute(
                select(Client).where(Client.username.ilike(username))
            )
            clients = list(result.scalars().all())
            if len(clients) == 1:
                client = clients[0]
                method = "Username"
            elif len(clients) > 1:
                await message.answer(_("admin-settings-add-admin-multiple-found"))
                return
    
    # Check if client_code
    if not client:
        client = await ClientDAO.get_by_client_code(session, identifier.upper())
        if client:
            method = "Client code"
    
    # Validation
    if not client:
        await message.answer(_("admin-settings-add-admin-not-found"))
        return
    
    if client.role in ['admin', 'super-admin']:
        await message.answer(_("admin-settings-add-admin-already-admin"))
        return
    
    # Add admin
    client.role = 'admin'
    await session.commit()
    
    # Confirmation to current admin
    identifier_display = identifier
    if method == "Username":
        identifier_display = f"@{client.username}" if client.username else identifier
    elif method == "Client code":
        identifier_display = client.client_code or identifier
    
    await message.answer(
        _("admin-settings-add-admin-success", method=method, identifier=identifier_display)
    )
    
    # Send message to new admin
    try:
        admin_menu = get_admin_main_menu(translator=_, is_super_admin=False)
        await bot.send_message(
            chat_id=client.telegram_id,
            text=_("admin-settings-add-admin-welcome"),
            reply_markup=admin_menu
        )
    except Exception as e:
        await session.rollback()
        logger.warning(f"Failed to send message to new admin {client.telegram_id}: {e}")
    
    await state.clear()
    
    # Return to settings menu
    kyb = get_settings_main_keyboard(
        _, ostatka_daily_enabled=await _load_ostatka_daily_flag(session)
    )
    await message.answer(
        _("admin-settings-title"),
        reply_markup=kyb.as_markup()
    )


# ========== REMOVE ADMIN ==========

@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:remove_admin_list"
)
@settings_router.callback_query(
    IsSuperAdmin(),
    F.data.startswith("settings:remove_admin_page:")
)
@handle_errors
async def remove_admin_list_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable
) -> None:
    """Show paginated list of admins for removal."""
    from sqlalchemy import select
    from src.infrastructure.database.models.client import Client

    # Get page number
    page = 0
    if callback.data.startswith("settings:remove_admin_page:"):
        try:
            page = int(callback.data.split(":")[-1])
        except ValueError:
            await session.rollback()
            page = 0

    # Query all admins
    result = await session.execute(
        select(Client).where(Client.role.in_(['admin', 'super-admin'])).order_by(Client.full_name)
    )
    admins = list(result.scalars().all())

    if not admins:
        keyboard = get_back_to_settings_keyboard(_)
        await callback.message.edit_text(
            _("admin-settings-remove-admin-empty"),
            reply_markup=keyboard.as_markup()
        )
        await callback.answer()
        return

    # Pagination
    total_pages = max(1, (len(admins) + ADMINS_PER_PAGE - 1) // ADMINS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    # Build text
    start_idx = page * ADMINS_PER_PAGE
    end_idx = start_idx + ADMINS_PER_PAGE
    page_admins = admins[start_idx:end_idx]

    text = _("admin-settings-remove-admin-title") + "\n\n"
    for admin in page_admins:
        code = admin.client_code or "N/A"
        text += f"• {admin.full_name} — {code}\n"

    if total_pages > 1:
        text += "\n" + _("admin-settings-cards-page", page=page + 1, total=total_pages)

    keyboard = get_remove_admin_keyboard(admins, page, total_pages, _)

    await callback.message.edit_text(
        text,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@settings_router.callback_query(
    IsSuperAdmin(),
    F.data.startswith("settings:fire_admin:")
)
@handle_errors
async def fire_admin_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable
) -> None:
    """Remove admin privileges from a client."""
    from sqlalchemy import select
    from src.infrastructure.database.models.client import Client

    try:
        client_id = int(callback.data.split(":")[-1])
    except ValueError:
        await session.rollback()
        await callback.answer(_("admin-settings-error"), show_alert=True)
        return

    # Fetch target client
    result = await session.execute(
        select(Client).where(Client.id == client_id)
    )
    target = result.scalar_one_or_none()

    if not target:
        await callback.answer(_("error-user-not-found"), show_alert=True)
        return

    # Prevent self-removal
    if target.telegram_id == callback.from_user.id:
        await callback.answer(
            _("admin-settings-remove-admin-self"),
            show_alert=True
        )
        return

    # Demote
    target.role = 'user'
    await session.commit()

    await callback.answer(
        _("admin-settings-remove-admin-success", full_name=target.full_name),
        show_alert=True
    )

    # Refresh the list
    result = await session.execute(
        select(Client).where(Client.role.in_(['admin', 'super-admin'])).order_by(Client.full_name)
    )
    admins = list(result.scalars().all())

    if not admins:
        keyboard = get_back_to_settings_keyboard(_)
        await callback.message.edit_text(
            _("admin-settings-remove-admin-empty"),
            reply_markup=keyboard.as_markup()
        )
        return

    total_pages = max(1, (len(admins) + ADMINS_PER_PAGE - 1) // ADMINS_PER_PAGE)
    page = 0

    text = _("admin-settings-remove-admin-title") + "\n\n"
    page_admins = admins[:ADMINS_PER_PAGE]
    for admin in page_admins:
        code = admin.client_code or "N/A"
        text += f"• {admin.full_name} — {code}\n"

    if total_pages > 1:
        text += "\n" + _("admin-settings-cards-page", page=1, total=total_pages)

    keyboard = get_remove_admin_keyboard(admins, page, total_pages, _)

    await callback.message.edit_text(
        text,
        reply_markup=keyboard.as_markup()
    )


# ========== DATABASE BACKUP ==========

@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:backup"
)
@handle_errors
async def backup_database_handler(
    callback: CallbackQuery,
    bot: Bot,
    _: callable
) -> None:
    """Handle database backup request."""
    from aiogram.types import BufferedInputFile
    
    await callback.answer(_("admin-settings-backup-creating"))
    
    try:
        # Notify admin that backup is being created
        status_message = await callback.message.answer(_("admin-settings-backup-in-progress"))
        
        # Create backup
        backup_path = create_database_backup()
        
        try:
            # Read backup file
            with open(backup_path, 'rb') as f:
                backup_data = f.read()
            
            # Create BufferedInputFile for sending
            file = BufferedInputFile(
                file=backup_data,
                filename=backup_path.name
            )
            
            # Send backup to admin
            await bot.send_document(
                chat_id=callback.from_user.id,
                document=file,
                caption=_("admin-settings-backup-caption")
            )
            
            # Update status message
            await status_message.edit_text(_("admin-settings-backup-success"))
            
            logger.info(f"Database backup sent to admin {callback.from_user.id}: {backup_path.name}")
            
        finally:
            # Always clean up backup file
            cleanup_backup_file(backup_path)
            
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or str(e)
        logger.error(f"Database backup failed: {error_msg}", exc_info=True)
        await callback.message.answer(_("admin-settings-backup-error"))
    except FileNotFoundError as e:
        if "pg_dump" in str(e):
            logger.error("pg_dump command not found")
            await callback.message.answer(_("admin-settings-backup-pgdump-not-found"))
        else:
            logger.error(f"Backup file error: {e}", exc_info=True)
            await callback.message.answer(_("admin-settings-backup-error"))
    except Exception as e:
        logger.error(f"Unexpected error during backup: {e}", exc_info=True)
        await callback.message.answer(_("admin-settings-backup-error"))


@settings_router.callback_query(
    IsSuperAdmin(),
    F.data.startswith("settings:card_delete:")
)
@handle_errors
async def card_delete_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable
):
    card_id = int(callback.data.split(":")[-1])

    card = await PaymentCardDAO.get_by_id(session, card_id)
    if not card:
        await callback.answer(_("admin-settings-cards-not-found"), show_alert=True)
        return

    # Last active card protection
    if card.is_active:
        active_cards = await PaymentCardDAO.get_all_active(session)
        if len(active_cards) == 1:
            await callback.answer(_("admin-settings-cards-last-active-warning"), show_alert=True)
            return

    await PaymentCardDAO.delete(session, card)
    await session.commit()

    await callback.answer(_("admin-settings-cards-delete-success"))

    # Refresh list
    cards = await PaymentCardDAO.get_all(session)
    page = 0
    total_pages = max(1, (len(cards) + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE)

    keyboard = get_cards_keyboard(cards, page, total_pages, _)

    await callback.message.edit_text(
        _("admin-settings-cards-title"),
        reply_markup=keyboard.as_markup()
    )


# ========== USD RATE ==========

@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:usd_rate"
)
@handle_errors
async def usd_rate_menu_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable
) -> None:
    """Show USD Rate menu."""
    static_data = await StaticDataDAO.get_by_id(session, 1)
    is_custom = static_data.use_custom_rate if static_data else False
    custom_rate = static_data.custom_usd_rate if static_data else None

    # Always fetch live API rate
    try:
        live_rate = await currency_converter.get_rate_async(session, "USD", "UZS")
    except Exception:
        await session.rollback()
        live_rate = 12000

    if is_custom and custom_rate:
        status_text = _("admin-settings-rate-status-custom", rate=int(custom_rate))
    else:
        status_text = _("admin-settings-rate-status-api")

    text = _("admin-settings-rate-title") + "\n\n"
    text += f"{status_text}\n"
    text += _("admin-settings-rate-live", rate=int(live_rate))

    # Build keyboard
    kyb = InlineKeyboardBuilder()
    kyb.row(
        InlineKeyboardButton(
            text=_("admin-settings-btn-edit-rate"),
            callback_data="settings:edit_rate"
        )
    )
    kyb.row(
        InlineKeyboardButton(
            text=_("admin-settings-btn-api-rate"),
            callback_data="settings:toggle_rate:api"
        ),
        InlineKeyboardButton(
            text=_("admin-settings-btn-custom-rate"),
            callback_data="settings:toggle_rate:custom"
        )
    )
    kyb.row(
        InlineKeyboardButton(
            text=_("admin-settings-btn-back-to-settings"),
            callback_data="settings:main"
        )
    )

    await callback.message.edit_text(
        text,
        reply_markup=kyb.as_markup(),
        parse_mode='HTML'
    )
    await callback.answer()


@settings_router.callback_query(
    IsSuperAdmin(),
    F.data.startswith("settings:toggle_rate:")
)
@handle_errors
async def usd_rate_toggle_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    redis: Redis,
    _: callable
) -> None:
    """Toggle between API and Custom rate."""
    mode = callback.data.split(":")[-1]
    use_custom = True if mode == "custom" else False

    static_data = await StaticDataDAO.get_by_id(session, 1)
    if use_custom and not (static_data and static_data.custom_usd_rate):
        await callback.answer(_("admin-settings-rate-no-custom"), show_alert=True)
        return

    service = StaticDataService()
    await service.update_usd_rate_mode(session, use_custom)
    await session.commit()
    await redis.delete("currency:usd_uzs")

    await callback.answer(_("admin-settings-rate-toggle-success"))
    
    # Reload USD menu
    await usd_rate_menu_handler(callback, session, _)


@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:edit_rate"
)
@handle_errors
async def usd_rate_edit_handler(
    callback: CallbackQuery,
    state: FSMContext,
    _: callable
) -> None:
    """Start edit flow for USD rate."""
    text = _("admin-settings-rate-prompt")
    
    kyb = InlineKeyboardBuilder()
    kyb.row(
        InlineKeyboardButton(
            text=_("admin-settings-btn-back-to-settings"),
            callback_data="settings:main"
        )
    )

    await callback.message.edit_text(
        text,
        reply_markup=kyb.as_markup(),
        parse_mode='HTML'
    )
    await callback.answer()
    
    await state.set_state(AdminSettingsStates.waiting_for_usd_rate)


@settings_router.message(
    IsSuperAdmin(),
    IsPrivate(),
    AdminSettingsStates.waiting_for_usd_rate
)
@handle_errors
async def usd_rate_save_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    redis: Redis,
    _: callable
) -> None:
    """Save custom USD rate."""
    try:
        new_rate = float(message.text.strip())
        if new_rate < 1000:
            await message.answer(_("admin-settings-rate-invalid"))
            return

        service = StaticDataService()
        result = await service.update_custom_usd_rate(session, new_rate)
        await session.commit()
        await redis.delete("currency:usd_uzs")
        
        if result['success']:
            await message.answer(_("admin-settings-rate-success"))
        else:
            await message.answer(_("admin-settings-error"))
            
    except ValueError:
        await session.rollback()
        await message.answer(_("admin-settings-rate-invalid"))
        return

    await state.clear()

    # Return to settings menu
    kyb = get_settings_main_keyboard(
        _, ostatka_daily_enabled=await _load_ostatka_daily_flag(session)
    )
    await message.answer(
        _("admin-settings-title"),
        reply_markup=kyb.as_markup()
    )


# ========== OSTATKA FLIGHT SELECTION ==========

import json as _json


async def _load_selected_flights(session: AsyncSession) -> list[str]:
    """Return the whitelist of A- flights selected for daily auto-send."""
    data = await StaticDataDAO.get_first(session)
    if data is None:
        return []
    raw = getattr(data, "ostatka_daily_flight_names", "[]") or "[]"
    try:
        return [n.upper() for n in _json.loads(raw) if n]
    except (ValueError, TypeError):
        return []


async def _get_available_ostatka_flights(session: AsyncSession) -> list[str]:
    """Return distinct A- flight names that exist in flight_cargos."""
    from sqlalchemy import distinct
    from src.infrastructure.database.models.flight_cargo import FlightCargo

    rows = (
        await session.execute(
            select(distinct(FlightCargo.flight_name))
            .where(FlightCargo.flight_name.ilike("A-%"))
            .order_by(FlightCargo.flight_name)
        )
    ).scalars().all()
    return list(rows)


def _build_flight_selection_keyboard(
    available: list[str],
    selected: list[str],
    translator: callable,
) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    selected_upper = {f.upper() for f in selected}
    for flight in available:
        check = "✅" if flight.upper() in selected_upper else "⬜"
        builder.row(
            InlineKeyboardButton(
                text=f"{check} {flight}",
                callback_data=f"settings:ostatka_flight_toggle:{flight}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text=translator("admin-settings-btn-back-to-settings"),
            callback_data="settings:main",
        )
    )
    return builder


@settings_router.callback_query(
    IsSuperAdmin(),
    F.data == "settings:ostatka_flights"
)
@handle_errors
async def ostatka_flights_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable,
) -> None:
    """Show A- flight selection screen for daily auto-send."""
    available = await _get_available_ostatka_flights(session)
    selected = await _load_selected_flights(session)

    if not available:
        await callback.answer(_("admin-settings-ostatka-flights-empty"), show_alert=True)
        return

    kyb = _build_flight_selection_keyboard(available, selected, _)
    await callback.message.edit_text(
        _("admin-settings-ostatka-flights-title"),
        reply_markup=kyb.as_markup(),
    )
    await callback.answer()


@settings_router.callback_query(
    IsSuperAdmin(),
    F.data.startswith("settings:ostatka_flight_toggle:")
)
@handle_errors
async def ostatka_flight_toggle_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    _: callable,
) -> None:
    """Toggle a single A- flight in/out of the daily send whitelist."""
    flight_name = callback.data.split(":", 2)[2].upper()

    selected = await _load_selected_flights(session)
    selected_set = set(selected)

    if flight_name in selected_set:
        selected_set.discard(flight_name)
    else:
        selected_set.add(flight_name)

    new_list = sorted(selected_set)
    service = StaticDataService()
    result = await service.update_ostatka_daily_flight_names(session, new_list)

    if not result.get("success"):
        await callback.answer(_("admin-settings-error"), show_alert=True)
        return

    await callback.answer()

    available = await _get_available_ostatka_flights(session)
    kyb = _build_flight_selection_keyboard(available, new_list, _)
    try:
        await callback.message.edit_reply_markup(reply_markup=kyb.as_markup())
    except Exception as exc:
        logger.debug("ostatka flight toggle: edit_reply_markup no-op: %s", exc)
