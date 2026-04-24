"""Admin client search handlers."""

import json
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters import IsAdmin, IsPrivate
from src.bot.handlers.user.delivery_request import UZBEKISTAN_REGIONS
from src.bot.keyboards import back_kyb
from src.bot.states import AdminClientSearchStates
from src.bot.utils.decorators import handle_errors
from src.config import config, BASE_DIR
from src.infrastructure.database.dao import (
    ClientDAO,
    ClientTransactionDAO,
    ClientExtraPassportDAO,
)
from src.infrastructure.services import ClientService

logger = logging.getLogger(__name__)
client_search_router = Router()


def get_client_webapp_keyboard(
    client_id: int | None, _: callable
) -> InlineKeyboardMarkup:
    """
    Generate WebApp keyboard based on client existence.

    Args:
        client_id: Client ID if exists, None if not found
        _: i18n translation function

    Returns:
        InlineKeyboardMarkup
    """
    kb = InlineKeyboardBuilder()

    if client_id is None:
        # ➕ Client yo‘q → Add
        kb.button(
            text=_("btn-add-client"),
            web_app=WebAppInfo(url=config.telegram.webapp_client_add),
        )
    else:
        # ✏️ Client bor → Edit + Delete
        kb.button(
            text=_("btn-edit-client"),
            web_app=WebAppInfo(url=f"{config.telegram.webapp_client_edit(client_id)}"),
        )
        kb.button(
            text=_("btn-view-client"),
            web_app=WebAppInfo(
                url=f"{config.telegram.webapp_verification_search_user(client_id)}"
            ),
        )
        kb.button(
            text=_("btn-delete-client"),
            callback_data=f"admin:delete_client:{client_id}",
        )

    # Tugmalarni 2 tadan joylashtirish
    kb.adjust(1)

    return kb.as_markup()


@client_search_router.message(
    IsAdmin(),
    IsPrivate(),
    F.text.in_(["👤 Foydalanuvchi qidirish", "👤 Поиск пользователя"]),
)
@handle_errors
async def handle_search_user_start_callback(
    message: Message, state: FSMContext, _: callable
) -> None:
    """Start client search process from callback - ask for client code."""
    logger.info(f"Admin {message.from_user.id} started client search")

    await state.set_state(AdminClientSearchStates.waiting_for_client_code)

    await message.delete()

    await message.answer(text=_("admin-search-title"), reply_markup=back_kyb(_))


