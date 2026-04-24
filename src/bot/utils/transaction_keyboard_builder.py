"""
Transaction Action Keyboard Builder

Centralized logic for building transaction action keyboards.
Ensures consistent button visibility across all handlers.

CRITICAL: All handlers MUST use this builder. No inline button logic allowed.
"""
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

from src.infrastructure.database.models.client_transaction import ClientTransaction


def build_transaction_action_keyboard(
    transaction: ClientTransaction,
    client_code: str | None,
    _: callable
) -> InlineKeyboardMarkup | None:
    """
    Build inline keyboard for transaction actions.

    This is the SINGLE SOURCE OF TRUTH for button visibility logic.

    Button Visibility Rules (based on DATABASE state):
    ═══════════════════════════════════════════════════════

    Rule 1: If is_taken_away == True
        → NO ACTION BUTTONS

    Rule 2: If payment_status == "paid" AND NOT taken
        → ONLY "Mark as Taken" button

    Rule 3: If payment_status in ("pending", "partial") AND NOT taken
        → "Cash Remainder" button
        → "Account Payment" button

    Rule 4: Cargo photos button
        → Always visible if client_code exists
        → Independent of payment status

    Args:
        transaction: ClientTransaction model instance
        client_code: Client code for cargo lookup (optional)
        _: i18n translation function

    Returns:
        InlineKeyboardMarkup if buttons exist, None otherwise

    Examples:
        >>> # Transaction fully paid, not taken
        >>> keyboard = build_transaction_action_keyboard(tx, "SS123", _)
        >>> # Result: ["Olib ketildi", "Show cargo"]

        >>> # Transaction partial paid, not taken
        >>> keyboard = build_transaction_action_keyboard(tx, "SS123", _)
        >>> # Result: ["Cash remainder", "Account payment", "Show cargo"]

        >>> # Transaction taken
        >>> keyboard = build_transaction_action_keyboard(tx, "SS123", _)
        >>> # Result: ["Show cargo"] (if client_code exists)
    """
    builder = InlineKeyboardBuilder()
    has_buttons = False

    # ═══════════════════════════════════════════════════════
    # RULE 1: Already taken → NO action buttons
    # ═══════════════════════════════════════════════════════
    if transaction.is_taken_away:
        # No payment/taken action buttons
        # Only cargo button (below) if applicable
        pass

    # ═══════════════════════════════════════════════════════
    # RULE 2: Fully paid, not taken → ONLY "Mark as Taken"
    # ═══════════════════════════════════════════════════════
    elif transaction.payment_status == "paid":
        builder.button(
            text=_("btn-mark-as-taken"),
            callback_data=f"v:mt:{transaction.id}"
        )
        has_buttons = True

    # ═══════════════════════════════════════════════════════
    # RULE 3: Pending or partial → Show payment options
    # ═══════════════════════════════════════════════════════
    else:
        # Cash remainder payment button
        builder.button(
            text=_("btn-cash-remainder"),
            callback_data=f"v:cp:{transaction.id}"
        )
        has_buttons = True

        # Account payment button (Click/Payme)
        builder.button(
            text=_("btn-account-payment"),
            callback_data=f"v:ap:{transaction.id}"
        )
        has_buttons = True

    # ═══════════════════════════════════════════════════════
    # RULE 4: Cargo photos button (independent of payment state)
    # ═══════════════════════════════════════════════════════
    if client_code:
        builder.button(
            text=_("btn-verification-show-cargos"),
            callback_data=f"v:cgo:{transaction.id}"
        )
        has_buttons = True

    # Arrange buttons vertically (one per row)
    builder.adjust(1)

    # Return keyboard only if buttons exist
    return builder.as_markup() if has_buttons else None


def get_button_explanation(transaction: ClientTransaction) -> str:
    """
    Get human-readable explanation of why certain buttons are visible.

    Useful for debugging and admin training.

    Args:
        transaction: ClientTransaction instance

    Returns:
        String explaining button logic

    Example:
        >>> explain = get_button_explanation(transaction)
        >>> print(explain)
        "Payment fully paid but not taken → Only 'Mark as Taken' button visible"
    """
    if transaction.is_taken_away:
        return "Transaction already taken → No action buttons visible (only cargo if exists)"

    elif transaction.payment_status == "paid":
        return "Payment fully paid but not taken → Only 'Mark as Taken' button visible"

    elif transaction.payment_status == "partial":
        remaining = transaction.remaining_amount or 0.0
        return f"Payment partial (remaining {remaining:.2f}) → Payment buttons visible"

    elif transaction.payment_status == "pending":
        return "Payment pending → Payment buttons visible"

    else:
        return f"Unknown status '{transaction.payment_status}' → No buttons"
