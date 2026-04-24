"""Profile handlers."""

import json
import asyncio
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from src.bot.filters.is_private_chat import IsPrivate
from src.bot.filters.is_logged_in import IsLoggedIn, ClientExists, IsRegistered
from src.bot.keyboards.user.reply_keyb.profile_kyb import profile_menu_kyb
from src.bot.keyboards.user.reply_keyb.user_home_kyb import user_main_menu_kyb
from src.bot.keyboards.user.inline_keyb.profile_inline_kyb import (
    logout_confirm_kyb,
    edit_profile_kyb,
)
from src.bot.utils.decorators import handle_errors
from src.infrastructure.services.client import ClientService
from src.infrastructure.tools.datetime_utils import to_tashkent
from src.config import BASE_DIR


profile_router = Router(name="profile")


class EditProfileStates(StatesGroup):
    """States for editing profile."""

    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_region = State()
    waiting_for_district_selection = State()
    waiting_for_address = State()


# Region constants for Uzbekistan
UZBEKISTAN_REGIONS = {
    "toshkent_city": "region-toshkent-city",
    "toshkent": "region-toshkent",
    "andijan": "region-andijan",
    "bukhara": "region-bukhara",
    "fergana": "region-fergana",
    "jizzakh": "region-jizzakh",
    "kashkadarya": "region-qashqadarya",
    "navoi": "region-navoiy",
    "namangan": "region-namangan",
    "samarkand": "region-samarkand",
    "sirdarya": "region-sirdarya",
    "surkhandarya": "region-surkhandarya",
    "karakalpakstan": "region-karakalpakstan",
    "khorezm": "region-khorezm",
}


async def _send_profile_images(message: Message, file_ids: list[str]):
    """Robustly send passport images using cascade strategy.

    Strategy order:
    - Single file: photo -> document
    - Multiple files: album -> sequential photos -> sequential documents
    Never raises — errors are logged and silently swallowed so the
    profile text is always sent afterwards.
    """
    if not file_ids:
        return

    if len(file_ids) == 1:
        try:
            await message.answer_photo(photo=file_ids[0])
            return
        except Exception:
            logger.debug("Single photo send failed, trying as document")
        try:
            await message.answer_document(document=file_ids[0])
            return
        except Exception:
            logger.warning("Failed to send single passport image as photo and document")
            return

    # Multiple files — Strategy A: album
    try:
        media = [InputMediaPhoto(media=fid) for fid in file_ids]
        await message.answer_media_group(media=media)
        return
    except Exception:
        logger.debug("Album send failed, trying sequential photos")

    # Strategy B: sequential photos
    try:
        for fid in file_ids:
            await message.answer_photo(photo=fid)
            await asyncio.sleep(0.3)
        return
    except Exception:
        logger.debug("Sequential photos failed, trying sequential documents")

    # Strategy C: sequential documents
    try:
        for fid in file_ids:
            await message.answer_document(document=fid)
            await asyncio.sleep(0.3)
    except Exception:
        logger.warning("All strategies failed to send passport images")


@profile_router.message(
    IsPrivate(),
    ClientExists(),
    IsRegistered(),
    IsLoggedIn(),
    F.text.in_(["👤 Profil", "👤 Профиль"]),
)
@handle_errors
async def profile_handler(
    message: Message,
    session: AsyncSession,
    client_service: ClientService,
    _: callable,
    state: FSMContext,
):
    """Show user profile with all information including passport images."""
    await state.clear()
    client = await client_service.get_client(message.from_user.id, session)

    if not client:
        await message.answer(_("error-occurred"))
        return

    if client.language_code == "ru":
        with open(
            BASE_DIR / "locales" / "district_ru.json", "r", encoding="utf-8"
        ) as f:
            district_ru = json.load(f)
            district_ru = district_ru.get("districts", {}).get(client.region, {})
    else:
        with open(
            BASE_DIR / "locales" / "district_uz.json", "r", encoding="utf-8"
        ) as f:
            district_uz = json.load(f)
            district_uz = district_uz.get("districts", {}).get(client.region, {})

    # Get referral count
    referral_count = await client_service.count_referrals(client.telegram_id, session)

    # Format data
    full_name = client.full_name or _("not-provided")
    phone = client.phone or _("not-provided")
    client_code = client.primary_code or _("not-provided")
    passport_series = client.passport_series or _("not-provided")
    pinfl = client.pinfl or _("not-provided")
    dob = (
        client.date_of_birth.strftime("%d.%m.%Y")
        if client.date_of_birth
        else _("not-provided")
    )
    region = f"{_(UZBEKISTAN_REGIONS.get(client.region, client.region))}, {district_ru.get(client.district, client.district) if client.language_code == 'ru' else district_uz.get(client.district, client.district)}"
    address = client.address or _("not-provided")
    created_at = (
        client.created_at.strftime("%d.%m.%Y %H:%M")
        if client.created_at
        else _("not-provided")
    )

    # Send profile info
    profile_text = _(
        "profile-info-with-referrals",
        full_name=full_name,
        telegram_id=str(client.telegram_id) or _("not-provided"),
        phone=phone,
        client_code=client_code,
        passport_series=passport_series,
        pinfl=pinfl,
        dob=dob,
        region=region,
        address=address,
        created_at=created_at,
        referral_count=str(referral_count),
    )

    # Send passport images if available (cascade strategy: never blocks profile text)
    if client.passport_images:
        try:
            images = json.loads(client.passport_images)
            if images:
                from src.infrastructure.tools.passport_image_resolver import (
                    resolve_passport_items,
                )

                resolved = await resolve_passport_items(images)
                await _send_profile_images(message, resolved)
        except (json.JSONDecodeError, Exception):
            await session.rollback()
            logger.warning(
                "Failed to parse passport_images JSON for user %s", client.telegram_id
            )

    # Send profile text with actions
    await message.answer(profile_text, reply_markup=profile_menu_kyb(translator=_))


