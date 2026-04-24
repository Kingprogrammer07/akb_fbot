"""FSM states for approval workflow."""
from aiogram.fsm.state import State, StatesGroup


class ApprovalStates(StatesGroup):
    """States for client approval workflow."""
    waiting_for_reject_reason = State()


class AdminClientSearchStates(StatesGroup):
    """States for admin client search workflow."""
    waiting_for_client_code = State()
