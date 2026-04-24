"""Broadcast FSM states."""

from aiogram.fsm.state import State, StatesGroup


class BroadcastStates(StatesGroup):
    """States for broadcast creation and delivery."""

    # Audience selection
    selecting_audience = State()
    waiting_for_client_codes = State()

    # Content creation flow
    selecting_media_type = State()
    waiting_for_media = State()
    waiting_for_next_media = State()
    waiting_for_caption = State()

    # Interactive elements
    adding_buttons = State()
    waiting_for_button_text = State()
    waiting_for_button_url = State()

    # Confirmation and execution
    preview = State()
    sending = State()