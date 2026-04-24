"""States for adding extra passport."""
from aiogram.fsm.state import State, StatesGroup


class AddPassportStates(StatesGroup):
    """States for adding extra passport flow."""

    waiting_for_passport_series = State()
    waiting_for_pinfl = State()
    waiting_for_date_of_birth = State()
    waiting_for_document_type = State()  # ID card or Passport
    waiting_for_images = State()
    confirm_save = State()
