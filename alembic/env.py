import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ================================
# App config (NO SHADOWING!)
# ================================
from src import config as app_config
from src.infrastructure.database.models.base import Base
from src.infrastructure.database.models import Client  # noqa: F401
from src.infrastructure.database.models.flight_cargo import FlightCargo  # noqa: F401
from src.infrastructure.database.models.client_transaction import ClientTransaction  # noqa: F401
from src.infrastructure.database.models.client_payment_event import ClientPaymentEvent  # noqa: F401
from src.infrastructure.database.models.user_payment_card import UserPaymentCard  # noqa: F401
from src.infrastructure.database.models.carousel_item import CarouselItem  # noqa: F401
from src.infrastructure.database.models.carousel_stat import CarouselStat  # noqa: F401
from src.infrastructure.database.models.notification import Notification  # noqa: F401
from src.infrastructure.database.models.delivery_request import DeliveryRequest  # noqa: F401
# Admin RBAC models — imported so Alembic autogenerate detects all 6 new tables
from src.infrastructure.database.models.role import Role, Permission, role_permissions  # noqa: F401
from src.infrastructure.database.models.admin_account import AdminAccount  # noqa: F401
from src.infrastructure.database.models.admin_passkey import AdminPasskey  # noqa: F401
from src.infrastructure.database.models.admin_audit_log import AdminAuditLog  # noqa: F401


# ================================
# Database URL
# ================================
DATABASE_URL: str = app_config.database.database_url

# Alembic % escape fix
DB_URL_ESCAPED = DATABASE_URL.replace("%", "%%")


# ================================
# Alembic config
# ================================
alembic_config = context.config
alembic_config.set_main_option("sqlalchemy.url", DB_URL_ESCAPED)


# ================================
# Logging
# ================================
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)


# ================================
# Metadata
# ================================
target_metadata = Base.metadata


# ================================
# Offline migrations
# ================================
def run_migrations_offline() -> None:
    """Run migrations in offline mode."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# ================================
# Online migrations helpers
# ================================
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


# ================================
# Entrypoint
# ================================
def run_migrations_online() -> None:
    print("ALEMBIC DATABASE URL =", DATABASE_URL)
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
