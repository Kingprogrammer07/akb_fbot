"""Flights cache utility using Redis."""
import json
import time
from typing import List

from src.bot.utils.google_sheets_checker import GoogleSheetsChecker
from src.config import config


# Cache TTL in seconds (5-10 minutes)
FLIGHTS_CACHE_TTL = 600  # 10 minutes

# Default number of flights to return
DEFAULT_FLIGHTS_COUNT = 5


class FlightsCache:
    """Cache for Google Sheets flights with Redis."""

    CACHE_KEY = "flights:list"

    def __init__(self, sheets_checker: GoogleSheetsChecker):
        """
        Initialize flights cache.

        Args:
            sheets_checker: GoogleSheetsChecker instance
        """
        self.sheets_checker = sheets_checker
        self._memory_cache: dict | None = None
        self._cache_timestamp: float = 0

    async def get_flights(
        self,
        use_cache: bool = True,
        last_n: int = DEFAULT_FLIGHTS_COUNT
    ) -> List[str]:
        """Get flights from cache or Google Sheets.

        The underlying ``GoogleSheetsChecker`` now returns a **per-prefix**
        capped list (``last_n`` M-flights followed by ``last_n`` A--flights),
        so the cache must hand back the full captured list verbatim — slicing
        here would silently drop the ostatka group.

        Args:
            use_cache: Whether to use cache (default: True).
            last_n:    Per-prefix cap passed through to the sheets checker.

        Returns:
            Combined list of flight names (M group then A- group).
        """
        if not use_cache:
            return await self._fetch_from_sheets(last_n)

        if self._is_memory_cache_valid():
            return list(self._memory_cache["flights"])

        flights = await self._fetch_from_sheets(last_n=last_n)
        self._memory_cache = {
            "flights": flights,
            "cached_at": time.time(),
        }
        self._cache_timestamp = time.time()
        return flights

    async def _fetch_from_sheets(self, last_n: int = 10) -> List[str]:
        """Fetch flights from Google Sheets."""
        return await self.sheets_checker.get_flight_sheet_names(last_n=last_n)

    def _is_memory_cache_valid(self) -> bool:
        """Check if memory cache is still valid."""
        if not self._memory_cache:
            return False

        elapsed = time.time() - self._cache_timestamp
        return elapsed < FLIGHTS_CACHE_TTL

    def invalidate_cache(self):
        """Manually invalidate cache."""
        self._memory_cache = None
        self._cache_timestamp = 0


# Global instance
_flights_cache: FlightsCache | None = None


def get_flights_cache() -> FlightsCache:
    """Get or create global flights cache instance."""
    global _flights_cache

    if _flights_cache is None:
        sheets_checker = GoogleSheetsChecker(
            spreadsheet_id=config.google_sheets.SHEETS_ID,
            api_key=config.google_sheets.API_KEY,
            last_n_sheets=10
        )
        _flights_cache = FlightsCache(sheets_checker)

    return _flights_cache
