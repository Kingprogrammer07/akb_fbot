"""
Client verification module for admin handlers.

This module provides functionality for admins to verify clients,
view their payments, mark cargo as taken, and process payments.

Module structure:
- entry.py: Entry handlers (start verification, process client code)
- client_info.py: Full client information display
- flights.py: Flight selection handlers
- paid.py: Paid payments list with filters and pagination
- unpaid.py: Unpaid payments handlers
- account_payment.py: Click/Payme payment handlers
- cash_payment.py: Cash payment handlers
- cargos.py: Cargo photos display
- keyboards.py: Keyboard builders
- utils.py: Utility functions
- router.py: Main router combining all sub-routers
"""
from .router import client_verification_router
from .utils import (
    VERIFICATION_CONTEXT,
    safe_answer_callback,
    encode_flight_code,
    decode_flight_code,
    get_unpaid_payments_for_client,
)
from .keyboards import get_client_webapp_keyboard

__all__ = [
    "client_verification_router",
    "VERIFICATION_CONTEXT",
    "safe_answer_callback",
    "encode_flight_code",
    "decode_flight_code",
    "get_unpaid_payments_for_client",
    "get_client_webapp_keyboard",
]
