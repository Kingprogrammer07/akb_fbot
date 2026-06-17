"""FastAPI middleware for API request logging."""
import json
import time
import logging
from typing import Any, Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.infrastructure.database.dao.api_request_log import APIRequestLogDAO

logger = logging.getLogger(__name__)

_MAX_ERROR_MESSAGE_LENGTH = 12000


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all API requests to database.
    
    Logs:
    - HTTP method and endpoint
    - Response status code
    - Response time in milliseconds
    - Error messages (if any)
    - User ID (if available from request state)
    - IP address
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and log to database."""
        start_time = time.time()
        
        # Initialize all variables BEFORE try block to ensure they exist in exception handlers
        method = request.method
        endpoint = str(request.url.path)
        ip_address = None
        user_id = None
        response_status = 500
        error_message = None
        response_time_ms = 0
        
        # Extract IP address
        try:
            if request.client:
                ip_address = request.client.host
            elif "x-forwarded-for" in request.headers:
                ip_address = request.headers["x-forwarded-for"].split(",")[0].strip()
        except Exception:
            pass  # IP extraction failed, continue with None
        
        # Extract user_id from request state (if available)
        # This is set by authentication middleware or handlers
        try:
            user_id = getattr(request.state, "user_id", None)
        except Exception:
            pass  # User ID extraction failed, continue with None
        
        # Skip logging for health check endpoint
        if endpoint == "/health":
            return await call_next(request)
        
        try:
            # Process request
            response = await call_next(request)
            response_status = response.status_code
            response_time_ms = int((time.time() - start_time) * 1000)
            user_id = self._get_state_user_id(request, user_id)
            error_message = None
            if response_status >= 400:
                response, response_body = await self._clone_response_with_body(response)
                error_message = self._build_error_message(
                    request=request,
                    response_status=response_status,
                    response_body=response_body,
                )
                self._log_http_error(
                    method=method,
                    endpoint=endpoint,
                    response_status=response_status,
                    response_time_ms=response_time_ms,
                    error_message=error_message,
                )
            
            # Log to database (non-blocking, safe)
            await self._log_request(
                request=request,
                method=method,
                endpoint=endpoint,
                user_id=user_id,
                response_status=response_status,
                response_time_ms=response_time_ms,
                error_message=error_message,
                ip_address=ip_address
            )
            
            return response
            
        except Exception as e:
            # Handle exceptions
            response_time_ms = int((time.time() - start_time) * 1000)
            user_id = self._get_state_user_id(request, user_id)
            error_message = self._build_error_message(
                request=request,
                response_status=response_status,
                exception=e,
            )
            response_status = 500
            logger.exception(
                "Unhandled API request error: %s %s - %s (%sms): %s",
                method,
                endpoint,
                response_status,
                response_time_ms,
                error_message,
            )
            
            # Log error to database (non-blocking, safe)
            await self._log_request(
                request=request,
                method=method,
                endpoint=endpoint,
                user_id=user_id,
                response_status=response_status,
                response_time_ms=response_time_ms,
                error_message=error_message,
                ip_address=ip_address
            )
            
            # Re-raise exception
            raise

    @staticmethod
    def _truncate(value: str, limit: int = _MAX_ERROR_MESSAGE_LENGTH) -> str:
        """Keep DB log rows useful without allowing very large error payloads."""
        if len(value) <= limit:
            return value
        return f"{value[:limit]}... [truncated {len(value) - limit} chars]"

    @staticmethod
    def _json_dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))

    @staticmethod
    def _get_state_user_id(request: Request, fallback: int | None) -> int | None:
        try:
            return getattr(request.state, "user_id", fallback)
        except Exception:
            return fallback

    @staticmethod
    def _decode_response_body(response_body: bytes) -> str | None:
        if not response_body:
            return None
        text = response_body.decode("utf-8", errors="replace")
        try:
            return RequestLoggingMiddleware._json_dumps(json.loads(text))
        except json.JSONDecodeError:
            return text

    @staticmethod
    async def _clone_response_with_body(response: Response) -> tuple[Response, bytes]:
        """
        Read an error response body for logging and recreate the response.

        Starlette responses returned by ``call_next`` are often streaming
        wrappers. Reading the iterator consumes it, so we return a fresh
        Response with the same payload.
        """
        body = b""
        body_iterator = getattr(response, "body_iterator", None)
        if body_iterator is None:
            body = getattr(response, "body", b"") or b""
        else:
            async for chunk in body_iterator:
                if isinstance(chunk, str):
                    chunk = chunk.encode()
                body += chunk

        cloned = Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
            background=response.background,
        )
        return cloned, body

    def _build_error_message(
        self,
        request: Request,
        response_status: int,
        response_body: bytes | None = None,
        exception: Exception | None = None,
    ) -> str:
        parts: list[str] = [f"status={response_status}"]
        if exception is not None:
            parts.append(f"exception={type(exception).__name__}: {exception}")

        decoded_body = self._decode_response_body(response_body or b"")
        if decoded_body:
            parts.append(f"response={decoded_body}")

        context = getattr(request.state, "error_context", None)
        if context is not None:
            parts.append(f"context={self._json_dumps(context)}")

        return self._truncate(" | ".join(parts))

    @staticmethod
    def _log_http_error(
        method: str,
        endpoint: str,
        response_status: int,
        response_time_ms: int,
        error_message: str,
    ) -> None:
        log_args = (
            "API request returned error: %s %s - %s (%sms): %s",
            method,
            endpoint,
            response_status,
            response_time_ms,
            error_message,
        )
        if response_status >= 500:
            logger.error(*log_args)
        else:
            logger.warning(*log_args)
    
    async def _log_request(
        self,
        request: Request,
        method: str,
        endpoint: str,
        user_id: int | None,
        response_status: int,
        response_time_ms: int,
        error_message: str | None,
        ip_address: str | None
    ) -> None:
        """
        Log request to database (non-blocking, safe).
        
        Must never raise exceptions - failures are silently logged.
        """
        try:
            # Get database client from app state
            db_client = request.app.state.db_client
            
            if not db_client:
                logger.warning("Database client not available for request logging")
                return
            
            # Get session and log request
            async for session in db_client.get_session():
                try:
                    await APIRequestLogDAO.create(
                        session=session,
                        method=method,
                        endpoint=endpoint,
                        response_status=response_status,
                        response_time_ms=response_time_ms,
                        user_id=user_id,
                        error_message=error_message,
                        ip_address=ip_address
                    )
                    await session.commit()
                    logger.debug(f"Logged request: {method} {endpoint} - {response_status} ({response_time_ms}ms)")
                except Exception as e:
                    await session.rollback()
                    logger.warning(f"Failed to log request to database: {e}", exc_info=True)
                finally:
                    break  # Only use first session
                    
        except Exception as e:
            # Silent failure - request logging must never break main flow
            logger.warning(f"Failed to log request: {e}", exc_info=True)
