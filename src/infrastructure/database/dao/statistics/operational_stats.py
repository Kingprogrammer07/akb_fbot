from datetime import date
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class OperationalStatsDAO:
    @staticmethod
    async def get_operational_summary(
        session: AsyncSession,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict:
        """
        Get average times for each delivery stage using raw SQL.
        """
        query_text = """
            WITH cargo_data AS (
                SELECT
                    fc.id,
                    fc.flight_name,
                    fc.client_id,
                    ci.created_at AS cn_received_at,
                    fc.created_at AS uz_received_at,
                    fc.is_sent_date AS notified_at,
                    t.fully_paid_date AS paid_at,
                    t.taken_away_date AS handed_over_at,
                    CASE 
                        WHEN t.is_taken_away = TRUE AND dr.delivery_type IS NULL THEN 'Self Pickup'
                        WHEN dr.delivery_type IS NOT NULL THEN dr.delivery_type
                        ELSE 'Omborda (Jarayonda)'
                    END AS delivery_type
                FROM flight_cargos fc
                LEFT JOIN cargo_items ci ON ci.flight_name = fc.flight_name AND ci.client_id = fc.client_id
                LEFT JOIN client_transaction_data t ON t.reys = fc.flight_name AND t.client_code = fc.client_id
                LEFT JOIN delivery_requests dr ON dr.client_id::text = t.client_code::text AND dr.status = 'approved'
                WHERE 1=1
        """

        params = {}
        if start_date:
            query_text += " AND fc.created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            query_text += " AND fc.created_at <= :end_date"
            params["end_date"] = end_date

        query_text += """
            )
            SELECT
                COUNT(DISTINCT id) as total_cargos,
                AVG(EXTRACT(EPOCH FROM (uz_received_at - cn_received_at)) / 86400.0) as avg_cn_to_uz,
                AVG(EXTRACT(EPOCH FROM (notified_at - uz_received_at)) / 86400.0) as avg_uz_to_notify,
                AVG(EXTRACT(EPOCH FROM (paid_at - notified_at)) / 86400.0) as avg_notify_to_pay,
                AVG(EXTRACT(EPOCH FROM (handed_over_at - paid_at)) / 86400.0) as avg_pay_to_handover,
                delivery_type
            FROM cargo_data
            GROUP BY delivery_type
        """

        result = await session.execute(text(query_text), params)
        rows = result.fetchall()

        total_cargos = 0
        cn_to_uz_sum = 0
        uz_to_notify_sum = 0
        notify_to_pay_sum = 0
        pay_to_handover_sum = 0
        stages_count = 0

        delivery_counts = {}

        for row in rows:
            cnt = row.total_cargos or 0
            if cnt > 0:
                total_cargos += cnt
                dtype = row.delivery_type or "Unknown"
                delivery_counts[dtype] = delivery_counts.get(dtype, 0) + cnt

            if row.avg_cn_to_uz is not None:
                cn_to_uz_sum += float(row.avg_cn_to_uz)
                uz_to_notify_sum += float(row.avg_uz_to_notify or 0)
                notify_to_pay_sum += float(row.avg_notify_to_pay or 0)
                pay_to_handover_sum += float(row.avg_pay_to_handover or 0)
                stages_count += 1

        # Calculate overall averages
        avg_cn_to_uz = round(cn_to_uz_sum / stages_count, 2) if stages_count else 0.0
        avg_uz_to_notify = (
            round(uz_to_notify_sum / stages_count, 2) if stages_count else 0.0
        )
        avg_notify_to_pay = (
            round(notify_to_pay_sum / stages_count, 2) if stages_count else 0.0
        )
        avg_pay_to_handover = (
            round(pay_to_handover_sum / stages_count, 2) if stages_count else 0.0
        )

        stages = [
            {"stage_name": "Xitoydan -> O'zbekistonga", "avg_days": avg_cn_to_uz},
            {"stage_name": "O'zbekistonda -> Xabargacha", "avg_days": avg_uz_to_notify},
            {"stage_name": "Xabar -> To'lovgacha", "avg_days": avg_notify_to_pay},
            {
                "stage_name": "To'lov -> Olib ketishgacha",
                "avg_days": avg_pay_to_handover,
            },
        ]

        delivery_types = []
        for dtype, count in delivery_counts.items():
            perc = round((count / total_cargos) * 100, 2) if total_cargos else 0.0
            delivery_types.append(
                {"delivery_type": str(dtype), "count": count, "percentage": perc}
            )

        bottlenecks = [s for s in stages if s["avg_days"] > 3.0]
        bottlenecks.sort(key=lambda x: x["avg_days"], reverse=True)

        return {
            "start_date": start_date,
            "end_date": end_date,
            "total_cargos_analyzed": total_cargos,
            "stages": stages,
            "delivery_types": delivery_types,
            "bottlenecks": bottlenecks,
        }
