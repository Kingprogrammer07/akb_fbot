"""
Shared pytest configuration.

``src/__init__.py`` imports ``src.config``, which instantiates every settings
class at module import time.  The repository intentionally ships no ``.env``,
so the required environment variables are injected here *before* any ``src.*``
module is imported — otherwise collection fails with validation errors that
have nothing to do with the code under test.

Database tests
--------------
Tests that need PostgreSQL request the ``db_engine`` or ``db_session``
fixture.  They are skipped unless ``AKB_TEST_DB=1`` is set, and they refuse to
run against anything other than a local database whose name starts with
``akb_t``: the fixture drops and recreates the whole ``public`` schema.

    AKB_TEST_DB=1 POSTGRES_HOST=localhost POSTGRES_PORT=55433 \
    POSTGRES_USER=akb_test POSTGRES_PASSWORD=... POSTGRES_DB=akb_t_local pytest
"""
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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

# The worktree root is not on sys.path when pytest is invoked from elsewhere.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_TEST_DB_PREFIX = "akb_t"


def _test_database_url() -> str:
    """Return the database URL for destructive tests, or skip / fail safely."""
    if os.environ.get("AKB_TEST_DB") != "1":
        pytest.skip("database tests are disabled; set AKB_TEST_DB=1 to run them")

    from src.config import config

    database = config.database
    if database.HOST not in _LOCAL_HOSTS or not database.DB.startswith(_TEST_DB_PREFIX):
        pytest.fail(
            "refusing to run destructive database tests against "
            f"{database.HOST!r}/{database.DB!r}: only a local database whose "
            f"name starts with {_TEST_DB_PREFIX!r} is allowed"
        )
    return database.database_url


@pytest_asyncio.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Engine bound to a freshly recreated schema built from the ORM models."""
    url = _test_database_url()

    import src.infrastructure.database.models  # noqa: F401  (registers every table)
    from src.infrastructure.database.models.base import Base
    from src.infrastructure.services.partner_resolver import get_resolver

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)

    # The resolver is a process-wide cache; a previous test's partners must not
    # leak into this schema.
    get_resolver()._loaded = False

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session on the fresh schema; ``expire_on_commit=False`` like production."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        yield session
