"""Cargo Item Service - Business logic layer for cargo operations."""
import math
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.cargo_item import CargoItemDAO
from src.infrastructure.database.models.cargo_item import CargoItem


class CargoItemService:
    """Service layer for cargo item operations."""

    async def _merge_and_enrich_items(
        self, session: AsyncSession, raw_items: list[CargoItem], client_id: str, flight_name: str
    ) -> list[dict]:
        from decimal import Decimal
        from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
        from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
        from src.api.services.verification.utils import get_usd_rate

        if not raw_items:
            return []

        # Fetch current USD to UZS exchange rate
        usd_rate = await get_usd_rate(session)
        usd_rate_decimal = Decimal(str(usd_rate))

        # 1. Group by track_code
        groups = {}
        for item in raw_items:
            # Fallback to item.id if track_code is completely missing, to avoid losing data
            tc = item.track_code or f"UNKNOWN_{item.id}"
            if tc not in groups:
                groups[tc] = {'pre': None, 'post': None}
            
            if item.checkin_status == 'post':
                groups[tc]['post'] = item
            else:
                groups[tc]['pre'] = item

        # 2. Fetch reliable billing data from flight_cargos
        flight_cargos = []
        if flight_name and client_id:
            flight_cargos = await FlightCargoDAO.get_by_client(session, flight_name, client_id)

        # Convert to a list so we can pop items one-by-one and "distribute" them
        fc_list = list(flight_cargos)

        # Get global fallbacks in case we run out of specific flight_cargos
        fallback_price_per_kg = fc_list[0].price_per_kg if fc_list else None
        is_sent_web = any(fc.is_sent_web for fc in flight_cargos) if flight_cargos else False

        # 3. Fetch taken away status
        transaction = None
        if flight_name and client_id:
            transaction = await ClientTransactionDAO.get_by_client_code_flight(session, client_id, flight_name)

        is_taken_away = transaction.is_taken_away if transaction else False
        taken_away_date = transaction.taken_away_date.isoformat() if transaction and transaction.taken_away_date else None

        # 4. Merge and build final output using 1-to-1 distribution (Zipping)
        merged_items = []
        for tc, pair in groups.items():
            pre = pair['pre']
            post = pair['post']
            primary = post or pre

            # Pop one flight_cargo record for this track_code if available
            current_fc = fc_list.pop(0) if fc_list else None

            force_uz_status = True if flight_cargos else False
            final_status = 'post' if (primary.checkin_status == 'post' or force_uz_status) else 'pre'

            # --- Smart Distribute Weight & Price ---
            if current_fc and current_fc.weight_kg:
                item_weight_val = float(current_fc.weight_kg)
                item_weight_str = str(current_fc.weight_kg)
                item_price_per_kg = float(current_fc.price_per_kg) if current_fc.price_per_kg else None
            else:
                # Fallback to primary (China) weight
                item_weight_str = primary.weight_kg
                item_weight_val = 0.0
                if item_weight_str and item_weight_str != '-':
                    try:
                        item_weight_val = float(str(item_weight_str).replace(',', '.'))
                    except ValueError:
                        item_weight_val = 0.0

                # Get price as float
                if fallback_price_per_kg:
                    item_price_per_kg = float(fallback_price_per_kg)
                elif primary.price_per_kg:
                    try:
                        item_price_per_kg = float(str(primary.price_per_kg).replace(',', '.'))
                    except (ValueError, AttributeError):
                        item_price_per_kg = None
                else:
                    item_price_per_kg = None

            # Calculate payment for THIS specific item
            item_payment_usd = None
            item_payment_uzs = None
            if item_weight_val > 0 and item_price_per_kg is not None:
                item_payment_usd = item_weight_val * item_price_per_kg
                item_payment_uzs = item_payment_usd * float(usd_rate_decimal)
            # ----------------------------------------

            merged = {
                'id': primary.id,
                'track_code': primary.track_code,
                'flight_name': primary.flight_name or flight_name,
                'client_id': primary.client_id or client_id,
                'item_name_cn': (post.item_name_cn if post and post.item_name_cn else None) or (pre.item_name_cn if pre else None),
                'item_name_ru': (post.item_name_ru if post and post.item_name_ru else None) or (pre.item_name_ru if pre else None),
                'quantity': (post.quantity if post and post.quantity else None) or (pre.quantity if pre else None),
                'box_number': (post.box_number if post and post.box_number else None) or (pre.box_number if pre else None),

                'weight_kg': item_weight_str if item_weight_str else "0",
                'price_per_kg_usd': str(item_price_per_kg) if item_price_per_kg else primary.price_per_kg,
                'price_per_kg_uzs': str(int(item_price_per_kg * float(usd_rate_decimal))) if item_price_per_kg else None,
                'total_payment_usd': str(round(item_payment_usd, 2)) if item_payment_usd is not None else primary.total_payment,
                'total_payment_uzs': str(int(item_payment_uzs)) if item_payment_uzs is not None else None,
                'exchange_rate': str(int(usd_rate_decimal)),

                'checkin_status': final_status,
                'pre_checkin_date': pre.pre_checkin_date if pre else None,
                'post_checkin_date': post.post_checkin_date if post else None,
                'is_sent_web': is_sent_web or (True if flight_cargos else False),
                'is_taken_away': is_taken_away,
                'taken_away_date': taken_away_date,
            }
            merged_items.append(merged)

        # If there are any leftover flight_cargos (e.g. 3 flight cargos but only 2 track codes),
        # we append them as "Unknown Track Code" items so the total weight is never lost.
        for leftover_fc in fc_list:
            item_weight_val = float(leftover_fc.weight_kg) if leftover_fc.weight_kg else 0.0
            item_price_per_kg = float(leftover_fc.price_per_kg) if leftover_fc.price_per_kg else None
            item_payment_usd = item_weight_val * item_price_per_kg if item_weight_val > 0 and item_price_per_kg else 0.0
            item_payment_uzs = item_payment_usd * float(usd_rate_decimal)

            merged_items.append({
                'id': leftover_fc.id,
                'track_code': f"EXTRA_{leftover_fc.id}",
                'flight_name': flight_name,
                'client_id': client_id,
                'item_name_cn': "Qo'shimcha yuk",
                'item_name_ru': "Дополнительный груз",
                'quantity': "1",
                'box_number': None,
                'weight_kg': str(item_weight_val),
                'price_per_kg_usd': str(item_price_per_kg) if item_price_per_kg else None,
                'price_per_kg_uzs': str(int(item_price_per_kg * float(usd_rate_decimal))) if item_price_per_kg else None,
                'total_payment_usd': str(round(item_payment_usd, 2)),
                'total_payment_uzs': str(int(item_payment_uzs)),
                'exchange_rate': str(int(usd_rate_decimal)),
                'checkin_status': 'post',
                'pre_checkin_date': None,
                'post_checkin_date': leftover_fc.created_at,
                'is_sent_web': leftover_fc.is_sent_web,
                'is_taken_away': is_taken_away,
                'taken_away_date': taken_away_date,
            })

        return merged_items

    async def search_by_track_code(self, track_code: str, session: AsyncSession) -> dict:
        all_items = await CargoItemDAO.get_by_track_code(session, track_code)
        if not all_items:
            return {'found': False, 'items': [], 'total_count': 0}
        
        # Take client_id and flight_name from the first item to fetch flight_cargos context
        client_id = all_items[0].client_id
        flight_name = all_items[0].flight_name

        merged_items = await self._merge_and_enrich_items(session, all_items, client_id, flight_name)

        return {
            'found': True,
            'items': merged_items,
            'total_count': len(merged_items),
        }

    async def get_client_cargo_summary(
        self, client_id: str, session: AsyncSession
    ) -> dict:
        """
        Get summary of cargo items for a client.

        Args:
            client_id: Client's unique identifier
            session: Database session

        Returns:
            Dictionary with cargo statistics
        """
        all_items = await CargoItemDAO.get_by_client_id(session, client_id)

        in_uzbekistan = await CargoItemDAO.count_by_client_and_status(
            session, client_id, 'post'
        )
        in_china = await CargoItemDAO.count_by_client_and_status(
            session, client_id, 'pre'
        )

        return {
            'total_items': len(all_items),
            'in_uzbekistan': in_uzbekistan,
            'in_china': in_china,
            'all_items': all_items
        }

    async def get_flight_cargo(
        self, flight_name: str, session: AsyncSession
    ) -> list[CargoItem]:
        """Get all cargo items for a specific flight."""
        return await CargoItemDAO.get_by_flight_name(session, flight_name)

    async def get_flight_summaries_for_client(
        self, client_id: str, session: AsyncSession
    ) -> list[dict]:
        """
        Get flight summaries for a client.

        Args:
            client_id: Client's unique identifier
            session: Database session

        Returns:
            List of dictionaries with flight summary data.
        """
        from src.infrastructure.database.dao.flight_cargo import FlightCargoDAO
        results = await CargoItemDAO.get_client_flight_summaries(session, client_id)

        summaries = []
        for row in results:
            flight_name = row.flight_name
            # Fetch real billed cargos for this flight & client to get true total weight
            fcs = await FlightCargoDAO.get_by_client(session, flight_name, client_id)

            if fcs:
                # Use real data from Uzbekistan
                real_total_weight = sum((float(fc.weight_kg) for fc in fcs if fc.weight_kg), 0.0)
                weight = real_total_weight
            else:
                # Fallback to China data
                weight = row.total_weight
                if weight is None:
                    weight = 0.0
                else:
                    try:
                        weight = float(weight)
                        if math.isnan(weight) or math.isinf(weight):
                            weight = 0.0
                    except (ValueError, TypeError):
                        weight = 0.0

            summaries.append({
                "flight_name": flight_name,
                "total_count": row.total_count,
                "total_weight": round(float(weight), 2),
                "last_update": row.last_update
            })

        return summaries

    async def get_flight_details_for_client(
        self,
        client_id: str,
        flight_name: str,
        page: int,
        size: int,
        session: AsyncSession
    ) -> dict:
        """
        Get detailed items for a specific flight and client.

        Fetches ALL items, merges pre/post duplicates, enriches with
        flight_cargo billing data, then paginates the merged list.

        Args:
            client_id: Client code
            flight_name: Flight name
            page: Page number (1-based)
            size: Page size
            session: DB session

        Returns:
            Dict with items and metadata
        """
        # Fetch ALL items without limit/offset to merge them properly
        raw_items, _ = await CargoItemDAO.get_items_by_client_and_flight(
            session, client_id, flight_name, limit=10000, offset=0
        )

        merged_items = await self._merge_and_enrich_items(session, raw_items, client_id, flight_name)

        # Now apply pagination on the merged list
        total_merged = len(merged_items)
        start_idx = (page - 1) * size
        end_idx = start_idx + size
        paginated_items = merged_items[start_idx:end_idx]

        return {
            "items": paginated_items,
            "total": total_merged,
            "page": page,
            "size": size
        }
