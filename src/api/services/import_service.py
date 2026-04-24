"""Service for handling Excel imports for cargo items."""
import io
from typing import Dict, Any, List, Optional
from datetime import datetime
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.infrastructure.database.models import CargoItem


class ImportService:
    """Handle Excel import operations for UZ and China databases."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def import_uz_database(
        self,
        file_content: bytes,
        filename: str
    ) -> Dict[str, Any]:
        """
        Import Uzbekistan (post-flight) database from Excel.

        Args:
            file_content: Excel file bytes
            filename: Original filename

        Returns:
            Dict with imported_count, sheets_processed, and errors
        """
        # Emit analytics event for import start
        from src.infrastructure.services.analytics_service import AnalyticsService
        await AnalyticsService.emit_event(
            session=self.session,
            event_type='import_start',
            user_id=None,
            payload={
                'import_type': 'uzbekistan',
                'filename': filename
            }
        )
        await self.session.commit()  # Commit start event immediately
        
        try:
            # Read all sheets from Excel
            excel_file = io.BytesIO(file_content)
            dfs = pd.read_excel(excel_file, sheet_name=None)

            total_created = 0
            sheets_processed = 0
            errors: List[str] = []

            for sheet_name, df in dfs.items():
                try:
                    # Expect exactly 2 columns: client_id, track_codes
                    if len(df.columns) < 2:
                        errors.append(
                            f"Sheet '{sheet_name}' has insufficient columns "
                            f"(found {len(df.columns)}, expected 2)"
                        )
                        continue

                    # Rename first two columns
                    df = df.rename(columns={
                        df.columns[0]: "client_id",
                        df.columns[1]: "track_codes",
                    })

                    # Drop rows where both client_id and track_codes are missing
                    df = df.dropna(subset=["client_id", "track_codes"], how="all")

                    # Data cleaning — handle float-like values (e.g. 123456.0 -> "123456")
                    def _to_clean_str(val):
                        if pd.isna(val):
                            return ""
                        if isinstance(val, float) and val == int(val):
                            return str(int(val)).strip()
                        return str(val).strip()

                    df["client_id"] = df["client_id"].ffill().apply(_to_clean_str)
                    df["track_codes"] = df["track_codes"].apply(_to_clean_str)

                    flight_name = sheet_name.strip()

                    # Fetch existing (flight, client, track, post) combos for fast duplicate check
                    stmt = select(CargoItem).where(
                        CargoItem.flight_name == flight_name,
                        CargoItem.checkin_status == "post",
                        CargoItem.client_id.in_(df["client_id"].unique().tolist())
                    )
                    result = await self.session.execute(stmt)
                    existing_items = result.scalars().all()
                    existing_set = {
                        (item.client_id, item.track_code)
                        for item in existing_items
                    }

                    new_items: List[CargoItem] = []

                    for _, row in df.iterrows():
                        client_id = row["client_id"]
                        track_code = row["track_codes"]  # Do not split!

                        if not client_id or not track_code:
                            continue

                        if (client_id, track_code) in existing_set:
                            continue  # Skip duplicates

                        today_date = datetime.today().strftime("%Y-%m-%d")

                        cargo_item = CargoItem(
                            flight_name=flight_name,
                            client_id=client_id,
                            track_code=track_code,
                            total_weight=None,
                            item_name_cn="-",
                            item_name_ru="-",
                            quantity=None,
                            weight_kg="-",
                            price_per_kg=None,
                            total_payment=None,
                            box_number="-",
                            checkin_status="post",
                            pre_checkin_date=today_date,
                            post_checkin_date=today_date
                        )

                        new_items.append(cargo_item)
                        # Track in-memory so later rows in same sheet don't duplicate
                        existing_set.add((client_id, track_code))

                    # Bulk insert
                    if new_items:
                        self.session.add_all(new_items)
                        total_created += len(new_items)

                    await self.session.commit()
                    sheets_processed += 1

                except Exception as e:
                    errors.append(f"Error in sheet '{sheet_name}': {str(e)}")
                    await self.session.rollback()

            # Emit analytics event for import complete
            await AnalyticsService.emit_event(
                session=self.session,
                event_type='import_complete',
                user_id=None,
                payload={
                    'import_type': 'uzbekistan',
                    'filename': filename,
                    'imported_count': total_created,
                    'sheets_processed': sheets_processed,
                    'error_count': len(errors),
                    'success': len(errors) == 0
                }
            )
            await self.session.commit()  # Commit analytics events

            return {
                "imported_count": total_created,
                "sheets_processed": sheets_processed,
                "errors": errors
            }

        except Exception as e:
            await self.session.rollback()
            raise Exception(f"Failed to import Uzbekistan database: {str(e)}")

    async def import_china_database(
        self,
        file_content: bytes,
        filename: str
    ) -> Dict[str, Any]:
        """
        Import China (pre-flight) database from Excel.

        Args:
            file_content: Excel file bytes
            filename: Original filename

        Returns:
            Dict with imported_count, sheets_processed, and errors
        """
        # Emit analytics event for import start
        from src.infrastructure.services.analytics_service import AnalyticsService
        await AnalyticsService.emit_event(
            session=self.session,
            event_type='import_start',
            user_id=None,
            payload={
                'import_type': 'china',
                'filename': filename
            }
        )
        await self.session.commit()  # Commit start event immediately
        
        try:
            # Read all sheets from Excel
            excel_file = io.BytesIO(file_content)
            dfs = pd.read_excel(excel_file, sheet_name=None)

            total_created = 0
            sheets_processed = 0
            errors: List[str] = []

            for sheet_name, df in dfs.items():
                try:
                    # Clean column names
                    df.columns = df.columns.str.strip()

                    # Check minimum columns
                    expected_cols = 8
                    if len(df.columns) < expected_cols:
                        errors.append(
                            f"Sheet '{sheet_name}' has insufficient columns "
                            f"(found {len(df.columns)}, expected {expected_cols})"
                        )
                        continue

                    # Rename columns
                    df = df.rename(columns={
                        df.columns[0]: "date",
                        df.columns[1]: "track_code",
                        df.columns[2]: "item_name_cn",
                        df.columns[3]: "item_name_ru",
                        df.columns[4]: "quantity",
                        df.columns[5]: "weight_kg",
                        df.columns[6]: "client_id",
                        df.columns[7]: "box_number",
                    })

                    # Drop rows without track_code or client_id
                    df = df.dropna(subset=["track_code", "client_id"])

                    # Data cleaning
                    df["client_id"] = df["client_id"].astype(str).str.strip()
                    df["track_code"] = df["track_code"].astype(str).str.strip()
                    df["box_number"] = df["box_number"].astype(str).str.strip()
                    df["weight_kg"] = df["weight_kg"].astype(str).str.replace(",", ".")
                    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(1).astype(int)

                    flight_name = sheet_name.strip()

                    # Fetch existing items for duplicate detection
                    stmt = select(CargoItem).where(
                        CargoItem.flight_name == flight_name,
                        CargoItem.checkin_status == "pre",
                        CargoItem.client_id.in_(df["client_id"].unique().tolist()),
                        CargoItem.track_code.in_(df["track_code"].unique().tolist())
                    )
                    result = await self.session.execute(stmt)
                    existing_items = result.scalars().all()

                    # Create set of existing items for fast lookup
                    existing_set = {
                        (
                            self._clean_value(item.flight_name),
                            self._clean_value(item.client_id),
                            self._clean_value(item.track_code),
                            self._clean_value(item.item_name_cn),
                            self._clean_value(item.item_name_ru),
                            self._clean_value(str(item.quantity)),
                            self._clean_value(str(item.weight_kg)),
                            self._clean_value(item.box_number),
                            self._clean_value(str(item.pre_checkin_date))
                        )
                        for item in existing_items
                    }

                    new_items = []

                    # Process each row
                    for _, row in df.iterrows():
                        # Create unique key for duplicate detection
                        key = (
                            self._clean_value(flight_name),
                            self._clean_value(row["client_id"]),
                            self._clean_value(row["track_code"]),
                            self._clean_value(row.get("item_name_cn")),
                            self._clean_value(row.get("item_name_ru")),
                            self._clean_value(str(row["quantity"])),
                            self._clean_value(str(row.get("weight_kg"))),
                            self._clean_value(row.get("box_number")),
                            self._clean_value(str(row["date"]))
                        )

                        if key in existing_set:
                            continue  # Skip duplicates

                        # Create new cargo item
                        cargo_item = CargoItem(
                            flight_name=flight_name,
                            client_id=self._clean_value(row["client_id"]),
                            track_code=self._clean_value(row["track_code"]),
                            item_name_cn=self._clean_value(row.get("item_name_cn")),
                            item_name_ru=self._clean_value(row.get("item_name_ru")),
                            quantity=self._clean_value(row["quantity"]),
                            weight_kg=self._clean_value(row.get("weight_kg")),
                            price_per_kg=None,
                            total_payment=None,
                            box_number=self._clean_value(row.get("box_number")),
                            checkin_status="pre",
                            pre_checkin_date=self._clean_value(row["date"]),
                            post_checkin_date=None
                        )

                        new_items.append(cargo_item)

                    # Bulk insert
                    if new_items:
                        self.session.add_all(new_items)
                        await self.session.commit()
                        total_created += len(new_items)

                    sheets_processed += 1

                except Exception as e:
                    errors.append(f"Error in sheet '{sheet_name}': {str(e)}")
                    await self.session.rollback()

            # Emit analytics event for import complete
            await AnalyticsService.emit_event(
                session=self.session,
                event_type='import_complete',
                user_id=None,
                payload={
                    'import_type': 'china',
                    'filename': filename,
                    'imported_count': total_created,
                    'sheets_processed': sheets_processed,
                    'error_count': len(errors),
                    'success': len(errors) == 0
                }
            )
            await self.session.commit()  # Commit analytics events

            return {
                "imported_count": total_created,
                "sheets_processed": sheets_processed,
                "errors": errors
            }

        except Exception as e:
            await self.session.rollback()
            raise Exception(f"Failed to import China database: {str(e)}")

    @staticmethod
    def _clean_value(val: Any) -> Optional[str]:
        """
        Normalize empty/NaN values to None, and strip strings.

        Args:
            val: Value to clean

        Returns:
            Cleaned string value or None
        """
        if pd.isna(val):
            return None
        if isinstance(val, str):
            val = val.strip()
            return val if val else None
        return str(val) if val is not None else None
