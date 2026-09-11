"""
The request log must not keep what a client submitted in a rejected body.

``_debug_validation_error`` leaves ``input`` out of its own log line, but
``RequestLoggingMiddleware`` appended every error response body to its WARNING
line and to ``api_request_logs.error_message``.  A 422 body is
``{"detail": exc.errors()}`` and each item's ``input`` is the submitted value:
a PIN, a passport number, or for a missing field the whole submitted object.
Only the client that sent it gets it back.
"""

import logging
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.api.middleware.request_logging import RequestLoggingMiddleware
from src.bot import bot as bot_module
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.database.models.api_request_log import APIRequestLog

MIDDLEWARE_LOGGER = "src.api.middleware.request_logging"
LOGIN = "/api/v1/auth/login"
LOOKUP = "/api/v1/clients/lookup"
SECRET_PIN = "q7Zx2"  # one character short of the PIN rule
SECRET_PASSPORT = "AB7394821"
BUSINESS_ERROR = "Mijoz kodi noto'g'ri"


class PinLogin(BaseModel):
    passport: str
    pin: str = Field(min_length=6)


@pytest_asyncio.fixture
async def api(db_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    """The middleware and the production 422 handler around two small routes."""
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    app.add_exception_handler(
        RequestValidationError, bot_module._debug_validation_error
    )

    @app.post(LOGIN)
    async def login(body: PinLogin) -> dict[str, str]:
        return {"status": "ok"}

    @app.post(LOOKUP)
    async def lookup() -> dict[str, str]:
        raise HTTPException(status_code=422, detail=BUSINESS_ERROR)

    # The middleware writes api_request_logs through app.state.db_client.
    db_client = DatabaseClient(db_engine.url.render_as_string(hide_password=False))
    app.state.db_client = db_client
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        await db_client.shutdown()


def _request_error_line(caplog: pytest.LogCaptureFixture) -> str:
    """The middleware's single log line for the failed request."""
    [line] = [
        record.getMessage()
        for record in caplog.records
        if record.name == MIDDLEWARE_LOGGER
        and record.getMessage().startswith("API request returned error")
    ]
    return line


async def _stored_error_message(db_session: AsyncSession, path: str) -> str:
    """The single ``api_request_logs.error_message`` persisted for ``path``."""
    result = await db_session.execute(
        select(APIRequestLog.error_message).where(APIRequestLog.endpoint == path)
    )
    [message] = result.scalars().all()
    assert message is not None
    return message


async def test_a_rejected_pin_reaches_the_client_but_not_the_request_log(
    api: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger=MIDDLEWARE_LOGGER):
        response = await api.post(
            LOGIN, json={"passport": "AA0000001", "pin": SECRET_PIN}
        )

    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["loc"] == ["body", "pin"]
    assert error["input"] == SECRET_PIN

    stored = await _stored_error_message(db_session, LOGIN)
    # The failure itself is still recorded, only the submitted value is gone.
    for message in (_request_error_line(caplog), stored):
        assert '"type":"string_too_short","loc":["body","pin"]' in message
    assert all(SECRET_PIN not in record.getMessage() for record in caplog.records)
    assert SECRET_PIN not in stored


async def test_a_missing_field_does_not_log_the_whole_submitted_object(
    api: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    submitted = {"passport": SECRET_PASSPORT}

    with caplog.at_level(logging.DEBUG, logger=MIDDLEWARE_LOGGER):
        response = await api.post(LOGIN, json=submitted)

    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["type"] == "missing"
    assert error["input"] == submitted

    stored = await _stored_error_message(db_session, LOGIN)
    for message in (_request_error_line(caplog), stored):
        assert '"type":"missing","loc":["body","pin"]' in message
    assert all(SECRET_PASSPORT not in record.getMessage() for record in caplog.records)
    assert SECRET_PASSPORT not in stored


async def test_a_business_422_body_is_logged_as_before(
    api: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """A ``detail`` that is not a validation error list is left alone."""
    with caplog.at_level(logging.DEBUG, logger=MIDDLEWARE_LOGGER):
        response = await api.post(LOOKUP)

    assert response.status_code == 422
    assert response.json() == {"detail": BUSINESS_ERROR}

    expected = f'status=422 | response={{"detail":"{BUSINESS_ERROR}"}}'
    assert _request_error_line(caplog).endswith(expected)
    assert await _stored_error_message(db_session, LOOKUP) == expected
