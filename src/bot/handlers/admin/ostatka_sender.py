"""Ostatka (A-) bulk cargo report sender.

Parallel workflow to ``bulk_cargo_sender.BulkCargoSender`` but specialised for
"A-" prefixed flights, which represent *leftover* cargo (ostatka).  The
differences from the regular flow are intentional and driven by business
requirements:

* Target chat is always ``config.telegram.AKB_OSTATKA_GROUP_ID``
  (never the client's personal chat).
* Report body excludes: ``track_code`` block, payment card details and the
  admin's ``foto_hisobot`` message.  It keeps: per-item weight / price,
  total weight, total payment.
* Clients are still put on the ledger — a ``ClientTransaction`` row with
  ``payment_status="pending"`` and ``is_taken_away=False`` is created per
  client, so the existing debt / take-away tracking pipeline continues to
  work without modification.
* Once every client has been processed, an aggregate statistics post is
  emitted to the same group via :mod:`src.bot.utils.ostatka_stats` — this
  module is reused by the daily scheduler.
"""
from __future__ import annotations

import asyncio
import contextlib
import html as html_module
import json
import logging
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.handlers.admin.bulk_cargo_sender import (
    ChannelLogger,
    ErrorReportGenerator,
    ProgressReporter,
    SendStats,
    _active_tasks,
    BulkSendTask,
    MAX_PHOTOS_PER_MESSAGE,
    DEFAULT_USD_TO_UZS_RATE,
)
from src.bot.utils.safe_sender import safe_execute, safe_send_message, safe_send_photo
from src.config import config
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.tools.s3_manager import s3_manager

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# Prefix that marks a flight as "ostatka" (leftover).  Kept as a constant so
# the branch-detection in bulk_cargo_sender.py shares a single source of truth.
OSTATKA_FLIGHT_PREFIX: str = "A-"


def is_ostatka_flight(flight_name: str) -> bool:
    """Return True when the given flight belongs to the ostatka pipeline."""
    return (flight_name or "").strip().upper().startswith(OSTATKA_FLIGHT_PREFIX)


# ---------------------------------------------------------------------------
# Report data — deliberately slimmer than CargoReportData
# ---------------------------------------------------------------------------


@dataclass
class OstatkaItem:
    """Single cargo line inside an ostatka report."""

    weight: float
    price_usd: float
    price_uzs: float
    category: str = "Yuk"


@dataclass
class OstatkaReportData:
    """Payload required to build and post a single-client ostatka report.

    Intentionally omits ``track_codes``, payment card info and
    ``foto_hisobot`` — those fields are absent by design for the A- flow.
    """

    client_id: str
    items: list[OstatkaItem]
    total_weight: float
    extra_charge: float
    photo_file_ids: list[str]
    cargo_ids: list[int]
    flight_name: str
    telegram_id: int | None = None  # Snapshot at build time; used in ClientTransaction only

    @property
    def total_price_uzs(self) -> float:
        return sum(item.price_uzs for item in self.items)

    @property
    def total_payment(self) -> float:
        return self.total_price_uzs + self.extra_charge

    def build_message(self) -> str:
        """Render the HTML report body for the ostatka group.

        No track codes, no payment card, no admin foto_hisobot — this is the
        whole point of the A- flow.  Item list + totals only.
        """
        safe_flight = html_module.escape(self.flight_name)
        safe_client = html_module.escape(self.client_id)

        items_text = "".join(
            f"📦 <b>{html_module.escape(item.category)} #{idx}</b>\n"
            f"⚖️ Vazn: {item.weight:.2f} kg\n"
            f"💰 Narx: {item.price_usd:,.2f} $ ({item.price_uzs:,.0f} so'm)\n\n"
            for idx, item in enumerate(self.items, 1)
        )

        return (
            f"♻️ <b>Ostatka — {safe_flight}</b>\n\n"
            f"{items_text}"
            f"<b>Mijoz kodi:</b> {safe_client}\n"
            f"<b>Jami vazn:</b> {self.total_weight:.2f} kg\n"
            f"<b>JAMI TO'LOV:</b> {self.total_payment:,.0f} so'm\n"
        )