@profile_router.message(
    IsPrivate(),
    ClientExists(),
    IsRegistered(),
    IsLoggedIn(),
    F.text.in_(["✏️ Tahrirlash", "✏️ Редактировать"]),
)
async def edit_profile_handler(message: Message, _: callable):
    """Show edit profile options."""
    await message.answer(
        _("profile-select-action"), reply_markup=edit_profile_kyb(translator=_)
    )


@profile_router.callback_query(F.data == "edit_name")
async def edit_name_callback(callback: CallbackQuery, state: FSMContext, _: callable):
    """Start editing name."""
    await callback.message.answer(_("profile-edit-name"))
    await state.set_state(EditProfileStates.waiting_for_name)
    await callback.answer()
    await callback.message.delete()


@profile_router.message(EditProfileStates.waiting_for_name)
async def process_edit_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    client_service: ClientService,
    _: callable,
):
    """Process new name."""
    new_name = message.text.strip()

    if len(new_name) < 2:
        await message.answer("❌ Ism kamida 2 ta harfdan iborat bo'lishi kerak!")
        return

    # Update client
    await client_service.update_client(
        telegram_id=message.from_user.id, data={"full_name": new_name}, session=session
    )
    await session.commit()

    await state.clear()
    await message.answer(_("profile-updated"))


@profile_router.callback_query(F.data == "edit_phone")
async def edit_phone_callback(callback: CallbackQuery, state: FSMContext, _: callable):
    """Start editing phone."""
    await callback.message.answer(_("profile-edit-phone"))
    await state.set_state(EditProfileStates.waiting_for_phone)
    await callback.answer()
    await callback.message.delete()


@profile_router.message(EditProfileStates.waiting_for_phone)
async def process_edit_phone(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    client_service: ClientService,
    _: callable,
):
    """Process new phone."""
    new_phone = message.text.strip()

    # Basic phone validation
    if not new_phone.startswith("+"):
        await message.answer("❌ Telefon raqami + belgisi bilan boshlanishi kerak!")
        return

    if len(new_phone) < 10:
        await message.answer("❌ Telefon raqami noto'g'ri!")
        return

    # Update client
    await client_service.update_client(
        telegram_id=message.from_user.id, data={"phone": new_phone}, session=session
    )
    await session.commit()

    await state.clear()
    await message.answer(_("profile-updated"))


@profile_router.callback_query(F.data == "edit_cancel")
async def edit_cancel_callback(callback: CallbackQuery, state: FSMContext, _: callable):
    """Cancel edit."""
    await state.clear()
    await callback.message.delete()
    await callback.answer(_("add-passport-cancelled"))


@profile_router.message(
    IsPrivate(),
    ClientExists(),
    IsLoggedIn(),
    F.text.in_(["🚪 Tizimdan chiqish", "🚪 Выйти из системы"]),
)
async def logout_handler(message: Message, _: callable):
    """Show logout confirmation."""
    await message.answer(
        _("profile-logout-confirm"), reply_markup=logout_confirm_kyb(translator=_)
    )


@profile_router.callback_query(F.data == "logout_confirm_yes")
async def logout_confirm_yes(
    callback: CallbackQuery,
    session: AsyncSession,
    client_service: ClientService,
    _: callable,
):
    """Confirm logout."""
    # Update is_logged_in to False
    await client_service.update_client(
        telegram_id=callback.from_user.id, data={"is_logged_in": False}, session=session
    )
    await session.commit()

    await callback.message.delete()
    await callback.message.answer(
        _("profile-logged-out"), reply_markup=ReplyKeyboardRemove()
    )
    await callback.answer()


