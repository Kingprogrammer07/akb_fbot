"""Admin track code checker - Best practice implementation."""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters import IsPrivate
from src.bot.states.admin_track_check import AdminTrackCheckStates
from src.bot.filters.is_admin import IsAdmin
from src.infrastructure.services.cargo_item import CargoItemService
from src.infrastructure.services.client import ClientService
from src.bot.utils.decorators import handle_errors
from src.bot.keyboards.reply_kb.general_keyb import cancel_kyb

track_check_router = Router()


@track_check_router.message(F.text.in_(["📦 Track kod tekshirish", "📦 Проверка трек-кода"]), IsAdmin(), IsPrivate())
@handle_errors
async def start_track_check(
    message: Message,
    _: callable,
    state: FSMContext
):
    """Start track code check flow."""
    await state.clear()
    await state.set_state(AdminTrackCheckStates.waiting_for_track_code)
    await message.answer(
        _("admin-track-check-enter-code"),
        reply_markup=cancel_kyb(_)
    )


@track_check_router.message(AdminTrackCheckStates.waiting_for_track_code, IsAdmin())
@handle_errors
async def process_track_code(
    message: Message,
    _: callable,
    session: AsyncSession,
    cargo_service: CargoItemService,
    client_service: ClientService,
    state: FSMContext
):
    """Process track code and show results."""

    # 1. CANCEL
    if message.text == _("btn-cancel"):
        await state.clear()
        from src.bot.keyboards.reply_kb.admin_menu import get_admin_main_menu
        client = await client_service.get_client(message.from_user.id, session)
        is_super = bool(client and client.role == "super-admin")
        await message.answer(
            _("admin-track-check-cancelled"),
            reply_markup=get_admin_main_menu(_, is_super_admin=is_super)
        )
        return

    # 2. Validatsiya
    if not message.text or len(message.text.strip()) < 3:
        await message.answer(
            _("admin-track-check-code-too-short"),
            reply_markup=cancel_kyb(_)
        )
        return

    track_code = message.text.strip().upper()

    # 3. Qidiruv
    results = await cargo_service.search_by_track_code(track_code, session)

    # 4. Topilmasa
    if not results['found']:
        await message.answer(
            _("admin-track-check-not-found", track_code=track_code) + "\n\n" + _("user-track-check-search-again"),
            reply_markup=cancel_kyb(_)
        )
        return

    # 5. merged items dict bo'lib keladi — .get() bilan olamiz
    items_in_uzbekistan: list[dict] = results.get('items_in_uzbekistan', [])
    items_in_china: list[dict]      = results.get('items_in_china', [])

    # Fallback: agar servis eski formatda qaytarsa (faqat 'items' bo'lsa)
    if not items_in_uzbekistan and not items_in_china:
        all_items: list[dict] = results.get('items', [])
        items_in_uzbekistan = [i for i in all_items if i.get('checkin_status') == 'post']
        items_in_china      = [i for i in all_items if i.get('checkin_status') == 'pre']

    # 6. O'zbekistondagi yuklar (post)
    for item in items_in_uzbekistan:
        client_info = item.get('client_id') or _("not-provided")

        info_text = _("admin-track-check-uzbekistan-info",
            track_code=track_code,
            client_id=client_info,
            flight=item.get('flight_name') or _("not-provided"),
            arrival_date=item.get('post_checkin_date') or _("not-provided"),
            weight=item.get('weight_kg') or _("not-provided"),
            quantity=item.get('quantity') or _("not-provided"),
            total_payment=item.get('total_payment_uzs') or item.get('total_payment_usd') or _("not-provided"),
        )
        await message.answer(info_text)

    # 7. Xitoydag yuklar (pre)
    for item in items_in_china:
        client_info = item.get('client_id') or _("not-provided")

        info_text = _("admin-track-check-china-info",
            track_code=track_code,
            client_id=client_info,
            flight=item.get('flight_name') or _("not-provided"),
            checkin_date=item.get('pre_checkin_date') or _("not-provided"),
            item_name_ru=item.get('item_name_ru') or _("not-provided"),
            item_name_cn=item.get('item_name_cn') or _("not-provided"),
            weight=item.get('weight_kg') or _("not-provided"),
            quantity=item.get('quantity') or _("not-provided"),
            box_number=item.get('box_number') or _("not-provided"),
        )
        await message.answer(info_text)

    # 8. Agar hech narsa topilmagan bo'lsa (merged bo'sh)
    if not items_in_uzbekistan and not items_in_china:
        await message.answer(
            _("admin-track-check-not-found", track_code=track_code) + "\n\n" + _("user-track-check-search-again"),
            reply_markup=cancel_kyb(_)
        )
        return

    # 9. Summary (bir nechta natija bo'lsa)
    total = results.get('total_count', len(items_in_uzbekistan) + len(items_in_china))
    if total > 1:
        summary = _("admin-track-check-summary",
            total=total,
            in_uzbekistan=len(items_in_uzbekistan),
            in_china=len(items_in_china),
        )
        await message.answer(summary)

    await message.answer(
        _("user-track-check-search-again"),
        reply_markup=cancel_kyb(_)
    )