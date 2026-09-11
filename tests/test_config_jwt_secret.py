"""
Regression tests for the admin JWT signing secret.

``API_JWT_SECRET`` used to fall back to a placeholder that is committed to the
repository.  An unset environment variable therefore booted the API on a
publicly known secret, letting anyone mint a ``role: "super-admin"`` token and
bypass every RBAC check.  The secret must now be rejected at startup unless it
is present, non-placeholder and long enough to be meaningful for HMAC.
"""
import pytest
from pydantic import SecretStr, ValidationError

from src.config import APIConfig

PLACEHOLDER = "changeme-please-set-a-real-secret-in-env-min-32-chars"
VALID_SECRET = "a" * 32


def build(secret: str) -> APIConfig:
    return APIConfig(JWT_SECRET=SecretStr(secret))


def test_placeholder_secret_is_rejected():
    with pytest.raises(ValidationError, match="API_JWT_SECRET"):
        build(PLACEHOLDER)


def test_empty_secret_is_rejected():
    with pytest.raises(ValidationError, match="API_JWT_SECRET"):
        build("")


def test_short_secret_is_rejected():
    with pytest.raises(ValidationError, match="32"):
        build("a" * 31)


def test_whitespace_only_secret_is_rejected():
    with pytest.raises(ValidationError, match="API_JWT_SECRET"):
        build(" " * 40)


def test_secret_of_exactly_32_chars_is_accepted():
    assert build(VALID_SECRET).JWT_SECRET.get_secret_value() == VALID_SECRET


def test_long_secret_is_accepted():
    secret = "f3a" * 30
    assert build(secret).JWT_SECRET.get_secret_value() == secret


def test_there_is_no_usable_default(monkeypatch):
    """
    The field must have no fallback at all: an unset ``API_JWT_SECRET`` has to
    fail loudly rather than silently boot on a known value.
    """
    monkeypatch.delenv("API_JWT_SECRET", raising=False)

    with pytest.raises(ValidationError):
        APIConfig(_env_file=None)
