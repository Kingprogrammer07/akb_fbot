from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class CargoStatsDAO:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_volume_stats(
        self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> dict:
        """
        Calculates main cargo volume stats:
        - total_cargos
        - total_weight_kg
        - avg_weight_per_client
        - avg_weight_per_track
        """
        query = """
            SELECT
                COUNT(id) as total_cargos,
                COALESCE(SUM(weight_kg), 0) as total_weight_kg,
                COUNT(DISTINCT client_id) as distinct_clients
            FROM flight_cargos
            WHERE 1=1
        """
        params = {}
        if start_date:
            query += " AND created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            query += " AND created_at <= :end_date"
            params["end_date"] = end_date

        result = await self.session.execute(text(query), params)
        row = result.mappings().first()

        total_cargos = row["total_cargos"] if row else 0
        total_weight_kg = row["total_weight_kg"] if row else 0
        distinct_clients = row["distinct_clients"] if row else 0

        avg_weight_per_client = (
            total_weight_kg / distinct_clients if distinct_clients > 0 else 0
        )
        avg_weight_per_track = total_weight_kg / total_cargos if total_cargos > 0 else 0

        return {
            "total_cargos": total_cargos,
            "total_weight_kg": total_weight_kg,
            "avg_weight_per_client": avg_weight_per_client,
            "avg_weight_per_track": avg_weight_per_track,
        }

    async def get_bottleneck_stats(
        self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> dict:
        """
        Calculates bottlenecks and statuses:
        - china_unaccounted
        - uz_pending_payment
        - uz_paid_not_taken
        - uz_taken_away
        - post_approved
        """
        # 1. china_unaccounted
        query_unaccounted = """
            SELECT COUNT(c.id) as cnt
            FROM cargo_items c
            LEFT JOIN flight_cargos f ON c.client_id = f.client_id AND c.flight_name = f.flight_name
            WHERE f.id IS NULL
        """
        params = {}
        if start_date:
            query_unaccounted += " AND c.created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            query_unaccounted += " AND c.created_at <= :end_date"
            params["end_date"] = end_date

        res_unaccounted = await self.session.execute(text(query_unaccounted), params)
        china_unaccounted = res_unaccounted.scalar() or 0

        # 2. uz_pending_payment
        query_pending = """
            SELECT COUNT(f.id) as cnt
            FROM flight_cargos f
            LEFT JOIN client_transaction_data t ON f.client_id = t.client_code AND f.flight_name = t.reys
            WHERE f.is_sent = true AND t.id IS NULL
        """
        params_pending = {}
        if start_date:
            query_pending += " AND f.created_at >= :start_date"
            params_pending["start_date"] = start_date
        if end_date:
            query_pending += " AND f.created_at <= :end_date"
            params_pending["end_date"] = end_date

        res_pending = await self.session.execute(text(query_pending), params_pending)
        uz_pending_payment = res_pending.scalar() or 0

        # 3. uz_paid_not_taken
        query_not_taken = """
            SELECT COUNT(id) as cnt
            FROM client_transaction_data
            WHERE is_taken_away = false
        """
        params_trans = {}
        if start_date:
            query_not_taken += " AND created_at >= :start_date"
            params_trans["start_date"] = start_date
        if end_date:
            query_not_taken += " AND created_at <= :end_date"
            params_trans["end_date"] = end_date

        res_not_taken = await self.session.execute(text(query_not_taken), params_trans)
        uz_paid_not_taken = res_not_taken.scalar() or 0

        # 4. uz_taken_away
        query_taken = """
            SELECT COUNT(id) as cnt
            FROM client_transaction_data
            WHERE is_taken_away = true
        """
        if start_date:
            query_taken += " AND created_at >= :start_date"
        if end_date:
            query_taken += " AND created_at <= :end_date"

        res_taken = await self.session.execute(text(query_taken), params_trans)
        uz_taken_away = res_taken.scalar() or 0

        # 5. post_approved
        query_post = """
            SELECT COUNT(id) as cnt
            FROM delivery_requests
            WHERE status = 'approved'
        """
        params_post = {}
        if start_date:
            query_post += " AND created_at >= :start_date"
            params_post["start_date"] = start_date
        if end_date:
            query_post += " AND created_at <= :end_date"
            params_post["end_date"] = end_date

        res_post = await self.session.execute(text(query_post), params_post)
        post_approved = res_post.scalar() or 0

        return {
            "china_unaccounted": china_unaccounted,
            "uz_pending_payment": uz_pending_payment,
            "uz_paid_not_taken": uz_paid_not_taken,
            "uz_taken_away": uz_taken_away,
            "post_approved": post_approved,
        }

    async def get_speed_stats(
        self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> dict:
        """
        Calculates average turnaround times in days.
        """
        params = {}
        date_filter = ""
        if start_date:
            date_filter += " AND f.created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            date_filter += " AND f.created_at <= :end_date"
            params["end_date"] = end_date

        query_china = f"""
            SELECT AVG(EXTRACT(EPOCH FROM (f.created_at - c.created_at))/86400.0) as avg_days
            FROM flight_cargos f
            JOIN cargo_items c ON f.client_id = c.client_id AND f.flight_name = c.flight_name
            WHERE c.created_at < f.created_at {date_filter}
        """
        res_china = await self.session.execute(text(query_china), params)
        china_to_uz_days = res_china.scalar() or 0

        query_uz = f"""
            SELECT AVG(EXTRACT(EPOCH FROM (t.taken_away_date - f.created_at))/86400.0) as avg_days
            FROM client_transaction_data t
            JOIN flight_cargos f ON t.client_code = f.client_id AND t.reys = f.flight_name
            WHERE t.is_taken_away = true AND t.taken_away_date IS NOT NULL 
              AND f.created_at < t.taken_away_date {date_filter}
        """
        res_uz = await self.session.execute(text(query_uz), params)
        uz_warehouse_days = res_uz.scalar() or 0

        full_cycle_days = china_to_uz_days + uz_warehouse_days

        return {
            "china_to_uz_days": float(china_to_uz_days),
            "uz_warehouse_days": float(uz_warehouse_days),
            "full_cycle_days": float(full_cycle_days),
        }

    async def get_top_flights(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Returns top flights by cargo volume."""
        query = """
            SELECT 
                flight_name, 
                COUNT(id) as cargo_count, 
                COALESCE(SUM(weight_kg), 0) as total_weight_kg
            FROM flight_cargos
            WHERE 1=1
        """
        params = {"limit": limit}
        if start_date:
            query += " AND created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            query += " AND created_at <= :end_date"
            params["end_date"] = end_date

        query += " GROUP BY flight_name ORDER BY cargo_count DESC LIMIT :limit"

        result = await self.session.execute(text(query), params)
        return [dict(row) for row in result.mappings()]

    async def get_period_trends(
        self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> list[dict]:
        """Returns daily track-code search counts from analytics_events."""
        query = """
            SELECT
                TO_CHAR(created_at AT TIME ZONE 'Asia/Tashkent', 'YYYY-MM-DD') AS period_name,
                COUNT(*) AS search_count
            FROM analytics_events
            WHERE event_type = 'track_code_search'
        """
        params = {}
        if start_date:
            query += " AND created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            query += " AND created_at <= :end_date"
            params["end_date"] = end_date

        query += (
            " GROUP BY TO_CHAR(created_at AT TIME ZONE 'Asia/Tashkent', 'YYYY-MM-DD')"
            " ORDER BY period_name ASC"
        )

        result = await self.session.execute(text(query), params)
        return [dict(row) for row in result.mappings().all()]