# ---------------------------------------------------------------------------
# Sender
# ---------------------------------------------------------------------------


class OstatkaBulkSender:
    """Delivers per-client ostatka reports to the ostatka Telegram group.

    The class mirrors :class:`BulkCargoSender`'s external contract so the
    calling handler code can stay branch-free: same ``initialize``, ``run``
    and ``stats`` semantics, same progress / error channels.  The important
    divergences are all contained in :meth:`_process_client` and
    :meth:`_build_report_data`.
    """

    def __init__(
        self,
        bot: Bot,
        flight_name: str,
        clients_data: dict[str, list[int]],
        admin_chat_id: int,
        task_id: str,
    ) -> None:
        self.bot = bot
        self.flight_name = flight_name
        self.clients_data = clients_data
        self.admin_chat_id = admin_chat_id
        self.task_id = task_id
        self.stats = SendStats(total=len(clients_data))
        self.channel_logger = ChannelLogger(bot)
        self.error_reporter = ErrorReportGenerator(bot, admin_chat_id)
        self.progress_reporter: ProgressReporter | None = None
        self.db_client: DatabaseClient | None = None

        self.group_chat_id: int = config.telegram.AKB_OSTATKA_GROUP_ID

    async def initialize(self, progress_message_id: int) -> bool:
        """Prepare the progress reporter; kept for call-site symmetry."""
        self.progress_reporter = ProgressReporter(
            self.bot, self.admin_chat_id, progress_message_id, self.flight_name
        )
        return True

    # -------------------------------------------------------------------
    # Public entry point
    # -------------------------------------------------------------------

    async def run(self) -> SendStats:
        """Execute the full ostatka bulk-send pipeline.

        1. Load static charges (``extra_charge``) from the DB.
        2. Walk every ``client_id → cargo_ids`` pair, processing one client
           per loop turn, with cancellation and progress updates.
        3. Finalise progress + emit the error Excel when any failures.
        4. Post aggregate statistics for this flight to the group.

        Errors inside a single client's processing do NOT abort the loop —
        they are recorded in ``stats`` and continue.
        """
        async with DatabaseClient(config.database.database_url) as db_client:
            self.db_client = db_client
            try:
                extra_charge = await self._load_extra_charge()

                for client_id, cargo_ids in self.clients_data.items():
                    if self._is_cancelled():
                        break

                    self.stats.processed += 1
                    await self._process_client(client_id, cargo_ids, extra_charge)

                    if self.stats.should_update_progress() and self.progress_reporter:
                        await self.progress_reporter.update(self.stats, self.task_id)

                if self.progress_reporter:
                    await self.progress_reporter.finalize(self.stats)

                if self.stats.errors:
                    await self.error_reporter.generate_and_send(
                        self.stats.errors, self.flight_name
                    )

            finally:
                await self._cleanup()

        # Aggregate stats post is deliberately scheduled AFTER the DB client is
        # released so a failure inside the stats module can never leak an open
        # connection.  Imported locally to keep this module's import graph flat.
        with contextlib.suppress(Exception):
            from src.bot.utils.ostatka_stats import send_ostatka_stats_for_flight
            await send_ostatka_stats_for_flight(self.bot, self.flight_name)

        return self.stats

    # -------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------

    def _is_cancelled(self) -> bool:
        task = _active_tasks.get(self.task_id)
        return bool(task and task.cancelled)

    async def _load_extra_charge(self) -> float:
        """Return the ``extra_charge`` singleton value, defaulting to 0."""
        try:
            async with self.db_client.session_factory() as session:
                static_data = await StaticDataDAO.get_first(session)
                return float(static_data.extra_charge) if static_data else 0.0
        except Exception:
            logger.exception("Failed to load static_data.extra_charge for ostatka run")
            return 0.0

    async def _process_client(
        self,
        client_id: str,
        cargo_ids: list[int],
        extra_charge: float,
    ) -> None:
        """Build + send the report for one client and record the transaction.

        Marks cargo as sent only when the Telegram delivery succeeded.  A
        failure logs to the fail channel and increments the failure counter;
        no cargo row is mutated so the operator can retry later.
        """
        report_data: OstatkaReportData | None = None
        async with self.db_client.session_factory() as session:
            try:
                report_data = await self._build_report_data(
                    session, client_id, cargo_ids, extra_charge
                )
                if not report_data:
                    # Nothing renderable (no photos, no weights) — mark the
                    # rows sent so the admin is not re-offered an unusable set
                    # of cargos forever.  No transaction is created because
                    # we cannot compute a meaningful debt.
                    await FlightCargoDAO.mark_as_sent(session, cargo_ids)
                    await session.commit()
                    self.stats.sent += 1
                    return

                result = await self._send_report(report_data)
                await self._handle_send_result(session, result, report_data)

            except Exception as exc:
                logger.exception("Ostatka: error processing client %s", client_id)
                self.stats.failed += 1
                await self._log_exception(client_id, exc, report_data)

    async def _build_report_data(
        self,
        session: AsyncSession,
        client_id: str,
        cargo_ids: list[int],
        extra_charge: float,
    ) -> OstatkaReportData | None:
        """Assemble an :class:`OstatkaReportData` from ``flight_cargos`` rows."""
        cargos = await self._fetch_cargos(session, cargo_ids)
        if not cargos:
            return None

        items: list[OstatkaItem] = []
        for cargo in cargos:
            weight = float(cargo.weight_kg or 0)
            price_per_kg_usd = float(cargo.price_per_kg or 0)
            price_per_kg_uzs = await self._convert_to_uzs(session, price_per_kg_usd)

            items.append(
                OstatkaItem(
                    weight=weight,
                    price_usd=price_per_kg_usd * weight,
                    price_uzs=price_per_kg_uzs * weight,
                    category="Yuk",
                )
            )

        raw_photo_ids = self._extract_photos(cargos)
        photo_file_ids = await self._resolve_photo_references(raw_photo_ids)

        # Best-effort telegram_id lookup — only for the transaction snapshot.
        # We never push anything to the user directly in the ostatka flow.
        telegram_id: int | None = None
        with contextlib.suppress(Exception):
            from src.infrastructure.database.dao.client import ClientDAO

            client = await ClientDAO.get_by_client_code(session, client_id)
            telegram_id = client.telegram_id if client else None

        total_weight = sum(item.weight for item in items)

        return OstatkaReportData(
            client_id=client_id,
            items=items,
            total_weight=total_weight,
            extra_charge=extra_charge,
            photo_file_ids=photo_file_ids,
            cargo_ids=cargo_ids,
            flight_name=self.flight_name,
            telegram_id=telegram_id,
        )

    async def _fetch_cargos(self, session: AsyncSession, cargo_ids: list[int]) -> list:
        cargos: list = []
        for cargo_id in cargo_ids:
            cargo = await FlightCargoDAO.get_by_id(session, cargo_id)
            if cargo:
                cargos.append(cargo)
        return cargos

    async def _convert_to_uzs(self, session: AsyncSession, usd_amount: float) -> float:
        """Same conversion rules as the M flow — shared fallback rate."""
        try:
            from src.bot.utils.currency_converter import currency_converter

            rate = await currency_converter.get_rate_async(session, "USD", "UZS")
            return usd_amount * rate
        except Exception:
            await session.rollback()
            logger.warning("Ostatka: currency conversion failed, using fallback")
            return usd_amount * DEFAULT_USD_TO_UZS_RATE

    def _extract_photos(self, cargos: "Sequence") -> list[str]:
        photos: list[str] = []
        for cargo in cargos:
            try:
                cargo_photos = json.loads(cargo.photo_file_ids or "[]")
                photos.extend(cargo_photos[:MAX_PHOTOS_PER_MESSAGE])
            except (json.JSONDecodeError, TypeError):
                continue
        return photos[:MAX_PHOTOS_PER_MESSAGE]

    async def _resolve_photo_references(self, items: list[str]) -> list[str]:
        resolved: list[str] = []
        for item in items:
            if "/" in item:
                try:
                    url = await s3_manager.generate_presigned_url(item, expires_in=3600)
                    resolved.append(url)
                except Exception as exc:
                    logger.error(
                        "Ostatka: failed to presign S3 key %s: %s", item, exc
                    )
            else:
                resolved.append(item)
        return resolved

    # -------------------------------------------------------------------
    # Telegram delivery
    # -------------------------------------------------------------------

    async def _send_report(self, report_data: OstatkaReportData) -> dict:
        """Send photos (if any) + text to the ostatka group."""
        chat_id = self.group_chat_id
        last_msg_id: int | None = None

        if report_data.photo_file_ids:
            try:
                caption = "📸 Foto hisobot"
                if len(report_data.photo_file_ids) == 1:
                    msg = await safe_send_photo(
                        self.bot,
                        chat_id=chat_id,
                        photo=report_data.photo_file_ids[0],
                        caption=caption,
                    )
                    if msg:
                        last_msg_id = msg.message_id
                else:
                    media = [
                        InputMediaPhoto(media=pid, caption=caption if i == 0 else None)
                        for i, pid in enumerate(
                            report_data.photo_file_ids[:MAX_PHOTOS_PER_MESSAGE]
                        )
                    ]
                    msgs = await safe_execute(
                        self.bot.send_media_group, chat_id=chat_id, media=media
                    )
                    if msgs:
                        last_msg_id = msgs[-1].message_id
            except TelegramForbiddenError:
                return {
                    "success": False,
                    "status": "blocked",
                    "error": "Bot cannot post to ostatka group",
                }
            except Exception as exc:
                logger.warning(
                    "Ostatka photo send failed for %s: %s", report_data.client_id, exc
                )

        try:
            await safe_send_message(
                self.bot,
                chat_id=chat_id,
                text=report_data.build_message(),
                reply_to_message_id=last_msg_id,
                parse_mode="HTML",
            )
            return {"success": True, "status": "sent"}
        except TelegramForbiddenError:
            return {
                "success": False,
                "status": "blocked",
                "error": "Bot cannot post to ostatka group",
            }
        except Exception as exc:
            return {"success": False, "status": "error", "error": str(exc)}

    async def _handle_send_result(
        self,
        session: AsyncSession,
        result: dict,
        report_data: OstatkaReportData,
    ) -> None:
        log_message = report_data.build_message()

        if result.get("success"):
            await self._mark_as_sent(session, report_data)
            self.stats.sent += 1
            await self.channel_logger.log_success(
                self.flight_name,
                report_data.client_id,
                self.group_chat_id,
                log_message,
                report_data.photo_file_ids,
            )
            return

        status_value = result.get("status", "")
        error_reason = result.get("error", "Unknown error")
        if status_value == "blocked":
            self.stats.blocked += 1
            self.stats.add_error(
                report_data.client_id,
                self.flight_name,
                f"Blocked: {error_reason}",
            )
        else:
            self.stats.failed += 1
            self.stats.add_error(
                report_data.client_id, self.flight_name, error_reason
            )

        cb_data = f"manual_sent:{self.flight_name}:{report_data.client_id}"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Qo'lda yuborildi", callback_data=cb_data)]
            ]
        )
        await self.channel_logger.log_failure(
            self.flight_name,
            report_data.client_id,
            error_reason,
            log_message,
            report_data.photo_file_ids,
            reply_markup=keyboard,
        )

    # -------------------------------------------------------------------
    # Ledger: mark cargos sent + create (or reuse) ClientTransaction
    # -------------------------------------------------------------------

    async def _mark_as_sent(
        self,
        session: AsyncSession,
        report_data: OstatkaReportData,
    ) -> None:
        """Persist success: ``FlightCargo.is_sent = True`` + create debt tx.

        Why do we still create a :class:`ClientTransaction` on the ostatka
        flow?  Because the downstream ``is_taken_away`` bookkeeping — the
        sole source of truth for whether a parcel is still in the warehouse —
        lives on that table.  Without a row there, the daily stats post
        could never determine which leftovers are already delivered.
        """
        await FlightCargoDAO.mark_as_sent(session, report_data.cargo_ids)

        from src.infrastructure.services.client import ClientService

        client = await ClientService().get_client_by_code(
            report_data.client_id, session
        )
        lookup_codes = client.active_codes if client else [report_data.client_id]
        existing_tx = await ClientTransactionDAO.get_by_client_code_flight(
            session,
            lookup_codes,
            report_data.flight_name,
        )

        if not existing_tx:
            await ClientTransactionDAO.create(
                session,
                {
                    "telegram_id": report_data.telegram_id or 0,
                    "client_code": report_data.client_id,
                    "qator_raqami": 0,
                    "reys": report_data.flight_name,
                    "summa": 0,
                    "vazn": str(round(report_data.total_weight, 2)),
                    "payment_type": "online",
                    "payment_status": "pending",
                    "paid_amount": 0,
                    "total_amount": report_data.total_payment,
                    "remaining_amount": report_data.total_payment,
                    "payment_balance_difference": -report_data.total_payment,
                    "is_taken_away": False,
                },
            )
        else:
            # Reys bo'yicha oldin tranzaksiya ochilgan bo'lsa (masalan, admin
            # xuddi shu reysga yana yuk qo'shib yuborgan bo'lsa), mavjud qarzga qo'shamiz.
            current_total = float(existing_tx.total_amount or existing_tx.summa or 0)
            existing_tx.total_amount = current_total + report_data.total_payment
            
            current_remaining = float(existing_tx.remaining_amount or 0)
            existing_tx.remaining_amount = current_remaining + report_data.total_payment
            
            current_diff = float(existing_tx.payment_balance_difference or 0)
            existing_tx.payment_balance_difference = current_diff - report_data.total_payment
            
            try:
                current_vazn = float(existing_tx.vazn) if existing_tx.vazn else 0.0
            except ValueError:
                current_vazn = 0.0
            existing_tx.vazn = str(round(current_vazn + report_data.total_weight, 2))
            
            if existing_tx.payment_status == "paid" and report_data.total_payment > 0:
                existing_tx.payment_status = "partial"

        await session.commit()

    # -------------------------------------------------------------------
    # Error path
    # -------------------------------------------------------------------

    async def _log_exception(
        self,
        client_id: str,
        error: Exception,
        report_data: OstatkaReportData | None,
    ) -> None:
        error_reason = f"Exception: {error!s}"
        self.stats.add_error(client_id, self.flight_name, error_reason)

        message_text = report_data.build_message() if report_data else ""
        photo_file_ids = report_data.photo_file_ids if report_data else []

        cb_data = f"manual_sent:{self.flight_name}:{client_id}"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Qo'lda yuborildi", callback_data=cb_data)]
            ]
        )
        await self.channel_logger.log_failure(
            self.flight_name,
            client_id,
            error_reason,
            message_text=message_text,
            photo_file_ids=photo_file_ids,
            reply_markup=keyboard,
        )
        with contextlib.suppress(Exception):
            await safe_send_message(
                self.bot,
                chat_id=self.admin_chat_id,
                text=f"⚠️ Ostatka xatolik ({client_id}): {str(error)[:200]}",
            )

    async def _cleanup(self) -> None:
        _active_tasks.pop(self.task_id, None)


__all__ = [
    "OSTATKA_FLIGHT_PREFIX",
    "OstatkaBulkSender",
    "OstatkaItem",
    "OstatkaReportData",
    "is_ostatka_flight",
]
