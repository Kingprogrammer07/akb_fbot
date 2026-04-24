"""Admin track check states."""
from aiogram.fsm.state import State, StatesGroup


class AdminTrackCheckStates(StatesGroup):
    """States for admin track code checking."""
    waiting_for_track_code = State()
