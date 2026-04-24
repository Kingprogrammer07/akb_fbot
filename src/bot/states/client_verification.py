"""FSM states for admin client verification."""
from aiogram.fsm.state import State, StatesGroup


class ClientVerificationStates(StatesGroup):
    """States for client verification flow."""

    waiting_for_client_code = State()  # Waiting for client code input
    waiting_for_flight_code = State()  # Waiting for flight code input