@client_search_router.message(
    AdminClientSearchStates.waiting_for_client_code, IsAdmin()
)
@handle_errors
async def handle_client_code_input(
    message: Message,
    state: FSMContext,
    client_service: ClientService,
    session: AsyncSession,
    _: callable,
) -> None:
    """Process client code or phone number input and display client information."""
    query = message.text.strip()

    # Check if this looks like a phone number (contains mostly digits)
    digits_only = "".join(c for c in query if c.isdigit())
    is_phone_query = len(digits_only) >= 7  # Phone numbers have at least 7 digits

    client = None
    search_query = query  # For error messages

    if is_phone_query:
        # Search by phone number
        logger.info(f"Admin searching for client by phone: {query}")
        client = await ClientDAO.search_by_client_code_or_phone(session, query)
        search_query = query
    else:
        # Search by client code
        logger.info(f"Admin searching for client by code: {query}")
        client_code = query.upper()
        client = await ClientDAO.get_by_client_code(session, client_code)

    # Clear state
    # await state.clear()

    if not client:
        # Client not found
        await message.answer(
            text=_("admin-search-not-found", code=search_query),
            reply_markup=get_client_webapp_keyboard(None, _),
        )
        return

    # Client found - gather all information

    # 1. Get transaction count and latest transaction.
    # A client may have transactions stored under any of their known codes
    # (client_code, extra_code, legacy_code), so we query all of them at once.
    # include_hidden=True lets admins see pending/debt transactions too.
    all_known_codes = [
        c for c in [client.client_code, client.extra_code, client.legacy_code] if c
    ]
    transactions = await ClientTransactionDAO.get_by_client_code(
        session, all_known_codes, include_hidden=True
    )
    transaction_count = len(transactions)
    latest_transaction = transactions[0] if transactions else None

    # 2. Get extra passports count
    extra_passports_count = await ClientExtraPassportDAO.count_by_client_code(
        session, client.client_code
    )

    # 3. Format client information
    info_text = _("admin-search-found") + "\n\n"
    referral_count = await client_service.count_referrals(client.telegram_id, session)
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

    full_address = f"{district_uz.get(client.district, client.district) if client.language_code == 'uz' else district_ru.get(client.district, client.district)}, {client.address}"

    # Basic info
    info_text += _(
        "admin-search-basic-info",
        code=client.client_code,
        new_code=client.extra_code or _("not-provided"),
        legacy_code=client.legacy_code or _("not-provided"),
        telegram_id=str(client.telegram_id) or _("not-provided"),
        name=client.full_name,
        phone=client.phone or _("not-provided"),
        birthday=str(client.date_of_birth)
        if client.date_of_birth
        else _("not-provided"),
        passport=client.passport_series or _("not-provided"),
        pinfl=client.pinfl or _("not-provided"),
        region=UZBEKISTAN_REGIONS.get(client.region, _("not-provided"))
        if client.region
        else _("not-provided"),
        address=full_address or _("not-provided"),
        referral_count=str(referral_count),
        created=client.created_at.strftime("%Y-%m-%d %H:%M"),
    )

    info_text += "\n\n"

    # Transaction info
    info_text += _("admin-search-payments-info", count=transaction_count)

    if latest_transaction:
        info_text += "\n\n"
        info_text += _(
            "admin-search-last-payment",
            flight=latest_transaction.reys,
            row=latest_transaction.qator_raqami,
            amount=latest_transaction.summa,
            date=latest_transaction.created_at.strftime("%Y-%m-%d %H:%M"),
        )

        # Payment receipt info
        if latest_transaction.payment_receipt_file_id:
            info_text += "\n" + _("admin-search-has-payment-receipt")

        # Cargo pickup status
        if latest_transaction.is_taken_away:
            taken_date = (
                latest_transaction.taken_away_date.strftime("%Y-%m-%d %H:%M")
                if latest_transaction.taken_away_date
                else _("unknown")
            )
            info_text += "\n" + _("admin-search-cargo-taken", date=taken_date)
        else:
            info_text += "\n" + _("admin-search-cargo-not-taken")

    # Extra passports info
    info_text += "\n\n"
    info_text += _("admin-search-extra-passports", count=extra_passports_count)

    # Prepare keyboard
    keyboard = get_client_webapp_keyboard(client.id, _)

    # Send passport images if available (silent fail pattern)
    images_sent = False
    if client.passport_images:
        try:
            file_ids = json.loads(client.passport_images)
            if file_ids:
                from src.infrastructure.tools.passport_image_resolver import (
                    resolve_passport_items,
                )

                resolved = await resolve_passport_items(file_ids)
                # Send images as album with caption
                media_group = [
                    InputMediaPhoto(media=ref, caption=info_text if i == 0 else "")
                    for i, ref in enumerate(resolved)
                ]

                # Send album
                await message.answer_media_group(media=media_group)
                images_sent = True

                # Send keyboard in separate message
                await message.answer(
                    text=_("admin-search-passport-images"), reply_markup=keyboard
                )
        except Exception as e:
            await session.rollback()
            # Silent fail: log error, do NOT notify user
            logger.warning(f"Silently failed to send passport images: {e}")
            images_sent = False

    # Fallback: Send text-only message if images weren't sent
    if not images_sent:
        await message.answer(text=info_text, reply_markup=keyboard)


@client_search_router.callback_query(
    F.data.startswith("admin:delete_client:"), IsAdmin()
)
@handle_errors
async def handle_delete_client_confirmation(
    callback_query: CallbackQuery, session: AsyncSession, _: callable
) -> None:
    """Show delete confirmation dialog."""
    client_id = int(callback_query.data.split(":")[2])

    client = await ClientDAO.get_by_id(session, client_id)

    if not client:
        await callback_query.answer(_("admin-delete-not-found"), show_alert=True)
        return

    # Store client data in callback_data for going back
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_("btn-confirm-delete"),
            callback_data=f"admin:confirm_delete:{client_id}",
        ),
        InlineKeyboardButton(
            text=_("btn-cancel-delete"), callback_data=f"admin:show_client:{client_id}"
        ),
    )

    await callback_query.message.edit_text(
        text=_("admin-delete-confirm", name=client.full_name, code=client.client_code),
        reply_markup=builder.as_markup(),
    )
    await callback_query.answer()


