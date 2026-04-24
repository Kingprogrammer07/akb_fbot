"""Flight Schedule API router.

Read endpoint (GET) is accessible to any authenticated user (Bearer or Telegram
initData) so the mobile app can display the flight calendar without admin credentials.

Write endpoints (POST / PUT / DELETE) require an Admin JWT with the
``flight_schedule:manage`` permission and are additionally gated by a
per-IP route-level rate limit stricter than the global middleware.
"""
import logging
from collections.abc import AsyncGenerator, Callable
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import AdminJWTPayload, require_permission
from src.api.schemas.flight_schedule import (
    CreateFlightScheduleRequest,
    DeleteFlightScheduleResponse,
    FlightScheduleItem,
    FlightScheduleListResponse,
    UpdateFlightScheduleRequest,
)
from src.infrastructure.database.dao.flight_schedule import FlightScheduleDAO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/flight-schedule", tags=["Flight Schedule"])

_RequireManage = Depends(require_permission("flight_schedule", "manage"))


# ---------------------------------------------------------------------------
# Shared dependencies
# ---------------------------------------------------------------------------


async def _get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with request.app.state.db_client.session_factory() as session:
        yield session


def _write_rate_limit(max_requests: int = 20, window_seconds: int = 60) -> Callable:
    """
    Route-level rate limit dependency for write operations.

    Applies a per-IP limit that is stricter than the global middleware (which
    allows 100 req/min for all routes).  Raises 429 with a Retry-After header
    when the caller exceeds the threshold.

    Args:
        max_requests:   Maximum allowed requests within the window.
        window_seconds: Rolling window length in seconds.
    """
    async def _check(request: Request) -> None:
        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            return

        client_ip = request.client.host if request.client else "unknown"
        key = f"rl:flight_schedule:{request.method}:{client_ip}"

        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window_seconds)
            if count > max_requests:
                ttl = await redis.ttl(key)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "detail": "Too many write requests. Please slow down.",
                        "retry_after_seconds": max(ttl, 1),
                    },
                    headers={"Retry-After": str(max(ttl, 1))},
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("flight_schedule rate-limit Redis error (allowing): %s", exc)

    return _check


_WriteRateLimit = Depends(_write_rate_limit())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=FlightScheduleListResponse)
async def list_schedule(
    year: int | None = Query(
        None,
        ge=2020,
        le=2100,
        description="Four-digit calendar year (defaults to the current year)",
    ),
    session: AsyncSession = Depends(_get_session),
) -> FlightScheduleListResponse:
    """
    Return all flight schedule entries for a given year, ordered by date ascending.

    Accessible to any authenticated user (no admin role required).

    Args:
        year: Four-digit calendar year (defaults to the current year).
    """
    resolved_year = year if year is not None else date.today().year
    entries = await FlightScheduleDAO.get_by_year(session, resolved_year)
    return FlightScheduleListResponse(
        year=resolved_year,
        total=len(entries),
        items=[FlightScheduleItem.model_validate(e) for e in entries],
    )


@router.post(
    "",
    response_model=FlightScheduleItem,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WriteRateLimit],
)
async def create_schedule_entry(
    body: CreateFlightScheduleRequest,
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(_get_session),
) -> FlightScheduleItem:
    """
    Create a new flight schedule entry.

    Requires ``flight_schedule:manage`` permission.

    Args:
        body: Flight name, date, type, status, and optional notes.
    """
    entry = await FlightScheduleDAO.create(
        session,
        flight_name=body.flight_name,
        flight_date=body.flight_date,
        type_=body.type,
        status=body.status,
        notes=body.notes,
    )
    await session.commit()
    logger.info("flight_schedule created: id=%d by admin_id=%d", entry.id, admin.admin_id)
    return FlightScheduleItem.model_validate(entry)


@router.put(
    "/{schedule_id}",
    response_model=FlightScheduleItem,
    dependencies=[_WriteRateLimit],
)
async def update_schedule_entry(
    schedule_id: int,
    body: UpdateFlightScheduleRequest,
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(_get_session),
) -> FlightScheduleItem:
    """
    Partially update an existing flight schedule entry.

    Only fields present in the request body are written — untouched columns
    are left unchanged.  Requires ``flight_schedule:manage`` permission.

    Args:
        schedule_id: Primary key of the entry to update.
        body:        Sparse update payload (at least one field required).

    Raises:
        404: No entry with schedule_id exists.
    """
    entry = await FlightScheduleDAO.get_by_id(session, schedule_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule entry {schedule_id} not found.",
        )

    updated = await FlightScheduleDAO.update(
        session,
        entry=entry,
        flight_name=body.flight_name,
        flight_date=body.flight_date,
        type_=body.type,
        status=body.status,
        notes=body.notes,
    )
    await session.commit()
    logger.info(
        "flight_schedule updated: id=%d by admin_id=%d", schedule_id, admin.admin_id
    )
    return FlightScheduleItem.model_validate(updated)


@router.delete(
    "/{schedule_id}",
    response_model=DeleteFlightScheduleResponse,
    dependencies=[_WriteRateLimit],
)
async def delete_schedule_entry(
    schedule_id: int,
    admin: AdminJWTPayload = _RequireManage,
    session: AsyncSession = Depends(_get_session),
) -> DeleteFlightScheduleResponse:
    """
    Delete a flight schedule entry.

    Requires ``flight_schedule:manage`` permission.

    Args:
        schedule_id: Primary key of the entry to delete.

    Raises:
        404: No entry with schedule_id exists.
    """
    entry = await FlightScheduleDAO.get_by_id(session, schedule_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule entry {schedule_id} not found.",
        )

    await FlightScheduleDAO.delete(session, entry)
    await session.commit()
    logger.info(
        "flight_schedule deleted: id=%d by admin_id=%d", schedule_id, admin.admin_id
    )
    return DeleteFlightScheduleResponse(
        deleted_id=schedule_id,
        message=f"Schedule entry {schedule_id} deleted successfully.",
    )
