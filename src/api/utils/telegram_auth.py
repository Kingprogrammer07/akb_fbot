"""Telegram Web App authentication utilities."""
import hashlib
import hmac
from urllib.parse import parse_qsl


def validate_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    """
    Validate Telegram Web App initData using HMAC SHA256.

    Args:
        init_data: The initData string from Telegram Web App
        bot_token: Your bot token

    Returns:
        Parsed user data if valid, None otherwise
    """
    try:
        # Parse the init_data
        parsed_data = dict(parse_qsl(init_data))

        # Extract hash
        received_hash = parsed_data.pop('hash', None)
        if not received_hash:
            return None

        # Validate auth_date (prevent replay attacks)
        import time
        auth_date = int(parsed_data.get('auth_date', 0))
        current_time = int(time.time())
        
        # Check if data is older than 1 day (86400 seconds)
        if current_time - auth_date > 1800:  # 30 minutes
            return None

        # Create data check string (alphabetically sorted key=value pairs)
        data_check_string = '\n'.join(
            f"{key}={value}"
            for key, value in sorted(parsed_data.items())
        )

        # Create secret key
        secret_key = hmac.new(
            key=b"WebAppData",
            msg=bot_token.encode(),
            digestmod=hashlib.sha256
        ).digest()

        # Calculate hash
        calculated_hash = hmac.new(
            key=secret_key,
            msg=data_check_string.encode(),
            digestmod=hashlib.sha256
        ).hexdigest()

        # Verify hash
        if calculated_hash != received_hash:
            return None

        # Parse user data if present
        import json
        if 'user' in parsed_data:
            user_data = json.loads(parsed_data['user'])
            return user_data

        return parsed_data

    except Exception:
        return None
