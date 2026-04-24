"""Currency converter utility using exchange rate API."""
import time
import requests
from typing import Dict

from src.config import config


class CurrencyConverter:
    """
    Currency converter with caching.

    Features:
    - Universal currency conversion
    - CNY -> UZS shortcut
    - In-memory cache with TTL (1 hour)
    - API key from environment
    """

    def __init__(self, ttl: int = 3600, timeout: int = 5) -> None:
        """
        Initialize currency converter.

        Args:
            ttl: Cache lifetime in seconds (default: 1 hour)
            timeout: HTTP request timeout in seconds
        """
        self.ttl = ttl
        self.timeout = timeout
        self._rates: Dict[str, float] | None = None
        self._last_fetch: float = 0.0

        self.api_url = config.api.CURRENCY_API_KEY

    def _fetch_rates(self) -> Dict[str, float]:
        """Fetch latest exchange rates from API."""
        response = requests.get(self.api_url, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()

        if data.get("result") != "success":
            raise RuntimeError("Currency API returned unsuccessful response")

        return data["rates"]

    def _get_rates(self) -> Dict[str, float]:
        """Get rates from cache or fetch if expired."""
        now = time.time()

        # Return cached rates if still valid
        if self._rates and (now - self._last_fetch) < self.ttl:
            return self._rates

        # Fetch new rates
        self._rates = self._fetch_rates()
        self._last_fetch = now
        return self._rates

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        """
        Convert amount from one currency to another.

        Args:
            amount: Amount to convert
            from_currency: Source currency code (e.g., "CNY")
            to_currency: Target currency code (e.g., "UZS")

        Returns:
            Converted amount

        Raises:
            ValueError: If currency is not supported
        """
        rates = self._get_rates()

        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        if from_currency not in rates:
            raise ValueError(f"Unsupported currency: {from_currency}")

        if to_currency not in rates:
            raise ValueError(f"Unsupported currency: {to_currency}")

        # Convert: from_currency -> USD -> to_currency
        usd_amount = amount / rates[from_currency]
        return usd_amount * rates[to_currency]

    # ========== Shortcuts ==========

    def cny_to_uzs(self, amount_cny: float) -> float:
        """
        Convert CNY (Chinese Yuan) to UZS (Uzbek Som).

        Args:
            amount_cny: Amount in CNY

        Returns:
            Amount in UZS
        """
        return self.convert(amount_cny, "CNY", "UZS")

    async def usd_to_uzs(self, session, amount_usd: float) -> float:
        """Convert USD to UZS."""
        rate = await self.get_rate_async(session, "USD", "UZS")
        return amount_usd * rate

    def uzs_to_usd(self, amount_uzs: float) -> float:
        """Convert UZS to USD."""
        return self.convert(amount_uzs, "UZS", "USD")

    def get_rate(self, from_currency: str, to_currency: str) -> float:
        """
        Get exchange rate from one currency to another.

        Args:
            from_currency: Source currency code
            to_currency: Target currency code

        Returns:
            Exchange rate (1 from_currency = X to_currency)
        """
        return self.convert(1.0, from_currency, to_currency)

    async def get_rate_async(self, session, from_currency: str, to_currency: str) -> float:
        """
        Get exchange rate from one currency to another asynchronously, 
        evaluating DB overrides.
        """
        if from_currency.upper() == "USD" and to_currency.upper() == "UZS":
            # Deferred import to avoid circular dependencies
            from src.infrastructure.database.dao.static_data import StaticDataDAO
            static_data = await StaticDataDAO.get_by_id(session, 1)
            if static_data and static_data.use_custom_rate and static_data.custom_usd_rate:
                return float(static_data.custom_usd_rate)
        
        # Fallback to sync API fetch
        return self.get_rate(from_currency, to_currency)


# Singleton instance for reuse across application
currency_converter = CurrencyConverter()
