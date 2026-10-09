"""Client-side validation failures are logged as warnings, not errors.

ERROR records are forwarded to the Telegram log channel when
LOG_TELEGRAM_ENABLED is on, so a malformed request from any client must not
page the team.  The details must still be logged, and the response body must
keep FastAPI's standard shape because the web client renders ``loc``/``msg``.
"""

import json
import logging

import pytest
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from src.bot import bot as bot_module


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
        }
    )


def _validation_error() -> RequestValidationError:
    return RequestValidationError(
        [
            {
                "type": "missing",
                "loc": ("query", "flight_name"),
                "msg": "Field required",
                "input": None,
            }
        ]
    )


def test_exactly_one_handler_is_registered_for_validation_errors() -> None:
    handler = bot_module.app.exception_handlers[RequestValidationError]
    assert handler is bot_module._debug_validation_error


async def test_validation_error_is_logged_as_warning_not_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exc = _validation_error()

    with caplog.at_level(logging.DEBUG, logger="src.bot.bot"):
        response = await bot_module.app.exception_handlers[RequestValidationError](
            _request("/api/v1/cargo/flight-status"), exc
        )

    records = [r for r in caplog.records if "RequestValidationError" in r.getMessage()]
    assert records, "the validation failure must still be logged"
    assert [r.levelno for r in records] == [logging.WARNING]
    assert "/api/v1/cargo/flight-status" in records[0].getMessage()

    assert response.status_code == 422
    assert json.loads(response.body) == {"detail": json.loads(json.dumps(exc.errors()))}


async def test_submitted_values_stay_out_of_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A rejected body can carry a PIN or a passport number; only the client sees it back."""
    secret = "4821-secret-pin"
    exc = RequestValidationError(
        [
            {
                "type": "string_too_short",
                "loc": ("body", "pin"),
                "msg": "String should have at least 6 characters",
                "input": secret,
            }
        ]
    )

    with caplog.at_level(logging.DEBUG, logger="src.bot.bot"):
        response = await bot_module.app.exception_handlers[RequestValidationError](
            _request("/api/v1/auth/login"), exc
        )

    messages = [
        r.getMessage()
        for r in caplog.records
        if "RequestValidationError" in r.getMessage()
    ]
    assert messages and "('body', 'pin')" in messages[0]
    assert all(secret not in message for message in messages)
    assert json.loads(response.body)["detail"][0]["input"] == secret


async def test_a_validator_exception_in_ctx_still_yields_a_422() -> None:
    """A field validator's ValueError sits in ``ctx``; it must not turn into a 500."""
    exc = RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "card_number"),
                "msg": "Value error, Card number must be 16 digits",
                "input": "1234",
                "ctx": {"error": ValueError("Card number must be 16 digits")},
            }
        ]
    )

    response = await bot_module.app.exception_handlers[RequestValidationError](
        _request("/api/v1/wallet/cards"), exc
    )

    assert response.status_code == 422
    [error] = json.loads(response.body)["detail"]
    assert (error["loc"], error["msg"]) == (
        ["body", "card_number"],
        "Value error, Card number must be 16 digits",
    )
