"""
Payment Notification Formatter

Formats payment notifications for channels with breakdown by provider.
Ensures consistent formatting and timezone handling.
"""
from datetime import datetime

from src.infrastructure.tools.datetime_utils import to_tashkent


async def format_account_payment_notification(
    client_code: str,
    transaction_id: int,
    flight_name: str,
    breakdown: dict[str, float],
    admin_name: str,
    timestamp: datetime,
    _: callable
) -> str:
    """
    Format account payment notification with breakdown.

    Args:
        client_code: Client code (e.g., "SS123")
        transaction_id: Transaction ID
        flight_name: Flight/reys name
        breakdown: Payment breakdown {'cash': 100.0, 'click': 50.0, 'payme': 0.0}
        admin_name: Admin name (preferably with @username)
        timestamp: Payment timestamp (UTC)
        _: i18n translation function

    Returns:
        Formatted message string with HTML markup

    Example:
        ```
        ✅ HISOBGA TO'LOV TASDIQLANDI

        👤 Client: SS123
        🆔 Transaction ID: 456
        ✈️ Reys: TK-2025-01-15

        💰 To'lov tarkibi:
           💳 Click: 50,000 so'm
           💳 Payme: 0 so'm
           💵 Naqd: 100,000 so'm
           ━━━━━━━━━━━━━━━━━
           📊 Jami: 150,000 so'm

        👨‍💼 Admin: @username
        🕒 Vaqt: 2026-01-15 18:30:45
        ```
    """
    # Convert timestamp to Tashkent timezone
    tashkent_time = to_tashkent(timestamp)
    formatted_time = tashkent_time.strftime("%Y-%m-%d %H:%M:%S")

    # Format amounts with thousand separators
    click_amount = breakdown.get('click', 0.0)
    payme_amount = breakdown.get('payme', 0.0)
    cash_amount = breakdown.get('cash', 0.0)
    total_amount = click_amount + payme_amount + cash_amount

    # Build breakdown section
    breakdown_lines = []
    breakdown_lines.append("💰 <b>To'lov tarkibi:</b>")
    breakdown_lines.append(f"   💳 Click: <code>{click_amount:,.0f} so'm</code>")
    breakdown_lines.append(f"   💳 Payme: <code>{payme_amount:,.0f} so'm</code>")
    breakdown_lines.append(f"   💵 Naqd: <code>{cash_amount:,.0f} so'm</code>")
    breakdown_lines.append("   ━━━━━━━━━━━━━━━━━")
    breakdown_lines.append(f"   📊 <b>Jami: {total_amount:,.0f} so'm</b>")

    breakdown_text = "\n".join(breakdown_lines)

    # Build full message
    message = f"""✅ <b>HISOBGA TO'LOV TASDIQLANDI</b>

👤 Client: <code>{client_code}</code>
🆔 Transaction ID: <code>{transaction_id}</code>
✈️ Reys: <b>{flight_name}</b>

{breakdown_text}

👨‍💼 Admin: {admin_name}
🕒 Vaqt: {formatted_time}"""

    return message


async def format_cash_payment_notification(
    client_code: str,
    transaction_id: int,
    flight_name: str,
    amount: float,
    admin_name: str,
    timestamp: datetime,
    _: callable
) -> str:
    """
    Format cash payment notification.

    Args:
        client_code: Client code
        transaction_id: Transaction ID
        flight_name: Flight/reys name
        amount: Payment amount
        admin_name: Admin name
        timestamp: Payment timestamp (UTC)
        _: i18n translation function

    Returns:
        Formatted message string
    """
    tashkent_time = to_tashkent(timestamp)
    formatted_time = tashkent_time.strftime("%Y-%m-%d %H:%M:%S")

    message = f"""💵 <b>NAQD TO'LOV TASDIQLANDI</b>

👤 Client: <code>{client_code}</code>
🆔 Transaction ID: <code>{transaction_id}</code>
✈️ Reys: <b>{flight_name}</b>
💰 Summa: <b>{amount:,.0f} so'm</b>

👨‍💼 Admin: {admin_name}
🕒 Vaqt: {formatted_time}"""

    return message


def format_payment_breakdown_inline(breakdown: dict[str, float]) -> str:
    """
    Format payment breakdown as inline text.

    Args:
        breakdown: {'cash': 100.0, 'click': 50.0, 'payme': 0.0}

    Returns:
        Inline string like "Click: 50k | Cash: 100k"
    """
    parts = []
    if breakdown.get('click', 0) > 0:
        parts.append(f"Click: {breakdown['click']/1000:.0f}k")
    if breakdown.get('payme', 0) > 0:
        parts.append(f"Payme: {breakdown['payme']/1000:.0f}k")
    if breakdown.get('cash', 0) > 0:
        parts.append(f"Naqd: {breakdown['cash']/1000:.0f}k")

    return " | ".join(parts) if parts else "0"


def get_payment_type_display(breakdown: dict[str, float]) -> str:
    """
    Get payment type display name based on breakdown.

    Args:
        breakdown: Payment breakdown

    Returns:
        "Cash", "Click", "Payme", "Mixed", or "None"
    """
    active_providers = [
        provider for provider, amount in breakdown.items()
        if amount > 0
    ]

    if len(active_providers) == 0:
        return "None"
    elif len(active_providers) == 1:
        provider = active_providers[0]
        return provider.capitalize()
    else:
        return "Mixed"
