"""Validation utilities for passport and PINFL."""
import re
from datetime import date, datetime
from src.infrastructure.tools.datetime_utils import get_current_time


# O'zbekistonda tug'ilgan fuqarolarning passport seriyalari (mahalliy)
UZBEKISTAN_NATIVE_PASSPORT_SERIES = [
    'AA', 'AB', 'AC', 'AD', 'AE', 'AF', 'AG', 'AH', 'AI', 'AJ', 'AK', 'AL', 'AM', 'AN',
    'BC', 'BD', 'BE', 'BF', 'BG', 'BH', 'BI', 'BJ', 'BK', 'BL', 'BM', 'BN', "K", 'KA'
]


def validate_uzbekistan_passport(passport: str | None, translator: callable = None) -> tuple[bool, str | None]:
    """
    Validate Uzbekistan passport series.

    Format: 2 capital letters + 7 digits (e.g., AA1234567)

    Returns:
        tuple: (is_valid, error_message)
    """

    # Default translator if not provided
    def _(key):
        return key

    if translator:
        _ = translator

    if not passport:
        return False, _("passport-series-not-match")

    # Remove spaces and convert to uppercase
    passport = passport.strip().upper().replace(" ", "")

    # Check format: 2 letters + 7 digits
    regex = re.compile(r'^([A-Z]{2})(\d{7})$')
    match = regex.match(passport)

    if not match:
        return False, _("passport-series-not-match")

    series = match.group(1)

    if series not in UZBEKISTAN_NATIVE_PASSPORT_SERIES:
        return False, _("passport-series-incorrect-format", series=series)

    return True, None


def validate_pinfl(pinfl: str | None, translator: callable = None) -> tuple[bool, str | None]:
    """
    Validate PINFL (14 digits).

    First digit must be 3, 4, 5, or 6.

    Returns:
        tuple: (is_valid, error_message)
    """
    # Default translator if not provided
    def _(key):
        return key

    if translator:
        _ = translator

    if not pinfl:
        return False, _("pinfl-incorrect-format")

    # Remove spaces
    pinfl = pinfl.strip().replace(" ", "")

    # Check if 14 digits
    if not re.match(r'^\d{14}$', pinfl):
        return False, _("pinfl-must-be-14-digits")

    # Check first digit
    first_digit = int(pinfl[0])
    if first_digit not in [3, 4, 5, 6]:
        return False, _("pinfl-incorrect-format")

    return True, None


def validate_date_of_birth(date_str: str | None, translator: callable = None) -> tuple[bool, str | None, date | None]:
    """
    Validate date of birth (DD.MM.YYYY or DD/MM/YYYY format).

    Must be at least 16 years old.

    Returns:
        tuple: (is_valid, error_message, parsed_date)
    """

    # Default translator if not provided
    def _(key):
        return key

    if translator:
        _ = translator

    if not date_str:
        return False, _("date-of-birth-incorrect-format"), None

    # Try parsing different formats
    for fmt in ['%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y']:
        try:
            birth_date = datetime.strptime(date_str.strip(), fmt).date()
            break
        except ValueError:
            continue
    else:
        return False, _("date-of-birth-incorrect-format"), None

    # Check if date is not in future (Tashkent timezone)
    today = get_current_time().date()
    if birth_date > today:
        return False, _("date-of-birth-not-in-future"), None

    # Calculate age
    age = today.year - birth_date.year
    if today.month < birth_date.month or (today.month == birth_date.month and today.day < birth_date.day):
        age -= 1

    # Check minimum age (16 years)
    if age < 16:
        return False, _("date-of-birth-too-young"), None

    # Check maximum reasonable age (150 years)
    if age > 150:
        return False, _("date-of-birth-incorrect"), None

    return True, None, birth_date
