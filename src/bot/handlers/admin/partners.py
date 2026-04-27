"""Bot-side admin commands for partner configuration.

Scope (Phase 3, bot side):

* ``/partners`` — inline list of all partners with quick-edit buttons for
  ``foto_hisobot`` and ``group_chat_id``.

Card / link CRUD and per-flight alias management remain in the web admin
panel (``/admin/partners`` REST endpoints) where the broader form factor
fits the multi-field workflows better.
"""
from __future__ import annotations

import html as html_module
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_admin import IsAdmin
from src.bot.utils.safe_sender import safe_send_message
from src.infrastructure.database.dao.partner import PartnerDAO
from src.infrastructure.database.dao.partner_static_data import (
    PartnerStaticDataDAO,
)
from src.infrastructure.services.partner_resolver import get_resolver

logger = logging.getLogger(__name__)

partners_admin_router = Router(name="partners_admin")


class PartnerAdminStates(StatesGroup):
    waiting_for_group_id = State()
    waiting_for_foto_hisobot = State()


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _partner_row(partner) -> str:
    routing = "DM" if partner.is_dm_partner else (
        f"guruh: <code>{partner.group_chat_id}</code>"
        if partner.group_chat_id
        else "❗ guruh ID yo'q"
    )
    return (
        f"• <b>{html_module.escape(partner.code)}</b> "
        f"({html_module.escape(partner.display_name)}, prefix "
        f"<code>{html_module.escape(partner.prefix)}</code>) — {routing}"
    )


def _partner_keyboard(partners) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in partners:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"⚙️ {p.code}",
                    callback_data=f"partner_open:{p.id}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="❌ Yopish", callback_data="partner_close")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _partner_detail_keyboard(partner) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 Guruh ID",
                    callback_data=f"partner_set_group:{partner.id}",
                ),
                InlineKeyboardButton(
                    text="📝 Foto hisobot",
                    callback_data=f"partner_set_foto:{partner.id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Orqaga", callback_data="partner_list"
                )
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@partners_admin_router.message(Command("partners"), IsAdmin())
async def cmd_partners(message: Message, session: AsyncSession, bot: Bot):
    """Open the partner administration menu."""
    await _render_partner_list(bot, message.chat.id, session)


@partners_admin_router.callback_query(F.data == "partner_list", IsAdmin())
async def partner_list_callback(
    callback: CallbackQuery, session: AsyncSession, bot: Bot
):
    await callback.answer()
    await callback.message.delete()
    await _render_partner_list(bot, callback.from_user.id, session)


async def _render_partner_list(bot: Bot, chat_id: int, session: AsyncSession):
    partners = await PartnerDAO.get_all(session)
    body = "\n".join(_partner_row(p) for p in partners) or "Hech qanday partner yo'q."
    text = (
        "🤝 <b>Partnerlar</b>\n\n"
        f"{body}\n\n"
        "Tahrirlash uchun partnerni tanlang."
    )
    await safe_send_message(
        bot,
        chat_id=chat_id,
        text=text,
        reply_markup=_partner_keyboard(partners),
        parse_mode="HTML",
    )


@partners_admin_router.callback_query(
    F.data.startswith("partner_open:"), IsAdmin()
)
async def partner_open(
    callback: CallbackQuery, session: AsyncSession, bot: Bot
):
    await callback.answer()
    partner_id = int(callback.data.split(":", 1)[1])
    partner = await PartnerDAO.get_by_id(session, partner_id)
    if partner is None:
        await callback.answer("❌ Partner topilmadi", show_alert=True)
        return
    psd = await PartnerStaticDataDAO.get_for_partner(session, partner.id)
    foto_preview = (psd.foto_hisobot if psd and psd.foto_hisobot else "—")[:200]

    text = (
        f"⚙️ <b>{html_module.escape(partner.display_name)}</b> "
        f"(<code>{html_module.escape(partner.code)}</code>)\n\n"
        f"<b>Prefix:</b> <code>{html_module.escape(partner.prefix)}</code>\n"
        f"<b>DM partner:</b> {'ha' if partner.is_dm_partner else 'yo'}'q\n"
        f"<b>Guruh ID:</b> "
        f"<code>{partner.group_chat_id if partner.group_chat_id else '—'}</code>\n"
        f"<b>Aktiv:</b> {'ha' if partner.is_active else 'yo'}'q\n\n"
        f"<b>Foto hisobot:</b>\n<code>{html_module.escape(foto_preview)}</code>"
    )
    await callback.message.delete()
    await safe_send_message(
        bot,
        chat_id=callback.from_user.id,
        text=text,
        reply_markup=_partner_detail_keyboard(partner),
        parse_mode="HTML",
    )


