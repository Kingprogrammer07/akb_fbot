import asyncio
import os
import sys
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Ensure we can import src by adding the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import config
from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.role import Role
from src.infrastructure.database.models.admin_account import AdminAccount
from src.infrastructure.tools.datetime_utils import get_current_time
from src.api.utils.security import hash_pin

async def main():
    print("=" * 50)
    print("      Admin Auth & RBAC Seeder Script      ")
    print("=" * 50)
    print("This script will create the core 'super-admin' role")
    print("and link it to an existing Client via Telegram ID.\n")

    telegram_id_str = input("Enter the Telegram ID of the existing Client: ").strip()
    if not telegram_id_str.isdigit():
        print("❌ Error: Telegram ID must be a number.")
        return
    telegram_id = int(telegram_id_str)

    system_username = input("Enter the new system_username for this admin: ").strip()
    if len(system_username) < 3:
        print("❌ Error: Username must be at least 3 characters.")
        return

    pin = input("Enter a secure 4+ digit PIN: ").strip()
    if len(pin) < 4:
        print("❌ Error: PIN must be at least 4 digits.")
        return

    print("\nConnecting to database...")
    
    # Setup Async Engine and Session
    engine = create_async_engine(config.database.database_url, echo=False)
    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_maker() as session:
        # 1. Check if Client exists
        doc = await session.execute(select(Client).where(Client.telegram_id == telegram_id))
        client = doc.scalar_one_or_none()
        
        if not client:
            print(f"❌ Error: No Client found with Telegram ID {telegram_id}. Please start the bot first to register.")
            await engine.dispose()
            return

        # 2. Setup super-admin Role
        doc = await session.execute(select(Role).where(Role.name == "super-admin"))
        super_admin_role = doc.scalar_one_or_none()
        
        if not super_admin_role:
            print("Creating 'super-admin' role...")
            super_admin_role = Role(
                name="super-admin",
                description="Built-in super administrator with full system access.",
                is_custom=False
            )
            session.add(super_admin_role)
            await session.flush()
        else:
            print("✅ 'super-admin' role already exists.")

        # 3. Check if AdminAccount exists for this client or username
        doc = await session.execute(
            select(AdminAccount).where(
                (AdminAccount.client_id == client.id) | 
                (AdminAccount.system_username == system_username)
            )
        )
        existing_account = doc.scalar_one_or_none()
        
        if existing_account:
            print("❌ Error: An AdminAccount already exists for this Client ID or Username.")
            print(f"Existing Account Username: {existing_account.system_username}")
            await engine.dispose()
            return

        # 4. Create AdminAccount
        print("Creating AdminAccount...")
        new_admin = AdminAccount(
            client_id=client.id,
            role_id=super_admin_role.id,
            system_username=system_username,
            pin_hash=hash_pin(pin),
            failed_login_attempts=0,
            is_active=True
        )
        session.add(new_admin)
        await session.commit()
        
        print("\n" + "=" * 50)
        print("✅ SUCCESS! Super-Admin account created.")
        print("=" * 50)
        print(f"Telegram ID: {telegram_id}")
        print(f"Username:    {system_username}")
        print(f"Role:        super-admin")
        print("=" * 50)
        print("You can now log into the Admin Panel using this PIN.")

    await engine.dispose()


if __name__ == "__main__":
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
