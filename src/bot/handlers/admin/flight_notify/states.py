"""FSM states for the flight-notify workflow."""

from aiogram.fsm.state import State, StatesGroup


class FlightNotifyStates(StatesGroup):
    """State machine for sending personalised track-code notifications per flight.

    Transitions:
        selecting_flight  →  waiting_for_text  →  preview  →  sending
        preview  →  waiting_for_text  (admin edits text)
        any  →  cleared  (cancel)
    """

    selecting_flight = State()
    """Paginated inline keyboard listing recent flights."""

    waiting_for_text = State()
    """Admin types the custom message appended after the track-code block."""

    preview = State()
    """Shows a sample notification and asks for confirmation."""

    sending = State()
    """Active send in progress; a stop button is displayed."""
