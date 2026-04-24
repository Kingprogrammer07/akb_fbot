"""Inline keyboard builders for the flight-notify workflow."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

FLIGHTS_PER_PAGE = 8


class FlightNotifyKeyboards:
    """Factory for all keyboards used in the flight-notify FSM."""

    @staticmethod
    def flight_list(
        flights: list[str],
        page: int,
        total_pages: int,
        client_counts: dict[str, int],
    ) -> InlineKeyboardMarkup:
        """Paginated flight-selection keyboard.

        Args:
            flights:       Full ordered list of flight names (all pages combined).
            page:          Current 0-based page index.
            total_pages:   Total number of pages.
            client_counts: Mapping of flight_name → unique client count for display.

        Returns:
            Keyboard with up to ``FLIGHTS_PER_PAGE`` flight buttons plus
            pagination and cancel rows.
        """
        start = page * FLIGHTS_PER_PAGE
        page_flights = flights[start : start + FLIGHTS_PER_PAGE]

        rows: list[list[InlineKeyboardButton]] = []

        for flight in page_flights:
            count = client_counts.get(flight, 0)
            label = f"✈️ {flight} ({count} mijoz)" if count else f"✈️ {flight}"
            rows.append(
                [InlineKeyboardButton(text=label, callback_data=f"fn_select_flight:{flight}")]
            )

        # Pagination row — only rendered when there is more than one page
        if total_pages > 1:
            nav: list[InlineKeyboardButton] = []
            if page > 0:
                nav.append(
                    InlineKeyboardButton(text="◀️", callback_data=f"fn_page:{page - 1}")
                )
            nav.append(
                InlineKeyboardButton(
                    text=f"{page + 1}/{total_pages}", callback_data="fn_noop"
                )
            )
            if page < total_pages - 1:
                nav.append(
                    InlineKeyboardButton(text="▶️", callback_data=f"fn_page:{page + 1}")
                )
            rows.append(nav)

        rows.append(
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="fn_cancel")]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def confirm_preview() -> InlineKeyboardMarkup:
        """Confirmation keyboard shown after the admin reviews the sample message."""
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Yuborish", callback_data="fn_confirm"
                    ),
                    InlineKeyboardButton(
                        text="❌ Bekor qilish", callback_data="fn_cancel"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="✏️ Matnni o'zgartirish", callback_data="fn_edit_text"
                    )
                ],
            ]
        )

    @staticmethod
    def stop_button(task_id: str) -> InlineKeyboardMarkup:
        """Single-button keyboard for stopping an active send."""
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⏸ To'xtatish",
                        callback_data=f"fn_stop_task:{task_id}",
                    )
                ]
            ]
        )
