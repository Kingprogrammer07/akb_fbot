"""Admin settings FSM states."""
from aiogram.fsm.state import State, StatesGroup


class AdminSettingsStates(StatesGroup):
    """FSM states for admin settings editing."""

    # Static data editing
    waiting_for_foto_hisobot = State()
    waiting_for_extra_charge = State()
    waiting_for_price_per_kg = State()
    waiting_for_usd_rate = State()

    # Payment cards
    waiting_for_card_full_name = State()
    waiting_for_card_number = State()
    
    # Admin management
    waiting_for_admin_identifier = State()

