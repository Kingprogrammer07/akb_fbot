"""
Telegram Bot with FastAPI Integration - Webhook Mode

This module runs both the Telegram bot (webhook) and FastAPI server in parallel.
Run with: python -m src.bot.bot
"""

import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import Update
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from src import config, setup_logging, start_telegram_logging, shutdown_logging
from src.bot.bot_instance import bot as bot_instance
from src.bot.handlers import ROUTERS
from src.bot.middlewares import (
    DatabaseMiddleware,
    ServiceMiddleware,
    RedisMiddleware,
    ThrottlingMiddleware,
    GlobalErrorMiddleware,
    LastSeenMiddleware,
)
from src.bot.middlewares.album_middleware import AlbumMiddleware
from src.bot.middlewares.i18n import I18nMiddleware
from src.bot.utils.bot_commands import set_default_commands
from src.bot.utils.startup_notify import notify_admins
from src.infrastructure.cache import RedisClient

# from src.infrastructure.cache.cache import Cache
from src.infrastructure.database.client import DatabaseClient
from src.infrastructure.services.client import ClientService
from src.infrastructure.services.payment_card import PaymentCardService
from src.infrastructure.services.client_transaction import ClientTransactionService
from src.infrastructure.services.cargo_item import CargoItemService
from src.infrastructure.services.flight_cargo import FlightCargoService
from src.api.routers.auth import router as auth_router
from src.api.routers.admin_auth import router as admin_auth_router
from src.api.middleware.partner_auth_swagger import custom_openapi
from src.api.routers.expected_cargo_router import router as expected_cargo_router
from src.api.routers.flight_schedule_router import router as flight_schedule_router
from src.api.routers.statistics.client_stats_router import router as client_stats_router
from src.api.routers.statistics.cargo_stats_router import router as cargo_stats_router
from src.api.routers.statistics.financial_stats_router import (
    router as financial_stats_router,
)
from src.api.routers.statistics.operational_stats_router import (
    router as operational_stats_router,
)
from src.api.routers.statistics.analytics_stats_router import (
    router as analytics_stats_router,
)
from src.api.routers.admin_management import router as admin_management_router
from src.api.routers.admin_clients_router import router as admin_clients_router
from src.api.routers.import_router import router as import_router
from src.api.routers.client_router import router as client_router
from src.api.routers.clients_router import router as clients_router
from src.api.routers.flights_router import router as flights_router
from src.api.routers.profile_router import router as profile_router
from src.api.routers.cargo import router as cargo_router
from src.api.routers.reports import router as reports_router
from src.api.routers.admin_carousel import router as admin_carousel_router
from src.api.routers.carousel import router as carousel_router
from src.api.routers.notifications import router as notifications_router
from src.api.routers.wallet import router as wallet_router
from src.api.routers.extra_passports import router as extra_passports_router
from src.api.routers.verification import (
    payments_pos_router,
    payments_router,
    transactions_router,
    verification_router,
)
from src.api.routers.delivery import router as delivery_router
from src.api.routers.user_delivery import router as user_delivery_router
from src.api.routers.make_payment import router as make_payment_router
from src.api.routers.payment_history import router as payment_history_router
from src.api.routers.calculator import router as calculator_router
from src.api.routers.admin_calculator import router as admin_calculator_router
from src.api.routers.china_address import router as china_address_router
from src.api.routers.warehouse_router import router as warehouse_router
from src.api.routers.shipment_router import router as shipment_router

from fastapi.staticfiles import StaticFiles
from src.api.middleware.request_logging import RequestLoggingMiddleware
from src.api.middleware.rate_limit import RateLimitMiddleware

logger = logging.getLogger(__name__)

# Global variables for bot and dispatcher
bot: Bot | None = None
dp: Dispatcher | None = None
redis_client: RedisClient | None = None
db_client: DatabaseClient | None = None