# ── group_chat_id editing ────────────────────────────────────────────────────


@partners_admin_router.callback_query(
    F.data.startswith("partner_set_group:"), IsAdmin()
)
async def partner_set_group_prompt(
    callback: CallbackQuery, state: FSMContext, bot: Bot
):
    await callback.answer()
    partner_id = int(callback.data.split(":", 1)[1])
    await state.update_data(editing_partner_id=partner_id)
    await state.set_state(PartnerAdminStates.waiting_for_group_id)
    await callback.message.delete()
    await safe_send_message(
        bot,
        chat_id=callback.from_user.id,
        text=(
            "🔗 Guruh ID ni yuboring.\n\n"
            "Bu Telegram guruhining sonli ID si bo'lishi kerak (masalan "
            "<code>-1001234567890</code>).\n\n"
            "<b>Tozalash uchun:</b> <code>0</code> yoki <code>-</code> yuboring."
        ),
        parse_mode="HTML",
    )


@partners_admin_router.message(
    PartnerAdminStates.waiting_for_group_id, IsAdmin(), F.text
)
async def partner_set_group_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    raw = (message.text or "").strip()
    data = await state.get_data()
    partner_id = data.get("editing_partner_id")
    if not partner_id:
        await message.answer("❌ Sessiya yo'qoldi.")
        await state.clear()
        return

    partner = await PartnerDAO.get_by_id(session, partner_id)
    if partner is None:
        await message.answer("❌ Partner topilmadi.")
        await state.clear()
        return

    new_group_id: int | None
    if raw in {"0", "-", "—"}:
        new_group_id = None
    else:
        try:
            new_group_id = int(raw)
        except ValueError:
            await message.answer(
                "❌ Noto'g'ri qiymat. Manfiy butun son yoki tozalash uchun "
                "<code>0</code> yuboring.",
                parse_mode="HTML",
            )
            return

    await PartnerDAO.update(session, partner, {"group_chat_id": new_group_id})
    await session.commit()
    await get_resolver().refresh(session)
    await state.clear()

    await message.answer(
        f"✅ Guruh ID yangilandi: <code>{new_group_id if new_group_id else '—'}</code>",
        parse_mode="HTML",
    )
    await _render_partner_list(bot, message.chat.id, session)


# ── foto_hisobot editing ────────────────────────────────────────────────────


@partners_admin_router.callback_query(
    F.data.startswith("partner_set_foto:"), IsAdmin()
)
async def partner_set_foto_prompt(
    callback: CallbackQuery, state: FSMContext, bot: Bot
):
    await callback.answer()
    partner_id = int(callback.data.split(":", 1)[1])
    await state.update_data(editing_partner_id=partner_id)
    await state.set_state(PartnerAdminStates.waiting_for_foto_hisobot)
    await callback.message.delete()
    await safe_send_message(
        bot,
        chat_id=callback.from_user.id,
        text=(
            "📝 Yangi foto hisobot matnini yuboring (4000 belgigacha).\n\n"
            "<b>Tozalash uchun:</b> <code>-</code> yuboring."
        ),
        parse_mode="HTML",
    )


@partners_admin_router.message(
    PartnerAdminStates.waiting_for_foto_hisobot, IsAdmin(), F.text
)
async def partner_set_foto_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    raw = message.text or ""
    if raw.strip() == "-":
        new_value = ""
    else:
        new_value = raw[:4000]

    data = await state.get_data()
    partner_id = data.get("editing_partner_id")
    if not partner_id:
        await message.answer("❌ Sessiya yo'qoldi.")
        await state.clear()
        return

    await PartnerStaticDataDAO.update_foto_hisobot(
        session, partner_id, new_value
    )
    await session.commit()
    await state.clear()

    await message.answer("✅ Foto hisobot yangilandi.")
    await _render_partner_list(bot, message.chat.id, session)


# ── close ────────────────────────────────────────────────────────────────────


@partners_admin_router.callback_query(F.data == "partner_close", IsAdmin())
async def partner_close(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()
