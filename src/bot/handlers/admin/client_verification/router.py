"""Main router that combines all client verification sub-routers."""
from aiogram import Router

from . import entry
from . import client_info
from . import flights
from . import paid
from . import unpaid
from . import account_payment
from . import cash_payment
from . import cargos


def create_client_verification_router() -> Router:
    """Create and configure the main client verification router."""
    router = Router()

    # Include all sub-routers
    router.include_router(entry.router)
    router.include_router(client_info.router)
    router.include_router(flights.router)
    router.include_router(paid.router)
    router.include_router(unpaid.router)
    router.include_router(account_payment.router)
    router.include_router(cash_payment.router)
    router.include_router(cargos.router)

    return router


# Create the main router instance for backwards compatibility
client_verification_router = create_client_verification_router()