async def setup_bot() -> tuple[Bot, Dispatcher, RedisClient, DatabaseClient]:
    """Initialize bot, dispatcher, and services."""
    setup_logging(service_name="bot")

    # Start Telegram logging worker (must be called after event loop is running)
    start_telegram_logging()

    # Use the shared global bot instance from bot_instance.py

    redis_client_instance = RedisClient()
    try:
        redis = await redis_client_instance.connect()
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}", exc_info=True)
        raise RuntimeError("Bot setup failed") from e

    storage = RedisStorage(
        redis, state_ttl=config.redis.TTL or 3600, data_ttl=config.redis.TTL or 3600
    )
    dp_instance = Dispatcher(storage=storage)

    # cache = Cache(redis, default_ttl=config.redis.TTL)
    client_service = ClientService()
    payment_card_service = PaymentCardService()
    transaction_service = ClientTransactionService()
    cargo_service = CargoItemService()
    flight_cargo_service = FlightCargoService()
    services = {
        "client_service": client_service,
        "payment_card_service": payment_card_service,
        "transaction_service": transaction_service,
        "cargo_service": cargo_service,
        "flight_cargo_service": flight_cargo_service,
    }

    db_client_instance = DatabaseClient(config.database.database_url)

    # Register AlbumMiddleware FIRST on message level (before other middlewares)
    dp_instance.message.outer_middleware(AlbumMiddleware(latency=0.5))

    # Register GlobalErrorMiddleware as OUTERMOST (catches all errors including stale callbacks)
    dp_instance.update.outer_middleware(GlobalErrorMiddleware())

    # Register ThrottlingMiddleware (anti-spam, 0.5s limit)
    dp_instance.update.outer_middleware(ThrottlingMiddleware(redis=redis, limit=0.5))

    # Register other middlewares
    dp_instance.update.outer_middleware(DatabaseMiddleware(db_client_instance))
    dp_instance.update.outer_middleware(RedisMiddleware(redis))
    dp_instance.update.outer_middleware(ServiceMiddleware(services))
    dp_instance.update.outer_middleware(I18nMiddleware())
    # LastSeenMiddleware must come after DatabaseMiddleware so "session" is in data
    dp_instance.update.outer_middleware(LastSeenMiddleware())

    # Include all routers
    for router in ROUTERS:
        dp_instance.include_router(router)
    logger.debug(f"Included {len(ROUTERS)} routers")

    # Set default commands
    await set_default_commands(bot_instance)

    # Notify admins
    await notify_admins(bot_instance)

    # Start notification scheduler
    from src.bot.utils.notification_scheduler import start_notification_scheduler

    start_notification_scheduler(bot_instance)

    # Start backup scheduler
    from src.bot.utils.backup_scheduler import start_backup_scheduler

    start_backup_scheduler(bot_instance)

    logger.info("Bot setup completed")
    return bot_instance, dp_instance, redis_client_instance, db_client_instance


async def shutdown_bot():
    """Shutdown bot and close connections."""
    global bot, dp, redis_client, db_client

    logger.info("Shutting down bot")

    # Shutdown Telegram logging (drain queue before closing)
    try:
        await shutdown_logging(timeout=10.0)
    except Exception as e:
        logger.warning(f"Error shutting down Telegram logging: {e}")

    # Stop notification scheduler
    try:
        from src.bot.utils.notification_scheduler import stop_notification_scheduler

        await stop_notification_scheduler()
    except Exception as e:
        logger.warning(f"Error stopping notification scheduler: {e}")

    # Close the shared bot session from bot_instance.py
    from src.bot.bot_instance import bot as shared_bot

    if shared_bot:
        await shared_bot.session.close()
    if dp and dp.storage:
        await dp.storage.close()
    if db_client:
        await db_client.shutdown()
    if redis_client:
        await redis_client.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI."""
    global bot, dp, redis_client, db_client

    # Startup
    logger.info("Starting FastAPI application with Telegram webhook")
    bot, dp, redis_client, db_client = await setup_bot()

    # Store db_client and redis in app state for API access
    app.state.db_client = db_client
    app.state.redis = await redis_client.get_redis()  # Get Redis connection for API

    # Seed reference data (idempotent — safe to run on every startup).
    # seed_roles depends on seed_permissions having committed first, so the
    # two calls use separate sessions to guarantee the Permission rows are
    # visible before role assignment queries run.
    from src.infrastructure.database.seeders import seed_permissions, seed_roles

    async with db_client.session_factory() as seed_session:
        await seed_permissions(seed_session)
    async with db_client.session_factory() as seed_session:
        await seed_roles(seed_session)

    if webhook_url := config.telegram.WEBHOOK_URL:
        webhook_path = "/webhook"
        full_webhook_url = f"{webhook_url}{webhook_path}"
        try:
            await bot.set_webhook(url=full_webhook_url, drop_pending_updates=True)
            logger.info(f"Webhook set to: {full_webhook_url}")
        except Exception as e:
            logger.warning(
                f"Failed to set webhook: {e}. Bot will still run for API access."
            )
    else:
        logger.warning("No WEBHOOK_URL configured - webhook not set")

    yield

    # Shutdown
    await shutdown_bot()


# Create FastAPI application
app = FastAPI(
    title="AKB Bot API",
    description="Telegram Bot API with authentication endpoints",
    version="1.0.0",
    lifespan=lifespan,
)


# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.api.CORS_ORIGINS,
    allow_credentials=config.api.CORS_ALLOW_CREDENTIALS,
    allow_methods=config.api.CORS_ALLOW_METHODS,
    allow_headers=config.api.CORS_ALLOW_HEADERS,
)

# Add rate-limiting middleware (after CORS, before request logging)
app.add_middleware(RateLimitMiddleware)

# Add request logging middleware
app.add_middleware(RequestLoggingMiddleware)


@app.exception_handler(RequestValidationError)
async def _debug_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Validation error handler.

    Logs full validation details but returns a sanitized payload to clients in production.
    """
    import logging as _logging
    import os as _os

    logger = _logging.getLogger(__name__)

    # Always log full validation details for debugging/observability
    logger.error(
        "422 RequestValidationError on %s %s — errors: %s",
        request.method,
        request.url.path,
        exc.errors(),
    )

    # Gate detailed responses behind an environment flag
    debug_validation = _os.getenv("DEBUG_VALIDATION_ERRORS", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if debug_validation:
        # Useful for local/dev; mirrors FastAPI's default structure
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors()},
        )

    # Sanitized, user-friendly error response for production
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {
                    "code": "validation_error",
                    "message": "One or more fields failed validation.",
                }
            ]
        },
    )


