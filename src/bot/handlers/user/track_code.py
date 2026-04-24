"""User track code checker - Best practice implementation."""
import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_private_chat import IsPrivate
from src.bot.filters.is_logged_in import ClientExists, IsRegistered, IsLoggedIn
from src.bot.states.user_track_check import UserTrackCheckStates
from src.infrastructure.services.cargo_item import CargoItemService
from src.infrastructure.database.models.analytics_event import AnalyticsEvent
from src.bot.utils.decorators import handle_errors
from src.bot.utils.safe_sender import safe_execute
from src.bot.keyboards.reply_kb.general_keyb import cancel_kyb

logger = logging.getLogger(__name__)

track_code_router = Router(name="track_code")


@track_code_router.message(
    IsPrivate(),
    ClientExists(),
    IsRegistered(),
    IsLoggedIn(),
    F.text.in_(["📦 Track kod tekshirish", "📦 Проверка трек-кода"])
)
@handle_errors
async def start_track_check(
    message: Message,
    _: callable,
    state: FSMContext
):
    """Start track code check flow for users."""
    await state.clear()
    await state.set_state(UserTrackCheckStates.waiting_for_track_code)
    await message.answer(
        _("user-track-check-enter-code"),
        reply_markup=cancel_kyb(_)
    )


@track_code_router.message(UserTrackCheckStates.waiting_for_track_code, IsPrivate(), ClientExists(), IsRegistered())
@handle_errors
async def process_track_code(
    message: Message,
    _: callable,
    session: AsyncSession,
    cargo_service: CargoItemService,
    state: FSMContext
):
    """Process track code and show results for users."""

    # 1. CANCEL
    if message.text == _("btn-cancel"):
        await state.clear()
        from src.bot.keyboards.user.reply_keyb.user_home_kyb import get_user_home_keyboard
        await message.answer(
            _("user-track-check-cancelled"),
            reply_markup=get_user_home_keyboard(_)
        )
        return

    # 2. Validatsiya
    if not message.text or len(message.text.strip()) < 3:
        await message.answer(
            _("user-track-check-code-too-short"),
            reply_markup=cancel_kyb(_)
        )
        return

    track_code = message.text.strip().upper()

    # 3. Qidiruv
    results = await cargo_service.search_by_track_code(track_code, session)

    # 4. Topilmasa
    if not results['found']:
        try:
            session.add(AnalyticsEvent(
                event_type="track_code_search",
                user_id=message.from_user.id,
                event_data={"track_code": track_code, "found": False},
            ))
            await session.commit()
        except Exception as e:
            logger.warning(f"Analytics event failed (track_code_search not found): {e}")
        await safe_execute(
            message.answer,
            _("user-track-check-not-found", track_code=track_code) + "\n\n" + _("user-track-check-search-again"),
            reply_markup=cancel_kyb(_)
        )
        return

    # Muvaffaqiyatli qidiruvni ham loglaymiz
    try:
        session.add(AnalyticsEvent(
            event_type="track_code_search",
            user_id=message.from_user.id,
            event_data={"track_code": track_code, "found": True},
        ))
        await session.commit()
    except Exception as e:
        logger.warning(f"Analytics event failed (track_code_search found): {e}")

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
        info_text = _("user-track-check-uzbekistan-info",
            track_code=track_code,
            flight=item.get('flight_name') or _("not-provided"),
            arrival_date=item.get('post_checkin_date') or _("not-provided"),
            total_payment=item.get('total_payment_uzs') or item.get('total_payment_usd') or _("not-provided"),
            weight=item.get('weight_kg') or _("not-provided"),
            quantity=item.get('quantity') or _("not-provided"),
        )
        await safe_execute(message.answer, info_text)

    # 7. Xitoydag yuklar (pre)
    for item in items_in_china:
        info_text = _("user-track-check-china-info",
            track_code=track_code,
            checkin_date=item.get('pre_checkin_date') or _("not-provided"),
            item_name=item.get('item_name_ru') or item.get('item_name_cn') or _("not-provided"),
            weight=item.get('weight_kg') or _("not-provided"),
            quantity=item.get('quantity') or _("not-provided"),
            flight=item.get('flight_name') or _("not-provided"),
            box_number=item.get('box_number') or _("not-provided"),
        )
        await safe_execute(message.answer, info_text)

    # 8. Hech narsa topilmagan bo'lsa
    if not items_in_uzbekistan and not items_in_china:
        await safe_execute(
            message.answer,
            _("user-track-check-not-found", track_code=track_code) + "\n\n" + _("user-track-check-search-again"),
            reply_markup=cancel_kyb(_)
        )
        return

    # 9. Summary (bir nechta natija bo'lsa)
    total = results.get('total_count', len(items_in_uzbekistan) + len(items_in_china))
    if total > 1:
        summary = _("user-track-check-summary",
            total=total,
            in_uzbekistan=len(items_in_uzbekistan),
            in_china=len(items_in_china),
        )
        await safe_execute(message.answer, summary)

    await safe_execute(
        message.answer,
        _("user-track-check-search-again"),
        reply_markup=cancel_kyb(_)
    )