@client_search_router.callback_query(F.data.startswith("admin:show_client:"), IsAdmin())
@handle_errors
async def handle_show_client_details(
    callback_query: CallbackQuery,
    client_service: ClientService,
    session: AsyncSession,
    _: callable,
) -> None:
    """Show client details after canceling delete."""
    client_id = int(callback_query.data.split(":")[2])

    client = await ClientDAO.get_by_id(session, client_id)

    if not client:
        await callback_query.answer(_("admin-delete-not-found"), show_alert=True)
        return

    # Get transaction count and latest transaction across all known client codes.
    all_known_codes = [
        c for c in [client.client_code, client.extra_code, client.legacy_code] if c
    ]
    transactions = await ClientTransactionDAO.get_by_client_code(
        session, all_known_codes, include_hidden=True
    )
    transaction_count = len(transactions)
    latest_transaction = transactions[0] if transactions else None

    # Get extra passports count
    extra_passports_count = await ClientExtraPassportDAO.count_by_client_code(
        session, client.client_code
    )

    # Get referral count
    referral_count = await client_service.count_referrals(client.telegram_id, session)

    # Format client information
    info_text = _("admin-search-found") + "\n\n"

    # Basic info
    info_text += _(
        "admin-search-basic-info",
        code=client.client_code,
        new_code=client.extra_code or _("not-provided"),
        legacy_code=client.legacy_code or _("not-provided"),
        telegram_id=client.telegram_id or _("not-provided"),
        name=client.full_name,
        phone=client.phone or _("not-provided"),
        birthday=str(client.date_of_birth)
        if client.date_of_birth
        else _("not-provided"),
        passport=client.passport_series or _("not-provided"),
        pinfl=client.pinfl or _("not-provided"),
        region=client.region or _("not-provided"),
        address=client.address or _("not-provided"),
        referral_count=str(referral_count),
        created=client.created_at.strftime("%Y-%m-%d %H:%M"),
    )

    info_text += "\n\n"

    # Transaction info
    info_text += _("admin-search-payments-info", count=transaction_count)

    if latest_transaction:
        info_text += "\n\n"
        info_text += _(
            "admin-search-last-payment",
            flight=latest_transaction.reys,
            row=latest_transaction.qator_raqami,
            amount=latest_transaction.summa,
            date=latest_transaction.created_at.strftime("%Y-%m-%d %H:%M"),
        )

        # Payment receipt info
        if latest_transaction.payment_receipt_file_id:
            info_text += "\n" + _("admin-search-has-payment-receipt")

        # Cargo pickup status
        if latest_transaction.is_taken_away:
            taken_date = (
                latest_transaction.taken_away_date.strftime("%Y-%m-%d %H:%M")
                if latest_transaction.taken_away_date
                else _("unknown")
            )
            info_text += "\n" + _("admin-search-cargo-taken", date=taken_date)
        else:
            info_text += "\n" + _("admin-search-cargo-not-taken")

    # Extra passports info
    info_text += "\n\n"
    info_text += _("admin-search-extra-passports", count=extra_passports_count)

    await callback_query.message.edit_text(
        text=info_text, reply_markup=get_client_webapp_keyboard(client.id, _)
    )
    await callback_query.answer()


@client_search_router.callback_query(
    F.data.startswith("admin:confirm_delete:"), IsAdmin()
)
@handle_errors
async def handle_delete_client_confirmed(
    callback_query: CallbackQuery, session: AsyncSession, _: callable
) -> None:
    """Delete client after confirmation."""
    client_id = int(callback_query.data.split(":")[2])

    client = await ClientDAO.get_by_id(session, client_id)

    if not client:
        await callback_query.answer(_("admin-delete-not-found"), show_alert=True)
        return

    client_name = client.full_name
    client_code = client.client_code

    # Delete client
    await ClientDAO.delete(session, client)
    await session.commit()

    logger.info(f"Admin {callback_query.from_user.id} deleted client {client_code}")

    await callback_query.message.edit_text(
        text=_("admin-delete-success", name=client_name, code=client_code)
    )
    await callback_query.answer(_("btn-confirm-delete"))
