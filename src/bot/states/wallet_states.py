"""Wallet FSM states."""
from aiogram.fsm.state import State, StatesGroup


class WalletStates(StatesGroup):
    """FSM states for wallet user flows."""

    # Refund flow
    waiting_for_refund_card_number = State()
    waiting_for_refund_holder_name = State()
    waiting_for_refund_amount = State()

    # Debt payment flow
    waiting_for_debt_receipt = State()

    # Card management
    waiting_for_new_card_number = State()
    waiting_for_new_card_holder = State()


class WalletAdminStates(StatesGroup):
    """FSM states for admin wallet actions."""

    # Refund confirmation
    waiting_for_refund_actual_amount = State()

    # Debt confirmation
    waiting_for_debt_actual_amount = State()
