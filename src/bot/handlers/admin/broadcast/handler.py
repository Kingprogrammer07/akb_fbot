"""Broadcast handler - Admin announcement system."""

import asyncio
import json
import time

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_admin import IsAdmin
from src.bot.filters.is_private_chat import IsPrivate
from src.bot.handlers.admin.broadcast.states import BroadcastStates
from src.bot.handlers.admin.flight_notify import FlightNotifyStates, render_flight_list
from src.bot.handlers.admin.broadcast.constants import (
    ERROR_MESSAGES, SUCCESS_MESSAGES, STATUS_EMOJIS, MAX_ALBUM_SIZE
)
from src.bot.handlers.admin.broadcast.models import BroadcastContent, BroadcastButton
from src.bot.handlers.admin.broadcast.utils import (
    calculate_broadcast_time, parse_media_from_message,
    serialize_buttons, get_media_type_display, validate_and_fix_url,
    entities_to_telegram_format
)
from src.bot.handlers.admin.broadcast.keyboards import BroadcastKeyboards
from src.bot.handlers.admin.broadcast.sender import BroadcastSender
from src.bot.utils.decorators import handle_errors
from src.infrastructure.database.dao.broadcast import BroadcastDAO
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.models.broadcast import BroadcastStatus

router = Router(name="broadcast")

# Active broadcasts tracking
active_broadcasts: dict[str, dict] = {}


