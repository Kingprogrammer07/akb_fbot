import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)


class DatabaseClient:
    """Manages database connection and sessions."""

    def __init__(self, database_url: str):
        self.engine = create_async_engine(
            url=database_url,
            echo=False,  # Disable SQL query logging for production
            pool_size=30,  # Max 30 active connections
            max_overflow=50,  # Allow up to 10 extra connections during peak load
            pool_timeout=30,  # Wait 30 seconds for a free connection
            pool_pre_ping=True,  # Check connection health before use
            pool_recycle=3600,  # Recycle connections every hour to avoid stale connections
        )
        self.session_factory = async_sessionmaker(bind=self.engine, expire_on_commit=False)

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Provide a database session.

        Uses try...except...finally to guarantee session cleanup:
        - On success: session is closed in finally
        - On exception: rollback then close in finally
        - On generator exit (GeneratorExit): close in finally

        This prevents connection leaks that cause AsyncAdaptedQueuePool warnings.
        """
        session = self.session_factory()
        try:
            yield session
        except GeneratorExit:
            # Generator was closed before completion (e.g., early return, break)
            # Do not rollback - just let finally handle close
            pass
        except Exception:
            # Application error - rollback changes
            await session.rollback()
            raise
        finally:
            # CRITICAL: Always close session to return connection to pool
            await session.close()

    async def shutdown(self):
        """Dispose the database engine."""
        await self.engine.dispose()
        logger.info(f'Database engine disposed for {self.engine.url}')

    async def __aenter__(self) -> "DatabaseClient":
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager, ensuring cleanup."""
        await self.shutdown()
