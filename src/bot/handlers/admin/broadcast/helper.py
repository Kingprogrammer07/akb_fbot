"""Broadcast helper functions for state management."""

from aiogram.fsm.context import FSMContext
from src.bot.handlers.admin.broadcast.models import BroadcastContent


async def get_content_from_state(state: FSMContext) -> BroadcastContent:
    """
    Get BroadcastContent from FSM state.
    
    Args:
        state: FSM context
        
    Returns:
        BroadcastContent object
    """
    data = await state.get_data()
    content_dict = data.get("content", {})
    return BroadcastContent.from_dict(content_dict)


async def save_content_to_state(state: FSMContext, content: BroadcastContent):
    """
    Save BroadcastContent to FSM state.
    
    Args:
        state: FSM context
        content: BroadcastContent object to save
    """
    await state.update_data(content=content.to_dict())