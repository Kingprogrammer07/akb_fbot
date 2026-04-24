"""Broadcast keyboard builders."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


class BroadcastKeyboards:
    """Factory for broadcast-related keyboards."""
    
    @staticmethod
    def main_menu(total_users: int) -> InlineKeyboardMarkup:
        """Main broadcast menu."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="➕ Reklama yaratish",
                callback_data="broadcast_create"
            )],
            [InlineKeyboardButton(
                text="📊 Reklama tarixi",
                callback_data="broadcast_history"
            )],
            [InlineKeyboardButton(
                text="❌ Yopish",
                callback_data="broadcast_cancel"
            )]
        ])
    
    @staticmethod
    def audience_selection() -> InlineKeyboardMarkup:
        """Audience type selection keyboard."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="👥 Barcha foydalanuvchilarga",
                callback_data="broadcast_audience_all"
            )],
            [InlineKeyboardButton(
                text="🎯 Tanlangan foydalanuvchilarga",
                callback_data="broadcast_audience_selected"
            )],
            [InlineKeyboardButton(
                text="✈️ Reys bo'yicha xabar",
                callback_data="broadcast_audience_flight"
            )],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="broadcast_cancel")]
        ])

    @staticmethod
    def media_type_selection() -> InlineKeyboardMarkup:
        """Media type selection keyboard."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📸 Rasm", callback_data="broadcast_media_photo"),
                InlineKeyboardButton(text="🎬 Video", callback_data="broadcast_media_video")
            ],
            [
                InlineKeyboardButton(text="📄 Hujjat", callback_data="broadcast_media_document"),
                InlineKeyboardButton(text="🎵 Audio", callback_data="broadcast_media_audio")
            ],
            [
                InlineKeyboardButton(text="🎤 Ovoz", callback_data="broadcast_media_voice"),
                InlineKeyboardButton(text="💬 Matn", callback_data="broadcast_media_text")
            ],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="broadcast_cancel")]
        ])
    
    @staticmethod
    def media_collection_menu(count: int) -> InlineKeyboardMarkup:
        """Add more media or finish collection."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="➕ Yana qo'shish",
                callback_data="broadcast_add_media"
            )],
            [InlineKeyboardButton(
                text=f"✅ Davom etish ({count} ta)",
                callback_data="broadcast_finish_media"
            )],
            [InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data="broadcast_cancel"
            )]
        ])

    @staticmethod
    def caption_options() -> InlineKeyboardMarkup:
        """Caption editing options."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Caption qo'shish", callback_data="broadcast_add_caption")],
            [InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="broadcast_skip_caption")]
        ])
    
    @staticmethod
    def button_options() -> InlineKeyboardMarkup:
        """Button management options."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Tugma qo'shish", callback_data="broadcast_add_button")],
            [InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="broadcast_skip_buttons")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="broadcast_cancel")]
        ])
    
    @staticmethod
    def more_buttons() -> InlineKeyboardMarkup:
        """Add more buttons or finish."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yana tugma qo'shish", callback_data="broadcast_add_button")],
            [InlineKeyboardButton(text="✅ Tayyor", callback_data="broadcast_skip_buttons")]
        ])
    
    @staticmethod
    def confirmation() -> InlineKeyboardMarkup:
        """Final confirmation before sending."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Tasdiqlash va yuborish",
                callback_data="broadcast_confirm"
            )],
            [InlineKeyboardButton(
                text="✏️ Qayta tahrirlash",
                callback_data="broadcast_create"
            )],
            [InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data="broadcast_cancel"
            )]
        ])
    
    @staticmethod
    def stop_broadcast(task_id: str) -> InlineKeyboardMarkup:
        """Stop button for active broadcast."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="⏸ To'xtatish",
                callback_data=f"broadcast_stop:{task_id}"
            )]
        ])
    
    @staticmethod
    def history_pagination(current_page: int, total_pages: int) -> InlineKeyboardMarkup:
        """Pagination keyboard for broadcast history."""
        buttons = []
        
        # Navigation buttons
        nav_row = []
        if current_page > 0:
            nav_row.append(InlineKeyboardButton(
                text="◀️ Oldingi",
                callback_data=f"broadcast_history_page:{current_page - 1}"
            ))
        
        if current_page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(
                text="Keyingi ▶️",
                callback_data=f"broadcast_history_page:{current_page + 1}"
            ))
        
        if nav_row:
            buttons.append(nav_row)
        

        
        return InlineKeyboardMarkup(inline_keyboard=buttons)