@profile_router.callback_query(F.data == "logout_confirm_no")
async def logout_confirm_no(callback: CallbackQuery, _: callable):
    """Cancel logout."""
    await callback.message.delete()
    await callback.answer(_("add-passport-cancelled"))


@profile_router.message(
    IsPrivate(),
    ClientExists(),
    IsRegistered(),
    IsLoggedIn(),
    F.text.in_(["⏰ To'lov eslatmasi", "⏰ Напоминание об оплате"]),
)
@handle_errors
async def payment_reminder_handler(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
):
    """Show payment reminders for partial payments."""
    await state.clear()

    # Get client
    client = await client_service.get_client(message.from_user.id, session)
    if not client:
        await message.answer(_("error-occurred"))
        return

    # Get active partial transactions
    from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO

    transactions = await ClientTransactionDAO.get_by_telegram_id(
        session, client.telegram_id
    )

    # Filter for partial payments with remaining amount
    partial_transactions = [
        tx
        for tx in transactions
        if tx.payment_status == "partial" and float(tx.remaining_amount or 0) > 0
    ]

    if not partial_transactions:
        await message.answer(_("payment-reminder-none"))
        return

    # Build reminder message
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    reminder_parts = []
    builder = InlineKeyboardBuilder()

    for tx in partial_transactions:
        total = float(tx.total_amount) if tx.total_amount else float(tx.summa or 0)
        paid = float(tx.paid_amount) if tx.paid_amount else 0.0
        remaining = float(tx.remaining_amount) if tx.remaining_amount else 0.0
        deadline = (
            tx.payment_deadline.strftime("%Y-%m-%d %H:%M")
            if tx.payment_deadline
            else _("not-set")
        )

        reminder_text = _(
            "payment-reminder-item",
            flight=tx.reys,
            total=f"{total:,.0f}",
            paid=f"{paid:,.0f}",
            remaining=f"{remaining:,.0f}",
            deadline=deadline,
        )
        reminder_parts.append(reminder_text)

        # Add payment button for this flight
        builder.button(
            text=_("btn-make-payment-now") + f" - {tx.reys}",
            callback_data=f"pay_flight:{tx.reys}",
        )

    # Add warning text
    warning_text = _("payment-reminder-warning")
    reminder_parts.append(warning_text)

    full_message = "\n\n".join(reminder_parts)
    builder.adjust(1)

    await message.answer(full_message, reply_markup=builder.as_markup())


@profile_router.message(
    IsPrivate(),
    ClientExists(),
    IsLoggedIn(),
    F.text.in_(["🏠 Asosiy menyu", "🏠 Главное меню"]),
)
async def back_to_menu_handler(message: Message, _: callable, state: FSMContext):
    """Go back to main menu."""
    await state.clear()
    await message.answer(_("main-menu"), reply_markup=user_main_menu_kyb(translator=_))