@app.exception_handler(RequestValidationError)
async def _debug_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Temporary: log full validation errors to stdout for debugging."""
    import logging as _logging

    _logging.getLogger(__name__).error(
        "422 RequestValidationError on %s %s — errors: %s",
        request.method,
        request.url.path,
        exc.errors(),
    )
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


# Include API routers
app.include_router(auth_router)
app.include_router(admin_auth_router)
app.include_router(admin_management_router, prefix="/api/v1")
app.include_router(admin_clients_router, prefix="/api/v1")
# User Panel
app.include_router(profile_router, prefix="/api/v1")
app.include_router(cargo_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(admin_carousel_router, prefix="/api/v1")
app.include_router(carousel_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(wallet_router, prefix="/api/v1")
app.include_router(extra_passports_router, prefix="/api/v1")
app.include_router(user_delivery_router, prefix="/api")
app.include_router(import_router, prefix="/api/v1")
app.include_router(client_router, prefix="/api/v1")

app.openapi = lambda: custom_openapi(app)

app.include_router(clients_router, prefix="/api")
app.include_router(flights_router, prefix="/api/v1")

# Include Client Verification API routers
app.include_router(verification_router, prefix="/api/v1")
app.include_router(transactions_router, prefix="/api/v1")
app.include_router(payments_router, prefix="/api/v1")
app.include_router(payments_pos_router, prefix="/api/v1")
app.include_router(payment_history_router, prefix="/api/v1")
app.include_router(delivery_router, prefix="/api/v1")
app.include_router(make_payment_router, prefix="/api/v1")
app.include_router(calculator_router, prefix="/api/v1")
app.include_router(admin_calculator_router, prefix="/api/v1")
app.include_router(china_address_router, prefix="/api/v1")
app.include_router(warehouse_router, prefix="/api/v1")
app.include_router(shipment_router, prefix="/api/v1")
app.include_router(expected_cargo_router, prefix="/api/v1")
app.include_router(flight_schedule_router, prefix="/api/v1")
app.include_router(client_stats_router, prefix="/api/v1")
app.include_router(cargo_stats_router, prefix="/api/v1")
app.include_router(financial_stats_router, prefix="/api/v1")
app.include_router(operational_stats_router, prefix="/api/v1")
app.include_router(analytics_stats_router, prefix="/api/v1")

# Serve static asset files (images, etc.)
import pathlib

_assets_dir = pathlib.Path(__file__).resolve().parent.parent / "assets"
app.mount("/static", StaticFiles(directory=str(_assets_dir)), name="static")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "bot": "running" if bot else "not initialized",
        "redis": "connected" if redis_client else "not connected",
        "database": "connected" if db_client else "not connected",
    }


@app.post("/webhook")
async def webhook_handler(request: Request):
    """Handle Telegram webhook updates."""
    global bot, dp

    if not bot or not dp:
        return JSONResponse(status_code=503, content={"error": "Bot not initialized"})

    try:
        update_data = await request.json()
        update = Update(**update_data)
        await dp.feed_update(bot, update)
        return {"ok": True}
    except Exception as e:
        # Log the FULL traceback so the root cause of 500s is never silent
        logger.error(
            f"Error processing webhook update: {type(e).__name__}: {e}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"error": f"Internal server error: {type(e).__name__}"},
        )


if __name__ == "__main__":
    import asyncio

    # Run FastAPI with uvicorn
    uvicorn.run(app, host=config.api.HOST, port=config.api.PORT, log_level="info")
