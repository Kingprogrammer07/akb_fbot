"""
Shared pytest configuration.

``src/__init__.py`` imports ``src.config``, which instantiates every settings
class at module import time.  The repository intentionally ships no ``.env``,
so the required environment variables are injected here *before* any ``src.*``
module is imported — otherwise collection fails with validation errors that
have nothing to do with the code under test.
"""
import os

_TEST_ENV: dict[str, str] = {
    "BOT_TOKEN": "123456:test-token-not-a-real-secret",
    "BOT_ADMIN_ACCESS_IDs": "[1]",
    "BOT_TASDIQLASH_GROUP_ID": "-1001",
    "BOT_TASDIQLANGANLAR_CHANNEL_ID": "-1002",
    "BOT_FOTO_HISOBOT_SUCCESS_CHANNEL_ID": "-1003",
    "BOT_FOTO_HISOBOT_FAIL_CHANNEL_ID": "-1004",
    "POSTGRES_USER": "test_user",
    "POSTGRES_PASSWORD": "test_password",
    "POSTGRES_DB": "test_db",
    "GOOGLE_SHEETS_SHEETS_ID": "test-sheets-id-0123456789",
    "GOOGLE_SHEETS_API_KEY": "test-sheets-api-key-0123456789",
    "AWS_ACCESS_KEY_ID": "test-access-key",
    "AWS_SECRET_ACCESS_KEY": "test-secret-access-key",
    "AWS_BUCKET_NAME": "test-bucket",
    # 64 chars — must satisfy the production strength rules for the admin JWT.
    "API_JWT_SECRET": "t" * 64,
}

for _key, _value in _TEST_ENV.items():
    os.environ.setdefault(_key, _value)

import sys
from pathlib import Path

# The worktree root is not on sys.path when pytest is invoked from elsewhere.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
