"""Client Verification API routers."""
from .payments_pos import router as payments_pos_router
from .payments_router import router as payments_router
from .transactions_router import router as transactions_router
from .verification_router import router as verification_router

__all__ = [
    "verification_router",
    "transactions_router",
    "payments_router",
    "payments_pos_router",
]