@profile_router.callback_query(F.data == "edit_address")
async def edit_address_callback(
    callback: CallbackQuery, state: FSMContext, _: callable
):
    """Start editing address - first select region."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    for region_key, region_trans_key in UZBEKISTAN_REGIONS.items():
        builder.button(
            text=_(region_trans_key), callback_data=f"select_region:{region_key}"
        )
    builder.adjust(2)  # 2 buttons per row

    await callback.message.answer(
        _("profile-select-region"), reply_markup=builder.as_markup()
    )
    await state.set_state(EditProfileStates.waiting_for_region)
    await callback.answer()
    await callback.message.delete()


@profile_router.callback_query(
    EditProfileStates.waiting_for_region, F.data.startswith("select_region:")
)
async def process_region_selection(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    client_service: ClientService,
    _: callable,
):
    """Process region selection and ask for district."""
    region_key = callback.data.split(":")[1]

    # Store selected region in state
    await state.update_data(selected_region_key=region_key)

    # Load districts from JSON based on language
    client = await client_service.get_client(callback.from_user.id, session)
    lang = client.language_code if client else callback.from_user.language_code

    file_path = (
        "locales/district_ru.json" if lang == "ru" else "locales/district_uz.json"
    )
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            districts = data.get("districts", {}).get(region_key, {})
    except Exception as e:
        await session.rollback()
        logger.error(f"Error loading districts: {e}")
        districts = {}

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()

    for dist_key, dist_name in districts.items():
        builder.button(text=dist_name, callback_data=f"select_dist:{dist_key}")
    builder.adjust(2)

    await callback.message.edit_text(
        _("profile-select-district"), reply_markup=builder.as_markup()
    )
    await state.set_state(EditProfileStates.waiting_for_district_selection)
    await callback.answer()


@profile_router.callback_query(
    EditProfileStates.waiting_for_district_selection, F.data.startswith("select_dist:")
)
async def process_district_selection(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    client_service: ClientService,
    _: callable,
):
    """Process district selection and ask for address."""
    district_key = callback.data.split(":")[1]

    # Store selected district in state
    await state.update_data(selected_district_key=district_key)

    data = await state.get_data()
    region_key = data.get("selected_region_key")

    client = await client_service.get_client(callback.from_user.id, session)
    lang = client.language_code if client else callback.from_user.language_code

    file_path = (
        "locales/district_ru.json" if lang == "ru" else "locales/district_uz.json"
    )
    district_name = district_key
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)
            district_name = (
                json_data.get("districts", {})
                .get(region_key, {})
                .get(district_key, district_key)
            )
    except Exception as e:
        await session.rollback()
        logger.error(f"Error loading districts: {e}")

    region_name = _(UZBEKISTAN_REGIONS.get(region_key, region_key))

    await callback.message.edit_text(
        _("profile-enter-address", region=region_name, district=district_name)
    )
    await state.set_state(EditProfileStates.waiting_for_address)
    await callback.answer()


@profile_router.message(EditProfileStates.waiting_for_address)
async def process_address(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    client_service: ClientService,
    _: callable,
):
    """Process new address."""
    new_address = message.text.strip()

    if len(new_address) < 5:
        await message.answer(_("profile-address-too-short"))
        return

    # Get region and district from state
    data = await state.get_data()
    region_key = data.get("selected_region_key")
    district_key = data.get("selected_district_key")

    # Update client with region, district, and address
    await client_service.update_client(
        telegram_id=message.from_user.id,
        data={"region": region_key, "district": district_key, "address": new_address},
        session=session,
    )
    await session.commit()

    await state.clear()
    await message.answer(_("profile-address-updated"))


# Event type translation keys
EVENT_TYPE_KEYS = {
    "LOGIN": "event-login",
    "RELINK": "event-relink",
    "LOGOUT": "event-logout",
}


@profile_router.message(
    IsPrivate(),
    ClientExists(),
    IsRegistered(),
    IsLoggedIn(),
    F.text.in_(["📱 Qurilmalar", "📱 Устройства"]),
)
@handle_errors
async def devices_handler(
    message: Message,
    session: AsyncSession,
    client_service: ClientService,
    _: callable,
    state: FSMContext,
):
    """Show session history (devices/login events)."""
    await state.clear()
    client = await client_service.get_client(message.from_user.id, session)

    if not client:
        await message.answer(_("error-occurred"))
        return

    # Get session logs
    from src.infrastructure.database.dao.session_log import SessionLogDAO

    logs = await SessionLogDAO.get_by_client_id(session, client.id, limit=10)

    if not logs:
        await message.answer(_("devices-empty"))
        return

    # Build devices history message
    lines = [_("devices-title"), ""]

    for log in logs:
        local_dt = to_tashkent(log.created_at) if log.created_at else None
        date_str = local_dt.strftime("%d.%m.%Y %H:%M") if local_dt else "-"
        event_label = _(EVENT_TYPE_KEYS.get(log.event_type, log.event_type))
        code_display = log.client_code or "-"
        username_display = f" (@{log.username})" if log.username else ""
        lines.append(
            _(
                "devices-item",
                date=date_str,
                client_code=code_display,
                event_type=event_label,
            )
            + username_display
        )

    await message.answer("\n".join(lines))


@profile_router.callback_query(F.data.startswith("devices_page:"))
async def devices_pagination_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    client_service: ClientService,
    _: callable,
):
    """Handle pagination for devices history."""
    page = int(callback.data.split(":")[1])
    client = await client_service.get_client(callback.from_user.id, session)

    if not client:
        await callback.answer(_("error-occurred"))
        return

    from src.infrastructure.database.dao.session_log import SessionLogDAO

    logs = await SessionLogDAO.get_by_client_id(
        session, client.id, limit=5, offset=page * 5
    )

    if not logs:
        await callback.answer(_("devices-empty"))
        return

    lines = [_("devices-title"), ""]

    for log in logs:
        local_dt = to_tashkent(log.created_at) if log.created_at else None
        date_str = local_dt.strftime("%d.%m.%Y %H:%M") if local_dt else "-"
        event_label = _(EVENT_TYPE_KEYS.get(log.event_type, log.event_type))
        code_display = log.client_code or "-"
        username_display = f" (@{log.username})" if log.username else ""
        lines.append(
            _(
                "devices-item",
                date=date_str,
                client_code=code_display,
                event_type=event_label,
            )
            + username_display
        )

    await callback.message.edit_text("\n".join(lines))
    await callback.answer()
