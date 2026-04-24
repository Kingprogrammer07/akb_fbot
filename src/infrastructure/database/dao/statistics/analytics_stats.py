from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class AnalyticsStatsDAO:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_events_page(
        self,
        event_type: Optional[str],
        start_date: Optional[date],
        end_date: Optional[date],
        page: int,
        page_size: int,
    ) -> tuple[list[dict], int]:
        """Return paginated analytics events and total count."""
        conditions = ["1=1"]
        params: dict = {}

        if event_type:
            conditions.append("event_type = :event_type")
            params["event_type"] = event_type
        if start_date:
            conditions.append("created_at >= :start_date")
            params["start_date"] = datetime.combine(start_date, datetime.min.time())
        if end_date:
            conditions.append("created_at < :end_date")
            params["end_date"] = datetime.combine(end_date, datetime.max.time())

        where = " AND ".join(conditions)
        offset = (page - 1) * page_size

        count_result = await self.session.execute(
            text(f"SELECT COUNT(id) FROM analytics_events WHERE {where}"),
            params,
        )
        total = count_result.scalar() or 0

        params["limit"] = page_size
        params["offset"] = offset
        rows_result = await self.session.execute(
            text(
                f"SELECT id, event_type, user_id, event_data, created_at "
                f"FROM analytics_events WHERE {where} "
                f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        items = [dict(r._mapping) for r in rows_result.fetchall()]
        return items, total

    async def get_summary(
        self,
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> list[dict]:
        """Return per-event-type totals: total_count, unique_users, last_occurrence."""
        conditions = ["1=1"]
        params: dict = {}

        if start_date:
            conditions.append("created_at >= :start_date")
            params["start_date"] = datetime.combine(start_date, datetime.min.time())
        if end_date:
            conditions.append("created_at < :end_date")
            params["end_date"] = datetime.combine(end_date, datetime.max.time())

        where = " AND ".join(conditions)
        result = await self.session.execute(
            text(
                f"SELECT event_type, COUNT(id) AS total_count, "
                f"COUNT(DISTINCT user_id) AS unique_users, MAX(created_at) AS last_occurrence "
                f"FROM analytics_events WHERE {where} "
                f"GROUP BY event_type ORDER BY total_count DESC"
            ),
            params,
        )
        return [dict(r._mapping) for r in result.fetchall()]

    async def get_daily_trends(
        self,
        event_type: Optional[str],
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> list[dict]:
        """Return daily event counts grouped by date."""
        conditions = ["1=1"]
        params: dict = {}

        if event_type:
            conditions.append("event_type = :event_type")
            params["event_type"] = event_type
        if start_date:
            conditions.append("created_at >= :start_date")
            params["start_date"] = datetime.combine(start_date, datetime.min.time())
        if end_date:
            conditions.append("created_at < :end_date")
            params["end_date"] = datetime.combine(end_date, datetime.max.time())

        where = " AND ".join(conditions)
        result = await self.session.execute(
            text(
                f"SELECT TO_CHAR(created_at AT TIME ZONE 'Asia/Tashkent', 'YYYY-MM-DD') AS date, "
                f"COUNT(id) AS count "
                f"FROM analytics_events WHERE {where} "
                f"GROUP BY TO_CHAR(created_at AT TIME ZONE 'Asia/Tashkent', 'YYYY-MM-DD') "
                f"ORDER BY date ASC"
            ),
            params,
        )
        return [dict(r._mapping) for r in result.fetchall()]
