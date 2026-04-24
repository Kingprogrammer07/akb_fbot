"""Analytics Service for event tracking."""
import logging
import asyncio
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.analytics_event import AnalyticsEventDAO

logger = logging.getLogger(__name__)


class AnalyticsService:
    """
    Service for emitting analytics events.
    
    Provides non-blocking, safe event emission that will never crash the main flow.
    Events are logged on errors but failures are silently handled.
    """
    
    @staticmethod
    async def emit_event(
        session: AsyncSession,
        event_type: str,
        user_id: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Emit an analytics event (non-blocking, safe).
        
        This method will never raise exceptions - all errors are caught and logged.
        Events are written synchronously within the current session context.
        
        Args:
            session: Database session (will commit event if successful)
            event_type: Type of event (e.g., 'client_registration', 'cargo_upload')
            user_id: Optional Telegram ID of user who triggered the event
            payload: Optional dictionary with event-specific data
            
        Note:
            Event is written immediately but errors are caught and logged.
            Main flow continues even if event emission fails.
        """
        try:
            await AnalyticsEventDAO.create(
                session=session,
                event_type=event_type,
                user_id=user_id,
                event_data=payload
            )
            # Note: We don't commit here - caller should commit their transaction
            # This allows event to be part of the same transaction or rolled back if needed
            logger.debug(f"Analytics event emitted: {event_type} (user_id={user_id})")
        except Exception as e:
            # Silent failure - analytics must never break main flow
            logger.warning(
                f"Failed to emit analytics event {event_type} (user_id={user_id}): {e}",
                exc_info=True
            )
            # Don't re-raise - continue execution
    
    @staticmethod
    async def emit_event_async(
        session_factory,
        event_type: str,
        user_id: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Emit an analytics event in a separate async task (fire-and-forget).
        
        This creates a new session and writes the event in background.
        Use this when you want truly non-blocking writes that don't affect
        the current transaction.
        
        Args:
            session_factory: Async generator function that yields a session
            event_type: Type of event
            user_id: Optional Telegram ID of user
            payload: Optional dictionary with event-specific data
            
        Note:
            This method creates a background task that runs independently.
            Failures are logged but never propagated to caller.
        """
        async def _emit_in_background():
            try:
                async for session in session_factory():
                    try:
                        await AnalyticsEventDAO.create(
                            session=session,
                            event_type=event_type,
                            user_id=user_id,
                            event_data=payload
                        )
                        await session.commit()
                        logger.debug(f"Analytics event emitted (async): {event_type} (user_id={user_id})")
                    except Exception as e:
                        await session.rollback()
                        logger.warning(
                            f"Failed to emit analytics event (async) {event_type} (user_id={user_id}): {e}",
                            exc_info=True
                        )
                    finally:
                        await session.close()
            except Exception as e:
                logger.warning(
                    f"Failed to get session for analytics event (async) {event_type}: {e}",
                    exc_info=True
                )
        # Fire and forget - create task but don't wait for it
        try:
            asyncio.create_task(_emit_in_background())
        except Exception as e:
            logger.warning(f"Failed to create task for analytics event {event_type}: {e}")

