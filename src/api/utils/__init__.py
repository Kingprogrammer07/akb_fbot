"""API utilities."""
from src.api.utils.telegram import (
    send_registration_to_approval_group,
    send_waiting_message_to_user
)

__all__ = [
    'send_registration_to_approval_group',
    'send_waiting_message_to_user'
]
