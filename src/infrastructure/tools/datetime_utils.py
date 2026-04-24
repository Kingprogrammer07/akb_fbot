"""
Timezone-safe datetime utilities for international deployment.

TIMEZONE STRATEGY:
- Storage: All timestamps stored in UTC (universal, unambiguous)
- Business Logic: Asia/Tashkent (UTC+5) for all business operations
- API: ISO format with timezone or converted to business timezone

CRITICAL RULES:
1. NEVER use naive datetime objects
2. NEVER rely on server local timezone
3. Always use UTC for storage/database
4. Always convert to Tashkent for business date operations
"""
from datetime import datetime, date, time
import pytz

# Business timezone - all business logic uses this
TASHKENT_TZ = pytz.timezone('Asia/Tashkent')
# Storage timezone - all database timestamps use this
UTC_TZ = pytz.UTC


def get_current_time() -> datetime:
    """
    Get current UTC time for database storage.
    
    Returns:
        Current datetime in UTC timezone (for storage)
    
    Usage:
        Use this for all created_at/updated_at timestamps.
        Database should store UTC, never server local time.
    """
    return datetime.now(UTC_TZ)


def get_current_business_time() -> datetime:
    """
    Get current time in business timezone (Asia/Tashkent).
    
    Returns:
        Current datetime in Tashkent timezone (for business logic)
    
    Usage:
        Use this when you need the "current time" in Tashkent for business operations.
    """
    return datetime.now(TASHKENT_TZ)


def get_current_business_date() -> date:
    """
    Get current date in business timezone (Asia/Tashkent).
    
    Returns:
        Current date in Tashkent timezone
        
    Usage:
        Use this instead of date.today() for business date operations.
        Example: Daily statistics should use Tashkent calendar day.
    """
    return get_current_business_time().date()


def to_tashkent(utc_dt: datetime) -> datetime:
    """
    Convert UTC datetime to Tashkent timezone.
    
    Args:
        utc_dt: Datetime in UTC (or timezone-aware)
        
    Returns:
        Datetime in Tashkent timezone
        
    Usage:
        Convert stored UTC timestamps to business timezone for display/logic.
    """
    if utc_dt.tzinfo is None:
        # Assume UTC if naive (defensive)
        utc_dt = UTC_TZ.localize(utc_dt)
    return utc_dt.astimezone(TASHKENT_TZ)


def to_utc(tashkent_dt: datetime) -> datetime:
    """
    Convert Tashkent datetime to UTC.
    
    Args:
        tashkent_dt: Datetime in Tashkent timezone
        
    Returns:
        Datetime in UTC
        
    Usage:
        Convert business timezone timestamps to UTC for storage.
    """
    if tashkent_dt.tzinfo is None:
        # Assume Tashkent if naive (defensive)
        tashkent_dt = TASHKENT_TZ.localize(tashkent_dt)
    return tashkent_dt.astimezone(UTC_TZ)


def tashkent_date_to_utc_range(business_date: date) -> tuple[datetime, datetime]:
    """
    Convert a business date (Tashkent calendar day) to UTC datetime range.
    
    This is critical for date-based queries. A "day" in Tashkent timezone
    maps to a specific UTC time range that may span two UTC calendar days.
    
    Args:
        business_date: Date in Tashkent calendar (e.g., date(2024, 1, 15))
        
    Returns:
        Tuple of (start_utc, end_utc) covering the entire business day in UTC
        
    Usage:
        Use this for all date-based database queries to ensure correct filtering.
        
    Example:
        >>> start, end = tashkent_date_to_utc_range(date(2024, 1, 15))
        >>> # Returns UTC boundaries that cover Jan 15 in Tashkent timezone
    """
    # Create datetime boundaries in Tashkent timezone
    start_tashkent = TASHKENT_TZ.localize(datetime.combine(business_date, time.min))
    end_tashkent = TASHKENT_TZ.localize(datetime.combine(business_date, time.max))
    
    # Convert to UTC for database queries
    start_utc = start_tashkent.astimezone(UTC_TZ)
    end_utc = end_tashkent.astimezone(UTC_TZ)
    
    return start_utc, end_utc


def utc_to_tashkent_date(utc_dt: datetime) -> date:
    """
    Convert UTC datetime to Tashkent calendar date.
    
    Args:
        utc_dt: Datetime in UTC
        
    Returns:
        Date in Tashkent calendar (which day it is in Tashkent)
        
    Usage:
        Extract the "business date" from a UTC timestamp.
        Use this to determine which calendar day a timestamp belongs to.
    """
    if utc_dt.tzinfo is None:
        # Assume UTC if naive (defensive)
        utc_dt = UTC_TZ.localize(utc_dt)
    return to_tashkent(utc_dt).date()


def ensure_timezone_aware(dt: datetime, assume_utc: bool = True) -> datetime:
    """
    Ensure datetime is timezone-aware (defensive utility).
    
    Args:
        dt: Datetime object (may be naive)
        assume_utc: If naive, assume UTC (True) or Tashkent (False)
        
    Returns:
        Timezone-aware datetime
        
    Usage:
        Use this defensively when receiving datetime from external sources.
    """
    if dt.tzinfo is None:
        if assume_utc:
            return UTC_TZ.localize(dt)
        else:
            return TASHKENT_TZ.localize(dt)
    return dt


# Backward compatibility - deprecated, use get_current_time() instead
def get_current_utc_time() -> datetime:
    """
    Get current UTC time (deprecated - use get_current_time() instead).
    
    This function is kept for backward compatibility but will be removed.
    Use get_current_time() instead.
    """
    return get_current_time()
