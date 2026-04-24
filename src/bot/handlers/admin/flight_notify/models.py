"""Data models for the flight-notify sender."""

from __future__ import annotations

import asyncio
import html
from dataclasses import dataclass, field
from time import monotonic


@dataclass
class ClientNotifyData:
    """All resolved data needed to send one notification to a single client.

    Track codes are collected from ``ExpectedFlightCargo`` (DB-primary) first;
    Google Sheets is used as a fallback inside the sender when the list is empty.
    """

    client_code: str
    """Raw code from ``flight_cargos.client_id``, already upper-cased."""

    telegram_id: int | None
    """Telegram user ID.  ``None`` → client has no bot account; skip DM, log failure."""

    track_codes: list[str]
    """Trek codes for this client in the selected flight."""

    is_gx: bool = False
    """True when the client code starts with 'GX' → route to Xorazm group."""

    def build_message(self, flight_name: str, admin_text: str) -> str:
        """Compose the personalised notification text.

        Format:
            <track_code_1>,
            <track_code_2>

            bu sizning <flight_name> dagi track codingiz

            <admin_text>

        Args:
            flight_name: The selected flight name (e.g. "M190-M191").
            admin_text:  Custom suffix text entered by the admin.

        Returns:
            Plain-text message string (no HTML markup — track codes can contain
            arbitrary characters that would break Telegram's HTML parser).
        """
        if self.track_codes:
            codes_block = ",\n".join(
                html.escape(tc) for tc in self.track_codes
            )
        else:
            codes_block = "(trek kodlar topilmadi)"

        safe_flight = html.escape(flight_name)
        parts: list[str] = [
            codes_block,
            "",
            f"bu sizning {safe_flight} dagi track codingiz",
        ]
        if admin_text.strip():
            parts += ["", html.escape(admin_text.strip())]

        return "\n".join(parts)


@dataclass
class FlightNotifyStats:
    """Running counters for one flight-notify send operation."""

    total: int = 0
    processed: int = 0
    sent: int = 0
    failed: int = 0
    blocked: int = 0
    skipped_no_telegram: int = 0
    """Clients that exist in flight_cargos but have no Telegram account."""

    start_time: float = field(default_factory=monotonic)
    errors: list[tuple[str, str]] = field(default_factory=list)
    """List of (client_code, reason) pairs for all non-successful sends."""

    @property
    def progress_percent(self) -> int:
        """Integer progress percentage (0–100)."""
        if self.total == 0:
            return 0
        return int((self.processed / self.total) * 100)

    @property
    def elapsed_time(self) -> float:
        """Seconds since the send started."""
        return monotonic() - self.start_time

    @property
    def estimated_remaining(self) -> float:
        """Estimated seconds until completion based on average send rate."""
        if self.processed == 0:
            return 0.0
        avg_time = self.elapsed_time / self.processed
        return (self.total - self.processed) * avg_time

    def should_update_progress(self, interval_percent: int = 5) -> bool:
        """Return True when progress has advanced by ``interval_percent`` since last update."""
        if self.total == 0:
            return False
        interval = max(1, self.total // (100 // interval_percent))
        return self.processed % interval == 0 or self.processed == self.total


@dataclass
class FlightNotifyTask:
    """Thin wrapper around an asyncio Task that supports cooperative cancellation."""

    task: asyncio.Task
    cancelled: bool = False

    def cancel(self) -> None:
        """Signal cancellation; the sender checks this flag between sends."""
        self.cancelled = True
        self.task.cancel()
