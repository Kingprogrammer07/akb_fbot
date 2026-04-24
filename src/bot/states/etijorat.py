"""FSM states for E-tijorat verification flow."""
from aiogram.fsm.state import State, StatesGroup


class ETijoratState(StatesGroup):
    """States for E-tijorat screenshot verification."""

    waiting_for_screenshot = State()  # Waiting for user to send E-tijorat screenshot
