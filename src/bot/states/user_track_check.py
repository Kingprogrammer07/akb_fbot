"""User track check states."""
from aiogram.fsm.state import State, StatesGroup


class UserTrackCheckStates(StatesGroup):
    """States for user track code checking."""
    waiting_for_track_code = State()