@router.message(F.text.in_(["📢 Reklama yuborish", "📢 Отправить рекламу"]), IsPrivate(), IsAdmin())
@handle_errors
async def show_broadcast_menu(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Display broadcast main menu with statistics."""
    await state.clear()
    
    total_users = await ClientDAO.count_all(session)
    time_estimate = calculate_broadcast_time(total_users)
    
    text = (
        "📢 <b>Reklama yuborish tizimi</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total_users:,}</b>\n"
        f"⏱ Taxminiy vaqt: <b>{time_estimate['formatted']}</b>\n"
        f"📅 Tugash vaqti: <b>{time_estimate['estimated_completion'].strftime('%H:%M:%S')}</b>\n\n"
        "Quyidagi amallardan birini tanlang:"
    )
    
    await message.answer(
        text,
        reply_markup=BroadcastKeyboards.main_menu(total_users),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "broadcast_create", IsAdmin())
async def start_broadcast_creation(callback: CallbackQuery, state: FSMContext):
    """Initialize broadcast creation flow."""
    await callback.answer()

    # Initialize empty broadcast content as dict (JSON serializable)
    empty_content = BroadcastContent()
    await state.update_data(content=empty_content.to_dict())

    text = (
        "🎯 <b>Reklama yaratish</b>\n\n"
        "Kimga yuborilsin?"
    )

    await callback.message.edit_text(
        text,
        reply_markup=BroadcastKeyboards.audience_selection(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.selecting_audience)


@router.callback_query(F.data.startswith("broadcast_audience_"), IsAdmin())
async def handle_audience_selection(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Handle audience type selection."""
    await callback.answer()

    audience_type = callback.data.replace("broadcast_audience_", "")
    data = await state.get_data()
    content = BroadcastContent.from_dict(data.get("content", {}))
    content.audience_type = audience_type

    if audience_type == "all":
        # For all users, go directly to media selection
        await state.update_data(content=content.to_dict())
        await show_media_type_selection(callback.message, state)

    elif audience_type == "selected":
        # Ask for client codes
        await state.update_data(content=content.to_dict())

        prompt = (
            "📝 <b>Client kodlarini kiriting</b>\n\n"
            "Bir yoki bir nechta client kodini vergul bilan ajratib yuboring.\n\n"
            "<i>Masalan:</i>\n"
            "<code>ss501</code> - bitta client\n"
            "<code>ss501, ss502, ss503</code> - bir nechta client"
        )

        await callback.message.edit_text(prompt, parse_mode="HTML")
        await state.set_state(BroadcastStates.waiting_for_client_codes)

    elif audience_type == "flight":
        # Hand off to the flight-notify FSM — clear broadcast content first
        await state.set_state(FlightNotifyStates.selecting_flight)
        await state.update_data(fn_page=0)
        await render_flight_list(callback.message, state, session, edit=True)


@router.message(BroadcastStates.waiting_for_client_codes, IsAdmin())
async def handle_client_codes_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Process client codes input."""
    data = await state.get_data()
    content = BroadcastContent.from_dict(data.get("content", {}))

    # Parse client codes from input
    raw_codes = message.text.strip().upper()
    client_codes = [code.strip() for code in raw_codes.replace(",", " ").split() if code.strip()]

    if not client_codes:
        await message.answer("❌ Client kod kiritilmadi. Iltimos, qaytadan kiriting.")
        return

    # Get clients from database
    clients = await ClientDAO.get_by_client_codes(session, client_codes)

    if not clients:
        await message.answer(
            f"❌ Kiritilgan client kod(lar) topilmadi.\n\n"
            f"Kiritilgan: <code>{', '.join(client_codes)}</code>",
            parse_mode="HTML"
        )
        return

    # Save normalized client codes to match database format
    found_codes = [client.client_code for client in clients]
    content.target_client_codes = found_codes
    await state.update_data(content=content.to_dict())

    # Compare normalized versions to find not found codes
    normalized_input = [code.strip().lower() for code in client_codes]
    normalized_found = [code.lower() for code in found_codes]
    not_found_normalized = set(normalized_input) - set(normalized_found)

    # Get original case versions of not found codes
    not_found = [code for code in client_codes if code.strip().lower() in not_found_normalized]

    response = f"✅ <b>{len(clients)} ta client topildi:</b>\n"
    for client in clients:
        response += f"• {client.client_code} - {client.full_name or 'Nomsiz'}\n"

    if not_found:
        response += f"\n⚠️ Topilmadi: <code>{', '.join(not_found)}</code>"

    await message.answer(response, parse_mode="HTML")

    # Proceed to media selection
    await show_media_type_selection(message, state)


async def show_media_type_selection(message: Message, state: FSMContext):
    """Show media type selection menu."""
    text = (
        "📤 <b>Reklama yaratish</b>\n\n"
        "Quyidagi formatlardan birini tanlang:\n\n"
        "📸 <b>Rasm</b> - Bitta yoki albom\n"
        "🎬 <b>Video</b> - Bitta yoki albom\n"
        "📄 <b>Hujjat</b> - Bitta yoki albom\n"
        "🎵 <b>Audio</b> - Bitta yoki albom\n"
        "🎤 <b>Ovozli xabar</b>\n"
        "💬 <b>Matn</b>\n\n"
        "Yoki media yuborib, tavsif qo'shing!"
    )

    await message.answer(
        text,
        reply_markup=BroadcastKeyboards.media_type_selection(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.selecting_media_type)


@router.callback_query(F.data.startswith("broadcast_media_"), IsAdmin())
async def handle_media_type_selection(
    callback: CallbackQuery,
    state: FSMContext
):
    """Process media type selection."""
    await callback.answer()
    
    media_type = callback.data.replace("broadcast_media_", "")
    data = await state.get_data()
    content = BroadcastContent.from_dict(data.get("content", {}))
    content.media_type = media_type
    
    await state.update_data(content=content.to_dict())
    
    if media_type == "text":
        await callback.message.edit_text(
            "📝 Matn xabaringizni yuboring:",
            parse_mode="HTML"
        )
        await state.set_state(BroadcastStates.waiting_for_caption)
    else:
        media_name = get_media_type_display(media_type)
        text = (
            f"📤 Iltimos, <b>{media_name}</b> yuboring.\n\n"
            "💡 <i>Bir nechta media yuborish uchun ularni "
            "albom sifatida bir vaqtda yuboring.</i>"
        )
        
        await callback.message.edit_text(text, parse_mode="HTML")
        await state.set_state(BroadcastStates.waiting_for_media)


@router.message(BroadcastStates.waiting_for_media, IsAdmin())
async def handle_media_upload(message: Message, state: FSMContext, **kwargs):
    """Process first uploaded media file (step-by-step collection)."""
    data = await state.get_data()
    content = BroadcastContent.from_dict(data.get("content", {}))

    # Parse media from single message
    new_content = parse_media_from_message(message)

    # Handle forwarded messages
    if new_content.is_forward():
        content.media_type = "forward"
        content.forward_from_chat_id = new_content.forward_from_chat_id
        content.forward_message_id = new_content.forward_message_id
        content.caption = new_content.caption
        await state.update_data(content=content.to_dict())

        # Go directly to buttons for forwarded messages
        text = (
            "🔘 <b>Inline tugmalar</b>\n\n"
            "Tugmalar havola (URL) yoki callback bo'lishi mumkin.\n"
            "Tugma qo'shmoqchimisiz?"
        )

        await message.answer(
            text,
            reply_markup=BroadcastKeyboards.button_options(),
            parse_mode="HTML"
        )
        await state.set_state(BroadcastStates.adding_buttons)
        return

    # Validate media
    if not new_content.file_ids:
        await message.answer(ERROR_MESSAGES["no_media"])
        return

    # Append media to content list
    content.file_ids.extend(new_content.file_ids)
    # Keep the base media type (without _album suffix) from first media
    if not content.file_ids or len(content.file_ids) == len(new_content.file_ids):
        content.media_type = new_content.media_type.replace("_album", "")
    # Save caption from first media if present
    if new_content.caption and not content.caption:
        content.caption = new_content.caption

    count = len(content.file_ids)
    await state.update_data(content=content.to_dict())

    # If at limit, auto-proceed to caption
    if count >= MAX_ALBUM_SIZE:
        content.media_type = content.media_type.replace("_album", "") + "_album"
        await state.update_data(content=content.to_dict())
        await message.answer(
            f"✅ {count} ta media qabul qilindi (maksimal)!\n\nCaption qo'shmoqchimisiz?",
            reply_markup=BroadcastKeyboards.caption_options()
        )
        await state.set_state(BroadcastStates.waiting_for_caption)
        return

    # Show add more / finish menu
    await message.answer(
        f"✅ {count}-media qabul qilindi. Yana qo'shasizmi?",
        reply_markup=BroadcastKeyboards.media_collection_menu(count)
    )


@router.callback_query(F.data == "broadcast_add_media", IsAdmin())
async def handle_add_media_callback(callback: CallbackQuery, state: FSMContext):
    """Admin clicked 'Add More' — prompt for next media."""
    await callback.answer()

    data = await state.get_data()
    content = BroadcastContent.from_dict(data.get("content", {}))
    count = len(content.file_ids)
    remaining = MAX_ALBUM_SIZE - count

    await callback.message.edit_text(
        f"📤 Keyingi media yuboring ({count}/{MAX_ALBUM_SIZE}).\n"
        f"Yana {remaining} ta qo'shish mumkin.",
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_for_next_media)


@router.message(BroadcastStates.waiting_for_next_media, IsAdmin())
async def handle_next_media_upload(message: Message, state: FSMContext):
    """Process additional media item in step-by-step collection."""
    data = await state.get_data()
    content = BroadcastContent.from_dict(data.get("content", {}))

    new_content = parse_media_from_message(message)
    if not new_content.file_ids:
        await message.answer(ERROR_MESSAGES["no_media"])
        return

    # Append file IDs
    content.file_ids.extend(new_content.file_ids)
    count = len(content.file_ids)
    await state.update_data(content=content.to_dict())

    # Auto-proceed at limit
    if count >= MAX_ALBUM_SIZE:
        content.media_type = content.media_type.replace("_album", "") + "_album"
        await state.update_data(content=content.to_dict())
        await message.answer(
            f"✅ {count} ta media qabul qilindi (maksimal)!\n\nCaption qo'shmoqchimisiz?",
            reply_markup=BroadcastKeyboards.caption_options()
        )
        await state.set_state(BroadcastStates.waiting_for_caption)
        return

    # Show updated menu
    await message.answer(
        f"✅ {count}-media qabul qilindi. Yana qo'shasizmi?",
        reply_markup=BroadcastKeyboards.media_collection_menu(count)
    )


@router.callback_query(F.data == "broadcast_finish_media", IsAdmin())
async def handle_finish_media_callback(callback: CallbackQuery, state: FSMContext):
    """Admin clicked 'Finish' — finalize media list and proceed to caption."""
    await callback.answer()

    data = await state.get_data()
    content = BroadcastContent.from_dict(data.get("content", {}))

    # Set album type if multiple files collected
    if len(content.file_ids) > 1:
        base_type = content.media_type.replace("_album", "")
        content.media_type = f"{base_type}_album"
    # else keep single media type as-is

    await state.update_data(content=content.to_dict())

    count = len(content.file_ids)
    await callback.message.edit_text(
        f"✅ {count} ta media tayyor!\n\nCaption qo'shmoqchimisiz?",
        parse_mode="HTML"
    )
    await callback.message.answer(
        "Caption tanlang:",
        reply_markup=BroadcastKeyboards.caption_options()
    )
    await state.set_state(BroadcastStates.waiting_for_caption)


@router.callback_query(F.data == "broadcast_add_caption", IsAdmin())
async def prompt_for_caption(callback: CallbackQuery, state: FSMContext):
    """Prompt user to enter caption text."""
    await callback.answer()
    await callback.message.delete()
    await callback.message.answer("📝 Caption matnini yuboring:")
    await state.set_state(BroadcastStates.waiting_for_caption)


@router.callback_query(F.data == "broadcast_skip_caption", IsAdmin())
async def skip_caption_entry(callback: CallbackQuery, state: FSMContext):
    """Skip caption and proceed to buttons."""
    await callback.answer()
    await callback.message.delete()
    
    text = (
        "🔘 <b>Inline tugmalar</b>\n\n"
        "Tugmalar havola (URL) yoki callback bo'lishi mumkin.\n"
        "Tugma qo'shmoqchimisiz?"
    )
    
    await callback.message.answer(
        text,
        reply_markup=BroadcastKeyboards.button_options(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.adding_buttons)


@router.message(BroadcastStates.waiting_for_caption, IsAdmin())
async def handle_caption_input(message: Message, state: FSMContext):
    """Process caption text input."""
    data = await state.get_data()
    content = BroadcastContent.from_dict(data.get("content", {}))

    # Update caption
    new_caption = message.text or message.caption or ""
    if new_caption:
        content.caption = new_caption

        # Extract and save entities (formatting)
        entities = None
        if message.caption_entities:
            entities = [entity.model_dump() for entity in message.caption_entities]
        elif message.entities:
            entities = [entity.model_dump() for entity in message.entities]
        content.caption_entities = entities

        await state.update_data(content=content.to_dict())
        await message.answer(
            SUCCESS_MESSAGES["caption_saved"] + "\n\nInline tugmalar qo'shmoqchimisiz?",
            reply_markup=BroadcastKeyboards.button_options()
        )
        await state.set_state(BroadcastStates.adding_buttons)
    else:
        await message.answer(
            "Caption bo'sh bo'lishi mumkin emas. Iltimos, matn yuboring yoki 'O'tkazib yuborish' tugmasini bosing."
        )


async def ask_for_buttons(message: Message, state: FSMContext):
    """Ask if user wants to add inline buttons."""
    text = (
        "🔘 <b>Inline tugmalar</b>\n\n"
        "Tugmalar havola (URL) yoki callback bo'lishi mumkin.\n"
        "Tugma qo'shmoqchimisiz?"
    )
    
    await message.answer(
        text,
        reply_markup=BroadcastKeyboards.button_options(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.adding_buttons)


@router.callback_query(F.data == "broadcast_add_button", IsAdmin())
async def prompt_for_button_text(callback: CallbackQuery, state: FSMContext):
    """Prompt for button text."""
    await callback.answer()
    
    await callback.message.edit_text(
        "📝 Tugma matnini yuboring:\n\n"
        "<i>Masalan:</i> <code>Websaytga o'tish</code>",
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_for_button_text)


@router.message(BroadcastStates.waiting_for_button_text, IsAdmin())
async def handle_button_text_input(message: Message, state: FSMContext):
    """Process button text and ask for URL."""
    await state.update_data(temp_button_text=message.text)
    
    await message.answer(
        "🔗 Tugma uchun URL yuboring:\n\n"
        "<i>URL uchun:</i> <code>https://example.com</code>\n"
        "<i>Callback uchun:</i> <code>callback:action_123</code>",
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_for_button_url)


@router.message(BroadcastStates.waiting_for_button_url, IsAdmin())
async def handle_button_url_input(message: Message, state: FSMContext):
    """Process button URL and save button."""
    data = await state.get_data()
    content = BroadcastContent.from_dict(data.get("content", {}))
    button_text = data.get("temp_button_text", "Button")
    button_url = message.text.strip()

    # Create button
    if button_url.startswith("callback:"):
        button = BroadcastButton(
            text=button_text,
            callback_data=button_url.replace("callback:", "")
        )
    else:
        # Validate and fix URL format
        button_url = validate_and_fix_url(button_url)
        button = BroadcastButton(text=button_text, url=button_url)

    content.buttons.append(button)
    await state.update_data(content=content.to_dict())

    # Show added buttons
    buttons_list = "\n".join([f"• {btn.text}" for btn in content.buttons])
    text = (
        f"{SUCCESS_MESSAGES['button_added']}\n\n"
        f"<b>Tugmalar:</b>\n{buttons_list}\n\n"
        "Yana tugma qo'shmoqchimisiz?"
    )

    await message.answer(
        text,
        reply_markup=BroadcastKeyboards.more_buttons(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.adding_buttons)


@router.callback_query(F.data == "broadcast_skip_buttons", IsAdmin())
async def finalize_and_preview(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
):
    """Skip buttons and show broadcast preview."""
    await callback.answer()
    await show_broadcast_preview(callback.message, state, session)


async def show_broadcast_preview(
    message: Message,
    state: FSMContext,
    session: AsyncSession
):
    """Display broadcast preview and request confirmation."""
    data = await state.get_data()
    content = BroadcastContent.from_dict(data.get("content", {}))

    # Send preview
    preview_text = "👁 <b>Ko'rib chiqish:</b>\n\n"

    try:
        await send_preview_message(message, content)
    except Exception as e:
        await session.rollback()
        await message.answer(f"{ERROR_MESSAGES['send_failed']}\n{str(e)}")
        await state.clear()
        return

    # Calculate recipients based on audience type
    if content.audience_type == "all":
        total_users = await ClientDAO.count_all(session)
        audience_info = f"👥 Qabul qiluvchilar: <b>Barcha ({total_users:,} ta)</b>\n"
    elif content.audience_type == "selected":
        clients = await ClientDAO.get_by_client_codes(session, content.target_client_codes)
        total_users = len(clients)
        audience_info = (
            f"🎯 Qabul qiluvchilar: <b>{total_users} ta tanlangan client</b>\n"
            f"📋 Kodlar: <code>{', '.join(content.target_client_codes)}</code>\n"
        )
    else:
        total_users = 0
        audience_info = "⚠️ Qabul qiluvchilar aniqlanmagan\n"

    time_estimate = calculate_broadcast_time(total_users)

    confirmation_text = (
        f"{preview_text}"
        f"{audience_info}"
        f"⏱ Taxminiy vaqt: <b>{time_estimate['formatted']}</b>\n\n"
        "Yuborishni tasdiqlaysizmi?"
    )

    await message.answer(
        confirmation_text,
        reply_markup=BroadcastKeyboards.confirmation(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.preview)


async def send_preview_message(message: Message, content: BroadcastContent):
    """Send preview of broadcast content."""
    from src.bot.handlers.admin.broadcast.utils import build_inline_keyboard

    keyboard = build_inline_keyboard(content.buttons)
    entities = entities_to_telegram_format(content.caption_entities)

    if content.is_forward():
        await message.bot.forward_message(
            chat_id=message.chat.id,
            from_chat_id=content.forward_from_chat_id,
            message_id=content.forward_message_id
        )
    elif content.media_type == "text":
        await message.answer(
            content.caption or "Matn yo'q",
            reply_markup=keyboard,
            entities=entities
        )
    elif content.is_album():
        await send_preview_album(message, content, keyboard)
    else:
        await send_preview_single_media(message, content, keyboard)


async def send_preview_single_media(message: Message, content: BroadcastContent, keyboard):
    """Send preview of single media."""
    file_id = content.file_ids[0]
    caption = content.caption
    entities = entities_to_telegram_format(content.caption_entities)

    if content.media_type == "photo":
        await message.answer_photo(
            file_id, caption=caption,
            caption_entities=entities,
            reply_markup=keyboard
        )
    elif content.media_type == "video":
        await message.answer_video(
            file_id, caption=caption,
            caption_entities=entities,
            reply_markup=keyboard
        )
    elif content.media_type == "document":
        await message.answer_document(
            file_id, caption=caption,
            caption_entities=entities,
            reply_markup=keyboard
        )
    elif content.media_type == "audio":
        await message.answer_audio(
            file_id, caption=caption,
            caption_entities=entities,
            reply_markup=keyboard
        )
    elif content.media_type == "voice":
        await message.answer_voice(
            file_id, caption=caption,
            caption_entities=entities,
            reply_markup=keyboard
        )


async def send_preview_album(message: Message, content: BroadcastContent, keyboard):
    """Send preview of media album."""
    from aiogram.types import InputMediaPhoto, InputMediaVideo
    from aiogram.types import InputMediaDocument, InputMediaAudio
    from src.bot.handlers.admin.broadcast.constants import MAX_ALBUM_SIZE

    media_class_map = {
        "photo_album": InputMediaPhoto,
        "video_album": InputMediaVideo,
        "document_album": InputMediaDocument,
        "audio_album": InputMediaAudio
    }

    media_class = media_class_map.get(content.media_type)
    if not media_class:
        return

    entities = entities_to_telegram_format(content.caption_entities)

    media = [
        media_class(
            media=file_id,
            caption=content.caption if idx == 0 else None,
            caption_entities=entities if idx == 0 else None
        )
        for idx, file_id in enumerate(content.file_ids[:MAX_ALBUM_SIZE])
    ]

    await message.answer_media_group(media)

    if keyboard:
        await message.answer("Tugmalar:", reply_markup=keyboard)


@router.callback_query(F.data == "broadcast_confirm", IsAdmin())
async def confirm_and_start_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot
):
    """Confirm and initiate broadcast sending."""
    await callback.answer()
    
    data = await state.get_data()
    content = BroadcastContent.from_dict(data.get("content", {}))
    
    # Calculate correct total based on audience type
    if content.audience_type == "selected":
        clients = await ClientDAO.get_by_client_codes(session, content.target_client_codes)
        total_users_count = len(clients)
    else:
        total_users_count = await ClientDAO.count_all(session)

    # Create database record
    broadcast_data = {
        "created_by_telegram_id": callback.from_user.id,
        "media_type": content.media_type,
        "caption": content.caption,
        "media_file_ids": json.dumps(content.file_ids, ensure_ascii=False),
        "forward_from_chat_id": content.forward_from_chat_id,
        "forward_message_id": content.forward_message_id,
        "inline_buttons": serialize_buttons(content.buttons),
        "status": BroadcastStatus.SCHEDULED,
        "total_users": total_users_count
    }
    
    broadcast = await BroadcastDAO.create(session, broadcast_data)
    await session.commit()
    
    # Create progress message
    progress_msg = await callback.message.answer(
        "🚀 <b>Yuborish boshlandi...</b>\n\n"
        f"👥 Jami: {broadcast.total_users:,}\n"
        f"📤 Progress: 0/{broadcast.total_users} (0%)\n"
        f"✅ Muvaffaqiyatli: 0\n"
        f"❌ Xato: 0\n"
        f"🚫 Bloklangan: 0",
        parse_mode="HTML"
    )
    
    # Setup broadcast task
    task_id = f"{callback.from_user.id}_{int(time.time())}"
    cancellation_flag = {"cancelled": False}
    
    sender = BroadcastSender(
        bot=bot,
        broadcast_id=broadcast.id,
        content=content,
        admin_chat_id=callback.from_user.id,
        progress_message_id=progress_msg.message_id,
        task_id=task_id,
        cancellation_flag=cancellation_flag
    )
    
    # Start sending task
    task = asyncio.create_task(sender.send_to_all())
    
    active_broadcasts[task_id] = {
        "task": task,
        "flag": cancellation_flag,
        "broadcast_id": broadcast.id
    }
    
    await state.update_data(task_id=task_id)
    await state.set_state(BroadcastStates.sending)
    
    # Add stop button
    await progress_msg.edit_reply_markup(
        reply_markup=BroadcastKeyboards.stop_broadcast(task_id)
    )
    try:
        await callback.message.delete()
    except Exception:
        await session.rollback()
        pass

@router.callback_query(F.data.startswith("broadcast_stop:"), IsAdmin())
async def stop_active_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
):
    """Stop ongoing broadcast."""
    await callback.answer("To'xtatilmoqda...")
    
    task_id = callback.data.split(":")[1]
    
    if task_id in active_broadcasts:
        active_broadcasts[task_id]["flag"]["cancelled"] = True
        
        broadcast_id = active_broadcasts[task_id]["broadcast_id"]
        await BroadcastDAO.update_status(
            session, broadcast_id, BroadcastStatus.CANCELLED
        )
        await session.commit()
    
    await callback.message.delete()
    await callback.message.answer(ERROR_MESSAGES["stopped"])
    await state.clear()


@router.callback_query(F.data == "broadcast_cancel", IsAdmin())
async def cancel_broadcast_creation(callback: CallbackQuery, state: FSMContext):
    """Cancel broadcast creation."""
    await callback.answer()
    await callback.message.edit_text(ERROR_MESSAGES["cancelled"])
    await state.clear()


@router.callback_query(F.data == "broadcast_history", IsAdmin())
async def show_broadcast_history(callback: CallbackQuery, session: AsyncSession):
    """Display recent broadcast history with detailed information."""
    await callback.answer()
    await _show_broadcast_history_page(callback.message, session, callback.from_user.id, page=0)


@router.callback_query(F.data.startswith("broadcast_history_page:"), IsAdmin())
async def show_broadcast_history_page(callback: CallbackQuery, session: AsyncSession):
    """Display specific page of broadcast history."""
    await callback.answer()
    page = int(callback.data.split(":")[1])
    await _show_broadcast_history_page(callback.message, session, callback.from_user.id, page)


async def _show_broadcast_history_page(
    message: Message,
    session: AsyncSession,
    admin_telegram_id: int,
    page: int = 0
):
    """Display paginated broadcast history."""
    BROADCASTS_PER_PAGE = 5
    
    # Get all broadcasts for this admin
    all_broadcasts = await BroadcastDAO.get_by_admin(
        session, admin_telegram_id, limit=100  # Get more for pagination
    )
    
    if not all_broadcasts:
        await message.edit_text("📊 Hali reklama yuborilmagan.")
        return
    
    # Calculate pagination
    total_broadcasts = len(all_broadcasts)
    total_pages = (total_broadcasts + BROADCASTS_PER_PAGE - 1) // BROADCASTS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * BROADCASTS_PER_PAGE
    end_idx = start_idx + BROADCASTS_PER_PAGE
    page_broadcasts = all_broadcasts[start_idx:end_idx]
    
    text = f"📊 <b>Reklama tarixi</b> (Sahifa {page + 1}/{total_pages})\n"
    text += "━" * 20 + "\n\n"
    
    for broadcast in page_broadcasts:
        text += _format_broadcast_entry(broadcast)
        text += "\n" + "━" * 20 + "\n\n"
    
    # Add pagination keyboard
    from src.bot.handlers.admin.broadcast.keyboards import BroadcastKeyboards
    keyboard = BroadcastKeyboards.history_pagination(page, total_pages)
    
    await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


def _format_broadcast_entry(broadcast) -> str:
    """Format a single broadcast entry with all details."""
    from src.bot.handlers.admin.broadcast.utils import deserialize_buttons
    
    # Get status string (handle enum)
    status_str = broadcast.status.value if hasattr(broadcast.status, 'value') else str(broadcast.status)
    emoji = STATUS_EMOJIS.get(status_str, "📊")
    status_text = _format_status(broadcast.status)
    
    text = f"{emoji} <b>Broadcast #{broadcast.id}</b>\n"
    text += f"📅 Sana: {broadcast.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
    text += f"📊 Status: {status_text}\n\n"
    
    # Content section
    text += "📦 <b>Kontent:</b>\n"
    
    # Detect content type (handle enum)
    media_type = broadcast.media_type.value if hasattr(broadcast.media_type, 'value') else str(broadcast.media_type)
    
    if media_type == "forward":
        text += "   • Media turi: <b>FORWARD</b>\n"
        if broadcast.forward_from_chat_id and broadcast.forward_message_id:
            text += f"   • Forward qilingan xabar\n"
            text += f"   • Chat ID: <code>{broadcast.forward_from_chat_id}</code>\n"
            text += f"   • Message ID: <code>{broadcast.forward_message_id}</code>\n"
    elif media_type == "text":
        text += "   • Media turi: <b>TEXT</b>\n"
        if broadcast.caption:
            caption_preview = _truncate_text(broadcast.caption, 200)
            text += f"   • Matn: <i>{_escape_html(caption_preview)}</i>\n"
    else:
        # Media type
        media_type_display = _format_media_type(media_type)
        text += f"   • Media turi: <b>{media_type_display}</b>\n"
        
        # File count
        file_count = _count_media_files(broadcast.media_file_ids)
        if file_count > 0:
            text += f"   • Fayllar soni: {file_count} ta\n"
        
        # Caption preview
        if broadcast.caption:
            caption_preview = _truncate_text(broadcast.caption, 150)
            text += f"   • Caption: <i>{_escape_html(caption_preview)}</i>\n"
    
    text += "\n"
    
    # Buttons section
    text += "🔘 <b>Tugmalar:</b>\n"
    buttons = deserialize_buttons(broadcast.inline_buttons) if broadcast.inline_buttons else []
    if buttons:
        text += f"   • Tugmalar soni: {len(buttons)} ta\n"
    else:
        text += "   • Yo'q\n"
    text += "\n"
    
    # Pin section
    text += "📌 <b>Pin:</b>\n"
    if broadcast.pin_message:
        text += "   • Pin qilingan\n"
    else:
        text += "   • Pin qilinmagan\n"
    text += "\n"
    
    # Statistics section
    text += "📈 <b>Natija:</b>\n"
    success_rate = (
        f"{(broadcast.sent_count / broadcast.total_users * 100):.1f}%"
        if broadcast.total_users > 0 else "0%"
    )
    text += f"   • Yuborildi: <b>{broadcast.sent_count}/{broadcast.total_users}</b> ({success_rate})\n"
    text += f"   • ❌ Xato: <b>{broadcast.failed_count}</b>\n"
    text += f"   • 🚫 Bloklangan: <b>{broadcast.blocked_count}</b>\n"
    text += "\n"
    
    # Timing section
    text += "⏱ <b>Vaqt:</b>\n"
    if broadcast.started_at:
        text += f"   • Boshlangan: {broadcast.started_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
    else:
        text += "   • Boshlangan: Hali boshlanmagan\n"
    
    if broadcast.completed_at:
        text += f"   • Tugagan: {broadcast.completed_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
    else:
        status_str = broadcast.status.value if hasattr(broadcast.status, 'value') else str(broadcast.status)
        if status_str in ["completed", "cancelled", "failed"]:
            text += "   • Tugagan: Noma'lum\n"
        else:
            text += "   • Tugagan: Hali tugamagan\n"
    
    return text


def _format_status(status) -> str:
    """Convert status enum to human-readable text."""
    status_map = {
        "draft": "Draft",
        "scheduled": "Rejalashtirilgan",
        "sending": "Yuborilmoqda",
        "completed": "Yakunlangan",
        "cancelled": "Bekor qilingan",
        "failed": "Xatolik"
    }
    status_str = status.value if hasattr(status, 'value') else str(status)
    return status_map.get(status_str, status_str)


def _format_media_type(media_type: str) -> str:
    """Convert media type to human-readable text."""
    type_map = {
        "text": "TEXT",
        "photo": "PHOTO",
        "photo_album": "PHOTO ALBUM",
        "video": "VIDEO",
        "video_album": "VIDEO ALBUM",
        "document": "DOCUMENT",
        "document_album": "DOCUMENT ALBUM",
        "audio": "AUDIO",
        "audio_album": "AUDIO ALBUM",
        "voice": "VOICE",
        "forward": "FORWARD"
    }
    return type_map.get(media_type, media_type.upper())


def _count_media_files(media_file_ids: str | None) -> int:
    """Count number of media files from JSON string."""
    if not media_file_ids:
        return 0
    try:
        file_ids = json.loads(media_file_ids)
        if isinstance(file_ids, list):
            return len(file_ids)
        return 1 if file_ids else 0
    except (json.JSONDecodeError, TypeError):
        # If not JSON, treat as single file_id string
        return 1 if media_file_ids else 0


def _truncate_text(text: str, max_length: int) -> str:
    """Truncate text to max length with ellipsis."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )