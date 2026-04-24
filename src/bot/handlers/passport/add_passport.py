"""Add passport handler with FSM."""
import json
import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters import IsPrivate
from src.bot.keyboards.reply_kb.general_keyb import cancel_kyb
from src.bot.keyboards.user import user_main_menu_kyb
from src.bot.keyboards.user.reply_keyb.extra_passport_keyb import ask_for_document_type, save_and_cancel_kyb
from src.bot.states.add_passport import AddPassportStates
from src.bot.utils.decorators import handle_errors
from src.bot.utils.validators import (
    validate_uzbekistan_passport,
    validate_pinfl,
    validate_date_of_birth
)
from src.infrastructure.database.dao.client_extra_passport import ClientExtraPassportDAO
from src.infrastructure.services.client import ClientService
from src.infrastructure.tools.s3_manager import s3_manager
from src.infrastructure.tools.image_optimizer import optimize_image_to_webp
from datetime import date

logger = logging.getLogger(__name__)

add_passport_router = Router(name="add_passport")


@add_passport_router.message(F.text.in_(["🪪 Passport qo'shish", "🪪 Добавить паспорт"]), IsPrivate())
@handle_errors
async def start_add_passport(
    message: Message,
    state: FSMContext,
    _: callable
):
    """Start passport adding flow."""
    await state.set_state(AddPassportStates.waiting_for_passport_series)
    await message.answer(
        _("add-passport-start"),
        reply_markup=cancel_kyb(translator=_)
    )


@add_passport_router.message(AddPassportStates.waiting_for_passport_series)
@handle_errors
async def process_passport_series(
    message: Message,
    state: FSMContext,
    _: callable
):
    """Process passport series input."""
    # Check cancel
    if message.text == _("btn-cancel"):
        await state.clear()
        await message.answer(_("add-passport-cancelled"), reply_markup=user_main_menu_kyb(translator=_))
        return

    # Validate
    is_valid, error_msg = validate_uzbekistan_passport(message.text, translator=_)
    if not is_valid:
        await message.answer(f"❌ {error_msg}\n\n" + _("add-passport-start"))
        return

    # Save and next
    await state.update_data(passport_series=message.text.strip().upper().replace(" ", ""))
    await state.set_state(AddPassportStates.waiting_for_pinfl)
    await message.answer(_("add-passport-pinfl"))


@add_passport_router.message(AddPassportStates.waiting_for_pinfl)
@handle_errors
async def process_pinfl(
    message: Message,
    state: FSMContext,
    _: callable
):
    """Process PINFL input."""
    # Check cancel
    if message.text == _("btn-cancel"):
        await state.clear()
        await message.answer(_("add-passport-cancelled"), reply_markup=user_main_menu_kyb(translator=_))
        return

    # Validate
    is_valid, error_msg = validate_pinfl(message.text, translator=_)
    if not is_valid:
        await message.answer(f"❌ {error_msg}\n\n" + _("add-passport-pinfl"))
        return

    # Save and next
    await state.update_data(pinfl=message.text.strip().replace(" ", ""))
    await state.set_state(AddPassportStates.waiting_for_date_of_birth)
    await message.answer(_("add-passport-dob"))


@add_passport_router.message(AddPassportStates.waiting_for_date_of_birth)
@handle_errors
async def process_dob(
    message: Message,
    state: FSMContext,
    _: callable
):
    """Process date of birth input."""
    # Check cancel
    if message.text == _("btn-cancel"):
        await state.clear()
        await message.answer(_("add-passport-cancelled"), reply_markup=user_main_menu_kyb(translator=_))
        return

    # Validate
    is_valid, error_msg, birth_date = validate_date_of_birth(message.text, translator=_)
    if not is_valid:
        await message.answer(f"❌ {error_msg}\n\n" + _("add-passport-dob"))
        return

    # Save and next
    await state.update_data(date_of_birth=birth_date.isoformat())
    await state.set_state(AddPassportStates.waiting_for_document_type)

    # Ask for document type
    kb = ask_for_document_type(translator=_)
    await message.answer(_("add-passport-doc-type"), reply_markup=kb)


@add_passport_router.message(AddPassportStates.waiting_for_document_type)
@handle_errors
async def process_document_type(
    message: Message,
    state: FSMContext,
    _: callable
):
    """Process document type selection."""
    # Check cancel
    if message.text == _("btn-cancel"):
        await state.clear()
        await message.answer(_("add-passport-cancelled"), reply_markup=user_main_menu_kyb(translator=_))
        return

    # Determine type
    if message.text == _("add-passport-id-card"):
        doc_type = "id_card"
        prompt = _("add-passport-id-front")
    elif message.text == _("add-passport-passport"):
        doc_type = "passport"
        prompt = _("add-passport-passport-photo")
    else:
        await message.answer(_("add-passport-doc-type"))
        return

    await state.update_data(document_type=doc_type, passport_images=[])
    await state.set_state(AddPassportStates.waiting_for_images)
    await message.answer(prompt, reply_markup=cancel_kyb(translator=_),
)


