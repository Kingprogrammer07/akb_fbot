"""Global API rate-limiting middleware.

Policy : 100 requests per 60 seconds per client IP.
Backend: Uses the shared async Redis pool (``request.app.state.redis``).
Excludes: /webhook, /static/, /health  — so Telegram updates and asset
           serving are never throttled.
"""
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------
RATE_LIMIT_MAX_REQUESTS = 100
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_KEY_PREFIX = "rate_limit:"

# Paths that should never be rate-limited
EXCLUDED_PATH_PREFIXES = ("/webhook", "/static/", "/health", "/shipment")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """IP-based rate limiter backed by Redis INCR + EXPIRE."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip excluded paths
        if any(path.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES):
            return await call_next(request)

        # Try to get Redis; if unavailable, let the request through
        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            return await call_next(request)

        # Determine client IP
        client_ip = self._get_client_ip(request)
        redis_key = f"{RATE_LIMIT_KEY_PREFIX}{client_ip}"

        try:
            # Atomic INCR — creates key with value 1 if it doesn't exist
            current_count = await redis.incr(redis_key)

            # Set expiry only on the FIRST request in the window
            if current_count == 1:
                await redis.expire(redis_key, RATE_LIMIT_WINDOW_SECONDS)

            if current_count > RATE_LIMIT_MAX_REQUESTS:
                ttl = await redis.ttl(redis_key)
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Too many requests. Please try again later.",
                        "retry_after_seconds": max(ttl, 1),
                    },
                    headers={"Retry-After": str(max(ttl, 1))},
                )

        except Exception as e:
            # Redis failure must never block legitimate traffic
            logger.warning(f"Rate-limit Redis error (allowing request): {e}")

        return await call_next(request)

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """Return the direct TCP peer address as the rate-limit key.

        We deliberately ignore X-Forwarded-For here because the header is
        trivially spoofable by any client: sending a unique fake IP on every
        request would create a fresh Redis counter each time, bypassing the
        limit entirely.  The connecting socket address (request.client.host)
        cannot be faked by the client and is set exclusively by the OS/proxy.

        If this service runs behind a trusted reverse proxy that terminates
        TLS and you need real-client IP granularity, inject the verified IP
        at the infrastructure level (e.g. Nginx `real_ip_from` + `set_real_ip`)
        so that request.client.host already carries the correct address by the
        time the request reaches this process.
        """
        if request.client:
            return request.client.host
        return "unknown"
