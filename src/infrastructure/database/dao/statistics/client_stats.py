from datetime import date, datetime, timedelta
from typing import Any
import re
from sqlalchemy import select, func, and_, or_, distinct, case, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.delivery_request import DeliveryRequest
from src.api.utils.constants import (
    DISTRICTS,
    REGIONS,
    UZBEKISTAN_REGIONS,
    get_district_name,
    get_region_name,
)
from src.infrastructure.tools.datetime_utils import get_current_time


class ClientStatsDAO:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_overview_and_retention(
        self, start_date: date | None, end_date: date | None
    ) -> dict[str, Any]:
        """
        Gathers overview and retention stats efficiently.
        """
        end_dt = (
            datetime.combine(end_date, datetime.max.time())
            if end_date
            else get_current_time()
        )
        start_dt = (
            datetime.combine(start_date, datetime.min.time())
            if start_date
            else datetime(2020, 1, 1)
        )

        # Using a raw SQL query with subqueries to make the aggregations blazingly fast
        # and easy to read/modify.
        # We define Active = last cargo within 45 days.
        # Passive = client > 60 days old AND last cargo > 60 days ago (or never had cargo but >60d old).
        query = """
        WITH client_cargos AS (
            SELECT 
                c.id as client_id,
                c.created_at as client_created_at,
                COUNT(fc.id) as total_cargos,
                COUNT(DISTINCT fc.flight_name) as total_flights,
                MAX(fc.created_at) as last_cargo_date
            FROM clients c
            LEFT JOIN flight_cargos fc 
                ON (fc.client_id = c.extra_code OR fc.client_id = c.client_code)
                AND fc.created_at <= :end_dt
            WHERE c.created_at <= :end_dt
            GROUP BY c.id, c.created_at
        )
        SELECT 
            -- Overview
            COUNT(*) as total_clients,
            SUM(CASE WHEN client_created_at >= :start_dt THEN 1 ELSE 0 END) as new_clients,
            SUM(CASE WHEN last_cargo_date >= :active_threshold THEN 1 ELSE 0 END) as active_clients,
            SUM(CASE WHEN client_created_at <= :passive_threshold_c AND (last_cargo_date IS NULL OR last_cargo_date <= :passive_threshold_fc) THEN 1 ELSE 0 END) as passive_clients,
            SUM(CASE WHEN total_cargos = 0 THEN 1 ELSE 0 END) as zombie_clients,
            
            -- Retention
            SUM(CASE WHEN total_flights > 1 THEN 1 ELSE 0 END) as repeat_clients,
            SUM(CASE WHEN total_flights = 1 THEN 1 ELSE 0 END) as one_time_clients,
            SUM(CASE WHEN total_flights >= 5 THEN 1 ELSE 0 END) as most_frequent_clients
        FROM client_cargos;
        """

        active_threshold = end_dt - timedelta(days=45)
        passive_threshold_c = end_dt - timedelta(days=60)
        passive_threshold_fc = end_dt - timedelta(days=60)

        result = await self.session.execute(
            text(query),
            {
                "start_dt": start_dt,
                "end_dt": end_dt,
                "active_threshold": active_threshold,
                "passive_threshold_c": passive_threshold_c,
                "passive_threshold_fc": passive_threshold_fc,
            },
        )
        row = result.fetchone()

        # is_logged_in count is a current-state metric, not date-filtered
        logged_in_result = await self.session.execute(
            text("SELECT COUNT(*) FROM clients WHERE is_logged_in = TRUE")
        )
        logged_in_count = int(logged_in_result.scalar() or 0)

        if row:
            return {
                "total_clients": int(row.total_clients or 0),
                "new_clients": int(row.new_clients or 0),
                "active_clients": int(row.active_clients or 0),
                "passive_clients": int(row.passive_clients or 0),
                "zombie_clients": int(row.zombie_clients or 0),
                "repeat_clients": int(row.repeat_clients or 0),
                "one_time_clients": int(row.one_time_clients or 0),
                "most_frequent_clients": int(row.most_frequent_clients or 0),
                "logged_in_clients": logged_in_count,
            }
        else:
            return {
                "total_clients": 0,
                "new_clients": 0,
                "active_clients": 0,
                "passive_clients": 0,
                "zombie_clients": 0,
                "repeat_clients": 0,
                "one_time_clients": 0,
                "most_frequent_clients": 0,
                "logged_in_clients": logged_in_count,
            }

    async def get_region_stats(
        self, start_date: date | None, end_date: date | None
    ) -> dict[str, Any]:
        """
        Viloyat/shahar → tumanlar bo'yicha mijozlar soni va moliyaviy
        ko'rsatkichlarni birlashtirib qaytaradi.

        Qaytaruvchi format:
          {
            "Toshkent shahri": {
              "code": "ST",
              "count": 45,            # mijozlar soni
              "revenue": 82_300_000,  # jami hisoblangan summa
              "paid":    60_000_000,  # to'langan summa
              "debt":    22_300_000,  # qarz
              "districts": {
                "Chilonzor tumani": {
                  "code": "STCH",
                  "count": 12,
                  "revenue": 22_300_000,
                  "paid":    17_000_000,
                  "debt":     5_300_000
                }, ...
              }
            }, ...
          }
        """
        end_dt = (
            datetime.combine(end_date, datetime.max.time())
            if end_date
            else get_current_time()
        )
        start_dt = (
            datetime.combine(start_date, datetime.min.time())
            if start_date
            else datetime(2020, 1, 1)
        )

        # New format helpers: extract numeric region code (chars 4-5 after
        # the ``AKB`` partner prefix) and the district subcode that always
        # follows the ``-`` separator (``AKB{rr}-{ds}/{seq}``).
        akb_code_re = re.compile(r"^AKB(\d{2})-(\d+)/")

        # ---- Query 1: Mijozlar soni hudud/tuman bo'yicha ----
        client_rows = (
            await self.session.execute(
                select(Client.extra_code, Client.client_code).where(
                    Client.created_at >= start_dt, Client.created_at <= end_dt
                )
            )
        ).all()

        # Group key: (region_code, district_subcode|"")
        district_counts: dict[tuple[str, str], int] = {}
        for row in client_rows:
            code = (row.extra_code or row.client_code or "").upper()
            m = akb_code_re.match(code)
            if not m:
                continue
            key = (m.group(1), m.group(2))
            district_counts[key] = district_counts.get(key, 0) + 1

        # ---- Query 2: Moliyaviy ko'rsatkichlar tuman bo'yicha ----
        fin_sql = text("""
            SELECT
                SUBSTRING(UPPER(client_code) FROM 4 FOR 2) AS region_code,
                SUBSTRING(UPPER(client_code) FROM '^AKB[0-9]{2}-([0-9]+)/') AS district_subcode,
                SUM(COALESCE(total_amount, summa))          AS revenue,
                SUM(CASE
                    WHEN paid_amount IS NOT NULL THEN paid_amount
                    WHEN payment_status = 'paid' THEN summa
                    ELSE 0
                END)                                        AS paid,
                SUM(COALESCE(remaining_amount, 0))          AS debt
            FROM client_transaction_data
            WHERE created_at >= :start_dt
              AND created_at <= :end_dt
              AND UPPER(client_code) ~ '^AKB[0-9]{2}'
              AND reys NOT LIKE 'WALLET_ADJ%%'
              AND reys NOT LIKE 'SYS_ADJ%%'
            GROUP BY region_code, district_subcode
        """)
        fin_rows = (
            await self.session.execute(fin_sql, {"start_dt": start_dt, "end_dt": end_dt})
        ).mappings().all()

        district_fin: dict[tuple[str, str], dict[str, float]] = {
            (row["region_code"], row["district_subcode"] or ""): {
                "revenue": float(row["revenue"] or 0),
                "paid":    float(row["paid"]    or 0),
                "debt":    float(row["debt"]    or 0),
            }
            for row in fin_rows
        }

        # ---- Birlashtirish: region → districts ----
        all_keys = set(district_counts) | set(district_fin)
        region_map: dict[str, Any] = {}

        for rcode, sub in all_keys:
            region_name = REGIONS.get(rcode, get_region_name(rcode))
            fin = district_fin.get((rcode, sub), {"revenue": 0.0, "paid": 0.0, "debt": 0.0})
            count = district_counts.get((rcode, sub), 0)

            region = region_map.setdefault(
                region_name,
                {"code": rcode, "count": 0, "revenue": 0.0, "paid": 0.0, "debt": 0.0, "districts": {}},
            )
            region["count"]   += count
            region["revenue"] += fin["revenue"]
            region["paid"]    += fin["paid"]
            region["debt"]    += fin["debt"]

            if sub:
                dcode = f"{rcode}-{sub}"
                d_name = (
                    DISTRICTS[dcode]["name"] if dcode in DISTRICTS
                    else get_district_name(dcode)
                )
                region["districts"][d_name] = {
                    "code":    dcode,
                    "count":   count,
                    "revenue": fin["revenue"],
                    "paid":    fin["paid"],
                    "debt":    fin["debt"],
                }

        # Districts ichida revenue bo'yicha tartiblash
        for region in region_map.values():
            region["districts"] = dict(
                sorted(region["districts"].items(), key=lambda kv: kv[1]["revenue"], reverse=True)
            )

        # Regionlarni revenue bo'yicha tartiblash
        return dict(
            sorted(region_map.items(), key=lambda kv: kv[1]["revenue"], reverse=True)
        )

    async def get_delivery_stats(
        self, start_date: date | None, end_date: date | None
    ) -> list[dict[str, Any]]:
        """
        Gets delivery methods merged from two sources:
        - delivery_requests  (customer zayavka requests)
        - cargo_delivery_proofs  (actual warehouse take-away proofs)
        """
        end_dt = (
            datetime.combine(end_date, datetime.max.time())
            if end_date
            else get_current_time()
        )
        start_dt = (
            datetime.combine(start_date, datetime.min.time())
            if start_date
            else datetime(2020, 1, 1)
        )

        method_map = {
            "uzpost": "Pochta (UzPost)",
            "yandex": "Yandex Dostavka",
            "akb": "AKB Dostavka",
            "bts": "BTS Pochta",
            "self_pickup": "O'zi olib ketish",
        }

        # --- Source 1: delivery_requests ---
        req_rows = (
            await self.session.execute(
                select(DeliveryRequest.delivery_type, func.count(DeliveryRequest.id))
                .where(
                    DeliveryRequest.created_at >= start_dt,
                    DeliveryRequest.created_at <= end_dt,
                )
                .group_by(DeliveryRequest.delivery_type)
            )
        ).all()

        # --- Source 2: cargo_delivery_proofs ---
        proof_sql = text("""
            SELECT delivery_method, COUNT(id) AS cnt
            FROM cargo_delivery_proofs
            WHERE created_at >= :start_dt
              AND created_at <= :end_dt
            GROUP BY delivery_method
        """)
        proof_rows = (
            await self.session.execute(proof_sql, {"start_dt": start_dt, "end_dt": end_dt})
        ).mappings().all()

        # Merge counts by normalised key
        merged: dict[str, int] = {}
        for delivery_type, count in req_rows:
            key = delivery_type.lower()
            merged[key] = merged.get(key, 0) + int(count)
        for row in proof_rows:
            key = row["delivery_method"].lower()
            merged[key] = merged.get(key, 0) + int(row["cnt"])

        stats = [
            {
                "method": method_map.get(key, key.capitalize()),
                "count": count,
            }
            for key, count in merged.items()
        ]
        stats.sort(key=lambda x: x["count"], reverse=True)
        return stats

    async def get_zombie_clients(
        self, start_date: date | None, end_date: date | None
    ) -> list[dict[str, Any]]:
        """
        Hech qachon yuk olmagan mijozlar (flight_cargos da yo'q).
        start_date/end_date → clients.created_at bo'yicha filtrlaydi.
        """
        end_dt = datetime.combine(end_date, datetime.max.time()) if end_date else get_current_time()
        start_dt = datetime.combine(start_date, datetime.min.time()) if start_date else datetime(2020, 1, 1)

        sql = text("""
            SELECT
                c.id,
                c.client_code,
                c.extra_code,
                c.legacy_code,
                c.phone,
                c.created_at,
                c.updated_at,
                c.last_seen_at
            FROM clients c
            WHERE c.created_at >= :start_dt
              AND c.created_at <= :end_dt
              AND NOT EXISTS (
                  SELECT 1 FROM flight_cargos fc
                  WHERE fc.client_id = c.client_code
                     OR fc.client_id = c.extra_code
                     OR fc.client_id = c.legacy_code
              )
            ORDER BY c.created_at DESC
        """)
        rows = (await self.session.execute(sql, {"start_dt": start_dt, "end_dt": end_dt})).mappings().all()

        result = []
        for r in rows:
            codes = [c for c in [r["extra_code"], r["client_code"], r["legacy_code"]] if c]
            result.append({
                "active_codes": " | ".join(codes) if codes else "—",
                "phone": r["phone"] or "",
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "last_seen_at": r["last_seen_at"],
            })
        return result

    async def get_passive_clients(
        self, start_date: date | None, end_date: date | None
    ) -> list[dict[str, Any]]:
        """
        Passiv mijozlar: kamida 1 ta yuklari bo'lgan, lekin oxirgi 60 kundа yuk olmagan.
        start_date/end_date → clients.created_at bo'yicha filtrlaydi.
        """
        end_dt = datetime.combine(end_date, datetime.max.time()) if end_date else get_current_time()
        start_dt = datetime.combine(start_date, datetime.min.time()) if start_date else datetime(2020, 1, 1)
        passive_threshold = end_dt - timedelta(days=60)

        sql = text("""
            SELECT
                c.id,
                c.client_code,
                c.extra_code,
                c.legacy_code,
                c.phone,
                c.created_at,
                c.updated_at,
                c.last_seen_at,
                MAX(fc.created_at)   AS last_cargo_date,
                MAX(fc.flight_name)  AS last_flight_name,
                MAX(fc.weight_kg)    AS last_weight_kg
            FROM clients c
            JOIN flight_cargos fc
              ON fc.client_id = c.client_code
              OR fc.client_id = c.extra_code
              OR fc.client_id = c.legacy_code
            WHERE c.created_at >= :start_dt
              AND c.created_at <= :end_dt
            GROUP BY c.id, c.client_code, c.extra_code, c.legacy_code,
                     c.phone, c.created_at, c.updated_at, c.last_seen_at
            HAVING MAX(fc.created_at) < :passive_threshold
            ORDER BY MAX(fc.created_at) DESC
        """)
        rows = (
            await self.session.execute(
                sql, {"start_dt": start_dt, "end_dt": end_dt, "passive_threshold": passive_threshold}
            )
        ).mappings().all()

        result = []
        for r in rows:
            codes = [c for c in [r["extra_code"], r["client_code"], r["legacy_code"]] if c]
            result.append({
                "active_codes": " | ".join(codes) if codes else "—",
                "phone": r["phone"] or "",
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "last_seen_at": r["last_seen_at"],
                "last_cargo_date": r["last_cargo_date"],
                "last_flight_name": r["last_flight_name"] or "",
                "last_weight_kg": float(r["last_weight_kg"] or 0),
            })
        return result

    async def get_frequent_clients(self, min_flights: int = 5) -> list[dict[str, Any]]:
        """
        5 va undan ortiq reysda yuklari bo'lgan mijozlar.
        """
        sql = text("""
            SELECT
                c.id,
                c.client_code,
                c.extra_code,
                c.legacy_code,
                c.phone,
                c.created_at,
                c.updated_at,
                c.last_seen_at,
                COUNT(DISTINCT fc.flight_name) AS flight_count,
                COUNT(fc.id)                   AS total_cargos,
                COALESCE(SUM(fc.weight_kg), 0) AS total_weight_kg
            FROM clients c
            JOIN flight_cargos fc
              ON fc.client_id = c.client_code
              OR fc.client_id = c.extra_code
              OR fc.client_id = c.legacy_code
            GROUP BY c.id, c.client_code, c.extra_code, c.legacy_code,
                     c.phone, c.created_at, c.updated_at, c.last_seen_at
            HAVING COUNT(DISTINCT fc.flight_name) >= :min_flights
            ORDER BY COUNT(DISTINCT fc.flight_name) DESC
        """)
        rows = (
            await self.session.execute(sql, {"min_flights": min_flights})
        ).mappings().all()

        result = []
        for r in rows:
            codes = [c for c in [r["extra_code"], r["client_code"], r["legacy_code"]] if c]
            result.append({
                "active_codes": " | ".join(codes) if codes else "—",
                "phone": r["phone"] or "",
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "last_seen_at": r["last_seen_at"],
                "flight_count": int(r["flight_count"]),
                "total_cargos": int(r["total_cargos"]),
                "total_weight_kg": float(r["total_weight_kg"]),
            })
        return result
