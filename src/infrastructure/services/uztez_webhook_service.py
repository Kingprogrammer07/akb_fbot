"""Uztez partner outgoing webhook service.

Dispatches flight cargo photo reports to Uztez's external webhook endpoint
whenever bulk sending runs for a flight containing Uztez cargo.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from src.config import config

logger = logging.getLogger(__name__)

# Delivery settings
_DEFAULT_TIMEOUT_SECONDS = 30.0
_MAX_RETRIES = 3
_BACKOFF_FACTOR = 1.5


class UztezWebhookService:
    """Dispatches outgoing webhook notifications to Uztez partner API."""

    def __init__(
        self,
        target_url: str | None = None,
        secret: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._target_url = target_url
        self._secret = secret
        self._timeout = timeout

    @property
    def target_url(self) -> str | None:
        """Configured target URL or fallback to config."""
        if self._target_url is not None:
            return self._target_url
        return config.api.UZTEZ_WEBHOOK_URL

    @property
    def secret(self) -> str | None:
        """Configured secret or fallback to config."""
        if self._secret is not None:
            return self._secret
        if config.api.UZTEZ_WEBHOOK_SECRET:
            return config.api.UZTEZ_WEBHOOK_SECRET.get_secret_value()
        return None

    def is_configured(self) -> bool:
        """Return True if a destination webhook URL is configured."""
        url = self.target_url
        return bool(url and url.strip())

    async def send_flight_reports(self, payload: dict[str, Any]) -> bool:
        """Send cargo photo reports payload to Uztez via HTTP POST.

        Args:
            payload: Formatted dictionary containing flight details and reports.

        Returns:
            True if delivered with 2xx HTTP response, False otherwise.
            Never raises exceptions to caller.
        """
        url = self.target_url
        if not url or not url.strip():
            logger.info("Uztez webhook URL not configured; skipping webhook dispatch.")
            return False

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "AKB-Cargo-Bot/1.0",
        }

        secret = self.secret
        if secret:
            headers["X-Webhook-Secret"] = secret

        flight_name = payload.get("flight_name", "UNKNOWN")
        total_clients = payload.get("total_clients", 0)

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)

                if 200 <= response.status_code < 300:
                    logger.info(
                        "Uztez webhook dispatched successfully for flight %s (%d reports) to %s: HTTP %d",
                        flight_name,
                        total_clients,
                        url,
                        response.status_code,
                    )
                    return True

                logger.warning(
                    "Uztez webhook attempt %d/%d returned HTTP %d: %s",
                    attempt,
                    _MAX_RETRIES,
                    response.status_code,
                    response.text[:200],
                )

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning(
                    "Uztez webhook attempt %d/%d network error (%s): %s",
                    attempt,
                    _MAX_RETRIES,
                    type(exc).__name__,
                    exc,
                )
            except Exception as exc:
                logger.error(
                    "Unexpected error during Uztez webhook dispatch (attempt %d/%d): %s",
                    attempt,
                    _MAX_RETRIES,
                    exc,
                    exc_info=True,
                )

            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_BACKOFF_FACTOR**attempt)

        logger.error(
            "Uztez webhook dispatch failed for flight %s after %d attempts to %s",
            flight_name,
            _MAX_RETRIES,
            url,
        )
        return False


# Global singleton instance
uztez_webhook_service = UztezWebhookService()
