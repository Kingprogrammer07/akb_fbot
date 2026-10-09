"""Stateless, client-scoped HMAC tokens that replace flight names in ``callback_data``."""

import inspect
import re
from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from src.bot.handlers.user import delivery_request, info, make_payment, profile
from src.bot.utils import flight_token as flight_token_module
from src.bot.utils.flight_token import (
    FLIGHT_TOKEN_LENGTH,
    client_token_scope,
    flight_token,
    resolve_flight_token,
)
from src.config import config

OWN_FLIGHT = "M9731-REAL"
OTHER_FLIGHT = "Q4402-REAL"
SCOPE_A = client_token_scope(101)
SCOPE_B = client_token_scope(202)
# The widest scope a client id (bigint) can produce.
WIDEST_SCOPE = client_token_scope(2**63 - 1)

# Every user callback prefix that carries a flight, plus the longest suffix
# ``info_flight`` appends (a row number up to the int4 maximum).
TOKEN_CALLBACK_TEMPLATES = (
    "info_flight:{token}:2147483647",
    "view_cargo_photos:{token}",
    "pay_flight:{token}",
    "payment_type:online:{token}",
    "payment_type:cash:{token}",
    "pay_full:{token}",
    "pay_full_remaining:{token}",
    "pay_partial:{token}",
    "enter_partial_amount:{token}",
    "payment_wallet_toggle:{token}",
    "payment_wallet_only:{token}",
    "cash_confirm:{token}",
    "select_flight:{token}",
)
HANDLER_MODULES = (delivery_request, info, make_payment, profile)
# ``callback_data=f"<prefix>{flight_token(...)}`` or ``...{token}`` in handler source.
TOKEN_PREFIX_PATTERN = re.compile(
    r'callback_data=f"([a-z_:]+)\{(?:flight_token\(|token\})'
)


@pytest.fixture(autouse=True)
def fresh_token_key() -> Iterator[None]:
    """The derived key is cached; never let one test's secret leak into another."""
    flight_token_module._token_key.cache_clear()
    yield
    flight_token_module._token_key.cache_clear()


def test_client_scope_names_the_client_account() -> None:
    assert client_token_scope(42) == "client:42"


def test_round_trip_returns_the_real_name() -> None:
    token = flight_token(OWN_FLIGHT, SCOPE_A)

    assert resolve_flight_token(token, [OTHER_FLIGHT, OWN_FLIGHT], SCOPE_A) == OWN_FLIGHT


def test_resolve_returns_the_allowed_element_with_its_whitespace() -> None:
    padded = f"  {OWN_FLIGHT}\n"
    token = flight_token(padded, SCOPE_A)

    assert token == flight_token(OWN_FLIGHT, SCOPE_A)
    # Returned untrimmed: DAO lookups compare the stored value as-is.
    assert resolve_flight_token(f" {token} ", [OTHER_FLIGHT, padded], SCOPE_A) == padded
    assert resolve_flight_token(token, [OWN_FLIGHT], SCOPE_A) == OWN_FLIGHT


def test_token_is_deterministic_and_fixed_length_hex() -> None:
    token = flight_token(OWN_FLIGHT, SCOPE_A)

    assert token == flight_token(OWN_FLIGHT, SCOPE_A)
    assert len(token) == FLIGHT_TOKEN_LENGTH
    int(token, 16)
    assert token != flight_token(OTHER_FLIGHT, SCOPE_A)


def test_same_flight_in_different_scopes_gives_different_tokens() -> None:
    assert flight_token(OWN_FLIGHT, SCOPE_A) != flight_token(OWN_FLIGHT, SCOPE_B)


def test_token_minted_for_one_client_does_not_resolve_for_another() -> None:
    allowed = [OWN_FLIGHT, OTHER_FLIGHT]
    token_for_a = flight_token(OWN_FLIGHT, SCOPE_A)

    assert resolve_flight_token(token_for_a, allowed, SCOPE_A) == OWN_FLIGHT
    assert resolve_flight_token(token_for_a, allowed, SCOPE_B) is None


def test_scope_and_name_cannot_be_shifted_across_the_separator() -> None:
    # Plain concatenation would make both messages "client:10-X".
    assert flight_token("0-X", "client:1") != flight_token("X", "client:10-")


