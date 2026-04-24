from datetime import datetime
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.utils.constants import AVIA_CODES, REGION_PREFIX_TO_NAME


class FinancialStatsDAO:
    @staticmethod
    async def get_financial_summary(
        session: AsyncSession,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        base_cost_usd: float = 8.0,
    ) -> dict[str, Any]:
        """
        Get aggregated financial summary using fast raw SQL.
        """
        where_clause = ""
        params = {}
        if start_date:
            where_clause += " AND created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            where_clause += " AND created_at <= :end_date"
            params["end_date"] = end_date

        sql = f"""
            WITH base_tx AS (
                SELECT 
                    id, client_code, reys, created_at,
                    COALESCE(total_amount, summa) as total_amount,
                    COALESCE(remaining_amount, 0) as remaining_amount,
                    CASE 
                        WHEN paid_amount IS NOT NULL THEN paid_amount
                        WHEN payment_status = 'paid' THEN summa
                        ELSE 0
                    END as paid_amount,
                    (CAST(NULLIF(regexp_replace(vazn, '[^0-9.]', '', 'g'), '') AS NUMERIC)) as weight_kg
                FROM client_transaction_data
                WHERE 1=1 {where_clause} AND reys NOT LIKE 'WALLET_ADJ%' AND reys NOT LIKE 'SYS_ADJ%'
            ),
            totals AS (
                SELECT
                    SUM(total_amount) as total_revenue,
                    SUM(paid_amount) as total_paid,
                    SUM(remaining_amount) as total_debt,
                    SUM(weight_kg) as total_kg,
                    SUM(CASE WHEN created_at < NOW() - INTERVAL '15 days' THEN remaining_amount ELSE 0 END) as overdue_debt
                FROM base_tx
            ),
            usd_rate_data AS (
                SELECT 
                    CASE 
                        WHEN use_custom_rate = TRUE THEN custom_usd_rate
                        ELSE 12500.0 -- Fallback default
                    END as usd_rate,
                    extra_charge as cogs_per_kg_usd -- Actually wait, profitability is 8$ per kg
                FROM static_data LIMIT 1
            ),
            payment_events AS (
                SELECT
                    COUNT(id) as total_payments,
                    AVG(amount) as avg_payment
                FROM client_payment_events
                WHERE 1=1 {where_clause}
            )
            SELECT 
                t.total_revenue,
                t.total_paid,
                t.total_debt,
                t.overdue_debt,
                t.total_kg,
                pe.avg_payment,
                u.usd_rate
            FROM totals t
            CROSS JOIN usd_rate_data u
            CROSS JOIN payment_events pe
        """

        result = await session.execute(text(sql), params)
        row = result.mappings().first()
        if not row:
            return {}

        revenue = float(row.get("total_revenue") or 0.0)
        paid = float(row.get("total_paid") or 0.0)
        debt = float(row.get("total_debt") or 0.0)
        overdue = float(row.get("overdue_debt") or 0.0)
        total_kg = float(row.get("total_kg") or 0.0)
        avg_payment = float(row.get("avg_payment") or 0.0)
        usd_rate = float(row.get("usd_rate") or 12500.0)

        # Profitability = Total Paid - (Total KG * base_cost_usd * conversion_rate)
        profitability = paid - (total_kg * base_cost_usd * usd_rate)

        return {
            "total_revenue": revenue,
            "total_paid": paid,
            "total_debt": debt,
            "overdue_debt": overdue,
            "average_payment": avg_payment,
            "total_profitability": profitability,
        }

    @staticmethod
    async def get_periodic_revenue(
        session: AsyncSession,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        where_clause = ""
        params = {}
        if start_date:
            where_clause += " AND created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            where_clause += " AND created_at <= :end_date"
            params["end_date"] = end_date

        sql = f"""
            SELECT 
                TO_CHAR(created_at, 'YYYY-MM') as period,
                SUM(COALESCE(total_amount, summa)) as revenue,
                SUM(CASE 
                    WHEN paid_amount IS NOT NULL THEN paid_amount
                    WHEN payment_status = 'paid' THEN summa
                    ELSE 0
                END) as paid,
                SUM(COALESCE(remaining_amount, 0)) as debt
            FROM client_transaction_data
            WHERE 1=1 {where_clause} AND reys NOT LIKE 'WALLET_ADJ%' AND reys NOT LIKE 'SYS_ADJ%'
            GROUP BY TO_CHAR(created_at, 'YYYY-MM')
            ORDER BY period
        """
        result = await session.execute(text(sql), params)
        return [dict(row) for row in result.mappings()]

    @staticmethod
    async def get_payment_methods(
        session: AsyncSession,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        where_clause = ""
        params = {}
        if start_date:
            where_clause += " AND created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            where_clause += " AND created_at <= :end_date"
            params["end_date"] = end_date

        sql = f"""
            SELECT
                payment_provider as method,
                SUM(amount) as total_amount,
                COUNT(id) as count
            FROM client_payment_events
            WHERE 1=1 {where_clause}
            GROUP BY payment_provider
            ORDER BY total_amount DESC
        """
        result = await session.execute(text(sql), params)
        return [dict(row) for row in result.mappings()]

    @staticmethod
    async def get_regions(
        session: AsyncSession,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        where_clause = ""
        params = {}
        if start_date:
            where_clause += " AND created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            where_clause += " AND created_at <= :end_date"
            params["end_date"] = end_date

        # Hududlar faqat 2-harfli prefiks bo'yicha guruhlanadi (ST, SV, SS, ...).
        # Filtr qoidalari:
        #   1. Kamida 4 ta harf bilan boshlanishi shart (STCH3, SVBK2...) —
        #      noma'lum qisqa kodlar (GG, SM, XX) chiqarib tashlanadi.
        #   2. "SS" + faqat raqam (SS389) — eski admin/test kodlar, chiqariladi.
        #      "SSSS333", "SSBL2" kabi to'g'ri tuman kodlari qabul qilinadi.
        #   3. Tire (-) bo'lgan kodlar (eski format) o'tkazilmaydi.
        sql = f"""
            SELECT
                SUBSTRING(UPPER(client_code) FROM 1 FOR 2) AS region_code,
                SUM(COALESCE(total_amount, summa)) AS revenue,
                SUM(CASE
                    WHEN paid_amount IS NOT NULL THEN paid_amount
                    WHEN payment_status = 'paid' THEN summa
                    ELSE 0
                END) AS paid,
                SUM(COALESCE(remaining_amount, 0)) AS debt
            FROM client_transaction_data
            WHERE 1=1 {where_clause}
                AND reys NOT LIKE 'WALLET_ADJ%'
                AND reys NOT LIKE 'SYS_ADJ%'
                AND client_code NOT LIKE '%-%'
                AND UPPER(client_code) ~ '^[A-Z]{{4}}'
                AND UPPER(client_code) !~ '^SS[0-9]'
            GROUP BY SUBSTRING(UPPER(client_code) FROM 1 FOR 2)
            ORDER BY revenue DESC
        """
        result = await session.execute(text(sql), params)
        return [dict(row) for row in result.mappings()]

    @staticmethod
    async def get_regions_hierarchical(
        session: AsyncSession,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Viloyat → tuman ierarxiyasi bilan moliyaviy ko'rsatkichlar.
        Qaytaruvchi: { region_name: { code, revenue, paid, debt,
                       districts: { district_name: { code, revenue, paid, debt } } } }
        """
        where_clause = ""
        params: dict = {}
        if start_date:
            where_clause += " AND created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            where_clause += " AND created_at <= :end_date"
            params["end_date"] = end_date

        sql = f"""
            SELECT
                SUBSTRING(UPPER(client_code) FROM 1 FOR 4) AS district_code,
                SUM(COALESCE(total_amount, summa))          AS revenue,
                SUM(CASE
                    WHEN paid_amount IS NOT NULL THEN paid_amount
                    WHEN payment_status = 'paid' THEN summa
                    ELSE 0
                END)                                        AS paid,
                SUM(COALESCE(remaining_amount, 0))          AS debt
            FROM client_transaction_data
            WHERE 1=1 {where_clause}
                AND reys NOT LIKE 'WALLET_ADJ%%'
                AND reys NOT LIKE 'SYS_ADJ%%'
                AND client_code NOT LIKE '%%-%'
                AND UPPER(client_code) ~ '^[A-Z]{{4}}'
                AND UPPER(client_code) !~ '^SS[0-9]'
            GROUP BY SUBSTRING(UPPER(client_code) FROM 1 FOR 4)
            ORDER BY revenue DESC
        """
        rows = (await session.execute(text(sql), params)).mappings().all()

        district_code_to_name: dict[str, str] = {
            prefix.upper(): (
                name_raw.replace("_t", " tumani")
                .replace("_s", " shahri")
                .replace("_", " ")
                .title()
            )
            for name_raw, prefix in AVIA_CODES.items()
        }

        result: dict[str, Any] = {}
        for row in rows:
            dcode = row["district_code"]
            rcode = dcode[:2]
            region_name = REGION_PREFIX_TO_NAME.get(rcode, f"Boshqa ({rcode})")
            district_name = district_code_to_name.get(dcode, f"Boshqa ({dcode})")

            rev  = float(row["revenue"] or 0)
            paid = float(row["paid"]    or 0)
            debt = float(row["debt"]    or 0)

            region = result.setdefault(
                region_name,
                {"code": rcode, "revenue": 0.0, "paid": 0.0, "debt": 0.0, "districts": {}},
            )
            region["revenue"] += rev
            region["paid"]    += paid
            region["debt"]    += debt
            region["districts"][district_name] = {
                "code": dcode, "revenue": rev, "paid": paid, "debt": debt
            }

        return dict(sorted(result.items(), key=lambda kv: kv[1]["revenue"], reverse=True))

    @staticmethod
    async def get_top_clients(
        session: AsyncSession,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        where_clause = ""
        params = {}
        if start_date:
            where_clause += " AND created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            where_clause += " AND created_at <= :end_date"
            params["end_date"] = end_date

        sql = f"""
            SELECT 
                client_code,
                SUM(COALESCE(total_amount, summa)) as revenue,
                SUM(CASE 
                    WHEN paid_amount IS NOT NULL THEN paid_amount
                    WHEN payment_status = 'paid' THEN summa
                    ELSE 0
                END) as paid,
                SUM(COALESCE(remaining_amount, 0)) as debt
            FROM client_transaction_data
            WHERE 1=1 {where_clause} AND reys NOT LIKE 'WALLET_ADJ%' AND reys NOT LIKE 'SYS_ADJ%'
            GROUP BY client_code
            ORDER BY revenue DESC
            LIMIT 50
        """
        result = await session.execute(text(sql), params)
        return [dict(row) for row in result.mappings()]

    @staticmethod
    async def get_flight_collections(
        session: AsyncSession,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        where_clause = ""
        params = {}
        if start_date:
            where_clause += " AND created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            where_clause += " AND created_at <= :end_date"
            params["end_date"] = end_date

        sql = f"""
            SELECT 
                reys as flight_name,
                SUM(COALESCE(total_amount, summa)) as revenue,
                SUM(CASE 
                    WHEN paid_amount IS NOT NULL THEN paid_amount
                    WHEN payment_status = 'paid' THEN summa
                    ELSE 0
                END) as paid
            FROM client_transaction_data
            WHERE 1=1 {where_clause} AND reys NOT LIKE 'WALLET_ADJ%' AND reys NOT LIKE 'SYS_ADJ%'
            GROUP BY reys
            ORDER BY revenue DESC
        """
        result = await session.execute(text(sql), params)

        rows = []
        for r in result.mappings():
            rev = float(r.get("revenue") or 0.0)
            paid = float(r.get("paid") or 0.0)
            rate = (paid / rev * 100.0) if rev > 0 else 0.0
            rows.append(
                {
                    "flight_name": r.get("flight_name"),
                    "revenue": rev,
                    "paid": paid,
                    "collection_rate": rate,
                }
            )
        return rows
