"""Registration errors name the field, never what the applicant typed.

``str(ValidationError)`` quotes its input, so the 400 body - stored with the
request in ``api_request_logs`` - used to carry the passport series, PINFL and
phone number of anyone whose registration failed validation.  The database
engine did the same for a failing statement until ``hide_parameters=True``.
"""

import pytest
from pydantic import ValidationError

from src.api.routers.auth import _rejected_fields
from src.bot.utils.i18n import i18n
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.schemas.auth import RegisterRequest

PASSPORT = "AB1234567"
PINFL = "12345678901234"
PHONE = "+7999123456"
"""A Russian number: the validator rejects anything but +998XXXXXXXXX."""

SECRETS = (PASSPORT, PINFL, PHONE)


def _rejected() -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        RegisterRequest(
            full_name="Ali Valiyev",
            passport_series=PASSPORT,
            pinfl=PINFL,
            region="Toshkent",
            district="Chilonzor",
            address="Bunyodkor 12",
            phone_number=PHONE,
            date_of_birth="1990-01-01",
        )
    return caught.value


def test_the_rejected_input_is_in_the_exception_text() -> None:
    """Why this exists: pydantic's own message quotes the submitted value."""
    assert PHONE in str(_rejected())


def test_only_field_names_are_reported() -> None:
    fields = _rejected_fields(_rejected())

    assert fields == "phone_number"
    for secret in SECRETS:
        assert secret not in fields


def test_a_plain_value_error_reports_no_field() -> None:
    """``date.fromisoformat`` raises before the model is built."""
    assert _rejected_fields(ValueError(f"Invalid isoformat string: '{PINFL}'")) == ""


@pytest.mark.parametrize("language", ["uz", "ru"])
def test_the_messages_the_endpoint_returns_carry_no_input(language: str) -> None:
    fields = i18n.get(language, "api-error-invalid-fields", fields="phone_number")
    submission = i18n.get(language, "api-error-invalid-submission")
    retry = i18n.get(language, "api-error-registration-retry")

    assert "phone_number" in fields
    for message, key in (
        (fields, "api-error-invalid-fields"),
        (submission, "api-error-invalid-submission"),
        (retry, "api-error-registration-retry"),
    ):
        # A missing key comes back as the key itself.
        assert message != key
        assert "{" not in message
        for secret in SECRETS:
            assert secret not in message


def test_the_engine_hides_statement_parameters() -> None:
    """A failing INSERT must not put a passport number in the error text."""
    client = DatabaseClient("postgresql+asyncpg://u:p@localhost:5432/akb_t_unused")

    assert client.engine.sync_engine.hide_parameters is True