@pytest.mark.parametrize("scope", ["", "client:1\x00", "\x00client:1"])
def test_empty_scope_or_scope_with_separator_is_refused(scope: str) -> None:
    with pytest.raises(ValueError):
        flight_token(OWN_FLIGHT, scope)
    with pytest.raises(ValueError):
        resolve_flight_token("0" * FLIGHT_TOKEN_LENGTH, [OWN_FLIGHT], scope)


def test_different_secret_gives_different_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = flight_token(OWN_FLIGHT, SCOPE_A)

    monkeypatch.setattr(config.api, "JWT_SECRET", SecretStr("r" * 64))
    flight_token_module._token_key.cache_clear()

    rotated = flight_token(OWN_FLIGHT, SCOPE_A)
    assert rotated != original
    assert resolve_flight_token(original, [OWN_FLIGHT], SCOPE_A) is None


def test_forged_token_is_rejected() -> None:
    forged = "0" * FLIGHT_TOKEN_LENGTH
    token = flight_token(OWN_FLIGHT, SCOPE_A)

    assert resolve_flight_token(forged, [OWN_FLIGHT, OTHER_FLIGHT], SCOPE_A) is None
    assert resolve_flight_token(token[:-1], [OWN_FLIGHT], SCOPE_A) is None
    assert resolve_flight_token(token.upper(), [OWN_FLIGHT], SCOPE_A) is None


def test_token_outside_the_allowed_set_is_rejected() -> None:
    token = flight_token(OTHER_FLIGHT, SCOPE_A)

    assert resolve_flight_token(token, [OWN_FLIGHT], SCOPE_A) is None


def test_raw_real_name_is_rejected_even_when_allowed() -> None:
    # Accepting it would let a client confirm guesses of the name behind a mask.
    assert resolve_flight_token(OWN_FLIGHT, [OWN_FLIGHT], SCOPE_A) is None
    assert resolve_flight_token(f"  {OWN_FLIGHT} ", [OWN_FLIGHT], SCOPE_A) is None
    assert resolve_flight_token(OWN_FLIGHT.lower(), [OWN_FLIGHT], SCOPE_A) is None


def test_empty_token_or_empty_allowed_set_gives_none() -> None:
    token = flight_token(OWN_FLIGHT, SCOPE_A)

    assert resolve_flight_token("", [OWN_FLIGHT], SCOPE_A) is None
    assert resolve_flight_token("   ", [OWN_FLIGHT], SCOPE_A) is None
    assert resolve_flight_token(token, [], SCOPE_A) is None
    assert resolve_flight_token(token, ["", "  "], SCOPE_A) is None


def test_non_ascii_flight_names_and_tokens() -> None:
    cyrillic = "Рейс-200"

    assert (
        resolve_flight_token(flight_token(cyrillic, SCOPE_A), [cyrillic], SCOPE_A)
        == cyrillic
    )
    assert resolve_flight_token("Рейс-999", [cyrillic], SCOPE_A) is None


@pytest.mark.parametrize("template", TOKEN_CALLBACK_TEMPLATES)
def test_longest_callback_payload_fits_telegram_limit(template: str) -> None:
    payload = template.format(token=flight_token("X" * 100, WIDEST_SCOPE))

    assert len(payload.encode("utf-8")) <= 64


def test_payload_templates_cover_every_token_prefix_in_the_handlers() -> None:
    in_source = {
        prefix
        for module in HANDLER_MODULES
        for prefix in TOKEN_PREFIX_PATTERN.findall(inspect.getsource(module))
    }
    templated = {template.split("{token}")[0] for template in TOKEN_CALLBACK_TEMPLATES}

    assert in_source == templated


def test_token_never_contains_the_real_name() -> None:
    # Real flight names always carry a non-hex character (``M``, ``Q``, ``-``),
    # and the token is pure lowercase hex, so no such name can appear in it.
    for name in (OWN_FLIGHT, OTHER_FLIGHT, "M200", "Q1", "AKB-150", "Рейс-200"):
        token = flight_token(name, SCOPE_A)
        assert set(token) <= set("0123456789abcdef")
        assert name not in token
        assert name.lower() not in token
