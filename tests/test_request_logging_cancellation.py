"""
Request logging must not swallow cancellation.

``RequestLoggingMiddleware._log_request`` wrote the log row inside
``try/except/finally`` with ``break`` in the ``finally`` clause.  A ``break``
there discards the exception in flight, so a request cancelled while its log
row was being written (client disconnect, server shutdown, a timeout wrapped
around the request) ran on as if it had never been cancelled.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from src.api.middleware.request_logging import RequestLoggingMiddleware
from src.infrastructure.database.dao.api_request_log import APIRequestLogDAO

MIDDLEWARE_LOGGER = "src.api.middleware.request_logging"
ENDPOINT = "/api/v1/flights"
# Turns a regression into a test failure instead of a hung test run.
HANG_GUARD = 5.0


class FakeSession:
    """Records how the middleware ended its unit of work."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeDatabaseClient:
    """Hands out sessions in order, the way ``DatabaseClient.get_session`` does.

    A plain async iterator, not an async generator: the middleware stops after
    the first session, and an abandoned async generator would be finalized by
    the event loop only after the test had ended.
    """

    def __init__(self, *sessions: FakeSession) -> None:
        self._sessions = iter(sessions)

    def get_session(self) -> AsyncIterator[FakeSession]:
        return self

    def __aiter__(self) -> AsyncIterator[FakeSession]:
        return self

    async def __anext__(self) -> FakeSession:
        session = next(self._sessions, None)
        if session is None:
            raise StopAsyncIteration
        return session


async def unreachable_app(_scope: Scope, _receive: Receive, _send: Send) -> None:
    raise AssertionError("dispatch() is called directly; the wrapped app never runs")


async def call_next(_request: Request) -> Response:
    return Response(status_code=200)


def build_middleware() -> RequestLoggingMiddleware:
    return RequestLoggingMiddleware(unreachable_app)


def build_request(db_client: FakeDatabaseClient) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("203.0.113.7", 50000),
            "root_path": "",
            "path": ENDPOINT,
            "raw_path": ENDPOINT.encode(),
            "query_string": b"",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace(db_client=db_client)),
        }
    )


async def test_cancellation_during_the_log_write_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_started = asyncio.Event()

    async def _slow_create(**_kwargs: object) -> None:
        write_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(APIRequestLogDAO, "create", staticmethod(_slow_create))
    request = build_request(FakeDatabaseClient(FakeSession()))

    task = asyncio.create_task(build_middleware().dispatch(request, call_next))
    await asyncio.wait_for(write_started.wait(), HANG_GUARD)
    task.cancel()
    done, _pending = await asyncio.wait({task}, timeout=HANG_GUARD)

    assert task in done
    assert task.cancelled(), (
        f"dispatch returned {task.result()!r} after being cancelled"
    )


async def test_a_failed_log_write_is_rolled_back_and_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def _failing_create(**_kwargs: object) -> None:
        raise OperationalError("INSERT INTO api_request_logs", {}, OSError("db down"))

    monkeypatch.setattr(APIRequestLogDAO, "create", staticmethod(_failing_create))
    session = FakeSession()

    with caplog.at_level(logging.WARNING, logger=MIDDLEWARE_LOGGER):
        response = await build_middleware().dispatch(
            build_request(FakeDatabaseClient(session)), call_next
        )

    assert response.status_code == 200
    assert session.rolled_back
    assert not session.committed
    assert any(
        "Failed to log request to database" in record.getMessage()
        for record in caplog.records
        if record.name == MIDDLEWARE_LOGGER
    )


async def test_only_the_first_session_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[FakeSession] = []

    async def _create(*, session: FakeSession, **_kwargs: object) -> None:
        used.append(session)

    monkeypatch.setattr(APIRequestLogDAO, "create", staticmethod(_create))
    first, second = FakeSession(), FakeSession()

    await build_middleware().dispatch(
        build_request(FakeDatabaseClient(first, second)), call_next
    )

    assert used == [first]
    assert first.committed
    assert not second.committed
