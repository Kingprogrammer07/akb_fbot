"""Money parsing utilities."""
import re
from decimal import Decimal, ROUND_HALF_UP


def money(value: float | int | Decimal) -> Decimal:
    """
    Normalize monetary value to 2 decimal places.
    
    Uses ROUND_HALF_UP to ensure consistent rounding.
    Returns Decimal to avoid float precision issues.
    """
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if not isinstance(value, (Decimal, str)) else Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_money(value: str) -> float:
    """
    Parse a formatted money string to float.
    
    Removes spaces, commas, and non-breaking spaces before converting to float.
    Handles user-facing formatted numbers like '1,144,789' or '1 144 789'.
    
    Args:
        value: String containing formatted money amount
        
    Returns:
        float: Parsed money amount
        
    Raises:
        ValueError: If value cannot be converted to float after cleaning
    """
    if not value:
        raise ValueError("Empty value cannot be converted to float")
    
    # Remove all spaces (including non-breaking spaces), commas, and other formatting characters
    cleaned = value.strip()
    
    # Remove spaces (regular and non-breaking)
    cleaned = cleaned.replace(" ", "").replace("\u00A0", "")  # \u00A0 is non-breaking space
    
    # Remove commas
    cleaned = cleaned.replace(",", "")
    
    # Try to convert to float
    try:
        return float(cleaned)
    except ValueError as e:
        raise ValueError(f"Could not convert '{value}' to float: {e}")