@add_passport_router.message(AddPassportStates.waiting_for_images, F.photo)
@handle_errors
async def process_images(
    message: Message,
    state: FSMContext,
    _: callable
):
    """Process passport images."""
    data = await state.get_data()
    doc_type = data.get("document_type")
    images = data.get("passport_images", [])

    # Download photo from Telegram, optimize, and upload to S3
    try:
        file_io = await message.bot.download(message.photo[-1])
        raw_content = file_io.read()
        optimized = await optimize_image_to_webp(raw_content)
        s3_key = await s3_manager.upload_file(
            file_content=optimized,
            file_name=f"{doc_type}_{len(images)}.webp",
            telegram_id=message.from_user.id,
            client_code=None,
            base_folder="extra-passports",
            sub_folder=doc_type,
            content_type="image/webp",
        )
        images.append(s3_key)
    except Exception as e:
        logger.error(f"Failed to upload passport image to S3: {e}", exc_info=True)
        await message.answer(_("add-passport-photo-upload-error"))
        return

    # ID Card: need 2 photos
    if doc_type == "id_card":
        if len(images) == 1:
            await state.update_data(passport_images=images)
            await message.answer(_("add-passport-id-saved") + "\n\n" + _("add-passport-id-back"))
        elif len(images) == 2:
            await state.update_data(passport_images=images)
            await show_confirmation(message, state, _)
        else:
            await message.answer(text=_("add-passport-max-2-photo"))

    # Passport: need 1 photo
    elif doc_type == "passport":
        await state.update_data(passport_images=images[:1])
        await show_confirmation(message, state, _)


async def show_confirmation(message: Message, state: FSMContext, _: callable):
    """Show confirmation message."""
    data = await state.get_data()
    await state.set_state(AddPassportStates.confirm_save)

    kb = save_and_cancel_kyb(translator=_)

    await message.answer(
        _("add-passport-confirm",
          passport_series=data["passport_series"],
          pinfl=data["pinfl"],
          dob=data["date_of_birth"],
          image_count=len(data["passport_images"])),
        reply_markup=kb
    )


@add_passport_router.message(AddPassportStates.confirm_save)
@handle_errors
async def confirm_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    client_service: ClientService,
    _: callable
):
    """Confirm and save passport."""
    # Check cancel
    if message.text == _("btn-cancel"):
        await state.clear()
        await message.answer(_("add-passport-cancelled"), reply_markup=user_main_menu_kyb(translator=_))
        return

    # Check save
    if message.text != _("btn-save"):
        await message.answer(text=_("add-passport-please-select-kyb"))
        return

    # Get data
    data = await state.get_data()

    # Get client_code from database
    client = await client_service.get_client(message.from_user.id, session)
    client_code = client.client_code if client else None

    # Save to database
    try:
        # Convert ISO date string to date object
        dob = date.fromisoformat(data["date_of_birth"])

        # Check for duplicates in client_extra_passports
        conflicts_extra = await ClientExtraPassportDAO.check_duplicate_passport(
            session=session,
            passport_series=data["passport_series"],
            pinfl=data["pinfl"],
            telegram_id=message.from_user.id
        )

        # Check for duplicates in main Client table
        conflicts_main = await ClientExtraPassportDAO.check_duplicate_in_main_passport(
            session=session,
            passport_series=data["passport_series"],
            pinfl=data["pinfl"],
            telegram_id=message.from_user.id
        )

        # Merge conflicts
        has_conflicts = any(conflicts_extra.values()) or any(conflicts_main.values())

        if has_conflicts:
            conflict_msgs = []
            if conflicts_extra.get('passport_series') or conflicts_main.get('passport_series'):
                conflict_msgs.append(_("passport-duplicate-series"))
            if conflicts_extra.get('pinfl') or conflicts_main.get('pinfl'):
                conflict_msgs.append(_("passport-duplicate-pinfl"))

            await message.answer(
                _("passport-duplicate-error") + "\n" + "\n".join(conflict_msgs),
                reply_markup=user_main_menu_kyb(translator=_)
            )
            await state.clear()
            return

        passport_data = {
            "telegram_id": message.from_user.id,
            "client_code": client_code,
            "passport_series": data["passport_series"],
            "pinfl": data["pinfl"],
            "date_of_birth": dob,  # date object, not string
            "passport_images": json.dumps(data["passport_images"])
        }

        await ClientExtraPassportDAO.create(session, passport_data)
        await session.commit()

        await state.clear()
        await message.answer(_("add-passport-success"), reply_markup=user_main_menu_kyb(translator=_))

    except Exception as e:
        await session.rollback()
        logger.error(f"Error saving passport: {e}", exc_info=True)
        await message.answer(_("add-passport-error"), reply_markup=user_main_menu_kyb(translator=_))
        await state.clear()
