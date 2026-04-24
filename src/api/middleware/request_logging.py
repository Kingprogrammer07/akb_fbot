"""FastAPI middleware for API request logging."""
import time
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.infrastructure.database.dao.api_request_log import APIRequestLogDAO

logger = logging.getLogger(__name__)


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
            
            # Log to database (non-blocking, safe)
            await self._log_request(
                request=request,
                method=method,
                endpoint=endpoint,
                user_id=user_id,
                response_status=response_status,
                response_time_ms=response_time_ms,
                error_message=None,
                ip_address=ip_address
            )
            
            return response
            
        except Exception as e:
            # Handle exceptions
            response_time_ms = int((time.time() - start_time) * 1000)
            error_message = str(e)
            response_status = 500
            
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
