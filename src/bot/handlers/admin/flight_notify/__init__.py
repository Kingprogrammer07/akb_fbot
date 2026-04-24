"""Flight-notify admin handler package.

Exports:
    flight_notify_router — aiogram Router to register on the dispatcher.
    FlightNotifyStates   — FSM state group (imported by broadcast/handler.py).
    render_flight_list   — public helper called by broadcast/handler.py to
                           bootstrap the flight-selection UI.
"""

from src.bot.handlers.admin.flight_notify.handler import render_flight_list, router
from src.bot.handlers.admin.flight_notify.states import FlightNotifyStates

flight_notify_router = router

__all__ = [
    "flight_notify_router",
    "FlightNotifyStates",
    "render_flight_list",
]
