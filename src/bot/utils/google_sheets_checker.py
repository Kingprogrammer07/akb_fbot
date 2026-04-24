import asyncio
import logging
import aiohttp
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class GoogleSheetsChecker:
    def __init__(
        self,
        spreadsheet_id: str,
        api_key: str,
        timeout: int = 30,
        last_n_sheets: int = 5,
        max_columns: str = "Z",
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.api_key = api_key
        self.last_n_sheets = last_n_sheets
        self.max_columns = max_columns
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self.meta_url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/"
            f"{spreadsheet_id}"
            f"?fields=sheets.properties"
            f"&key={api_key}"
        )

        self.batch_values_url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/"
            f"{spreadsheet_id}/values:batchGet"
            f"?key={api_key}"
        )

        self.single_values_url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/"
            f"{spreadsheet_id}/values/{{range}}"
            f"?key={api_key}"
        )

    async def _fetch_json(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Fetch JSON with retry logic for transient errors.

        Retries on ClientError and TimeoutError up to max_retries times.
        Does NOT retry on CancelledError - re-raises immediately.
        """
        last_exception: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                async with session.get(url, params=params) as r:
                    r.raise_for_status()
                    return await r.json()
            except asyncio.CancelledError:
                logger.warning(
                    f"Request cancelled (attempt {attempt}/{self.max_retries}): {url}"
                )
                raise  # Never retry cancelled tasks
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exception = e
                logger.warning(
                    f"Request failed (attempt {attempt}/{self.max_retries}): {url} - {e}"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(2**attempt)

        # All retries exhausted
        raise last_exception  # type: ignore[misc]

    @staticmethod
    def _clean_cell(value: Any) -> Any:
        """Clean a single cell value."""
        if isinstance(value, str):
            return value.replace("\u00a0", " ").strip()
        return value

    def _clean_row(self, row: List[Any]) -> List[Any]:
        """Clean all cells in a row."""
        return [self._clean_cell(v) for v in row]

    # Prefixes recognised as "flight" worksheets.
    #   M   → regular flights (e.g. M123-2025)
    #   A-  → ostatka (leftover) flights (e.g. A-2025-04)
    _FLIGHT_PREFIXES: tuple[str, ...] = ("M", "A-")
    _OSTATKA_PREFIX: str = "A-"

    @classmethod
    def _is_flight_sheet(cls, name: str) -> bool:
        """Check if sheet name is a recognised flight worksheet."""
        upper = name.strip().upper()
        return any(upper.startswith(p) for p in cls._FLIGHT_PREFIXES)

    @classmethod
    def _is_ostatka_sheet(cls, name: str) -> bool:
        """Return True when the sheet belongs to the A- (ostatka) group."""
        return name.strip().upper().startswith(cls._OSTATKA_PREFIX)

    def _filter_flight_sheets(self, names: List[str]) -> List[str]:
        """Filter sheet names to only include flight sheets (M or A-)."""
        return [name for name in names if self._is_flight_sheet(name)]

    async def _get_last_sheet_names(
        self, session: aiohttp.ClientSession, reverse: bool = False
    ) -> List[str]:
        """Get last N flight sheet names grouped by prefix.

        Returns ``self.last_n_sheets`` most-recent sheets **per prefix** (M, A-),
        preserving the original worksheet order within each group, and then
        concatenating the groups (M first, A- second).  This lets the API layer
        expose both flight types simultaneously without exceeding the per-group
        cap requested by the caller.
        """
        meta = await self._fetch_json(session, self.meta_url)
        all_sheets = meta.get("sheets", [])
        all_names = [s["properties"]["title"] for s in all_sheets]

        m_names = [n for n in all_names if not self._is_ostatka_sheet(n) and self._is_flight_sheet(n)]
        a_names = [n for n in all_names if self._is_ostatka_sheet(n)]

        m_last = m_names[-self.last_n_sheets :]
        a_last = a_names[-self.last_n_sheets :]

        combined = m_last + a_last
        return list(reversed(combined)) if reverse else combined

    # ==========================================================
    # 1️⃣ EARLY EXIT (eng tez)
    # ==========================================================
    async def find_code(
        self, code: str, reverse: bool = False
    ) -> Optional[Dict[str, Any]]:
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            sheet_names = await self._get_last_sheet_names(session, reverse)

            ranges = [f"{name}!A:A" for name in sheet_names]

            data = await self._fetch_json(
                session, self.batch_values_url, params={"ranges": ranges}
            )

            value_ranges = data.get("valueRanges", [])
            if reverse:
                value_ranges = list(reversed(value_ranges))

            for value_range in value_ranges:
                sheet_name = value_range["range"].split("!")[0]
                rows = value_range.get("values", [])

                row_iter = (
                    reversed(list(enumerate(rows, start=1)))
                    if reverse
                    else enumerate(rows, start=1)
                )

                for row_number, row in row_iter:
                    if row and self._clean_cell(row[0]) == code:
                        full_range = (
                            f"{sheet_name}!A{row_number}:{self.max_columns}{row_number}"
                        )

                        row_resp = await self._fetch_json(
                            session, self.single_values_url.format(range=full_range)
                        )

                        return {
                            "worksheet": sheet_name,
                            "row_number": row_number,
                            "row_data": self._clean_row(
                                row_resp.get("values", [[]])[0]
                            ),
                        }

        return None

    # ==========================================================
    # 2️⃣ FULL SCAN (hammasini topadi)
    # ==========================================================
    async def find_code_all(self, code: str, reverse: bool = False) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            sheet_names = await self._get_last_sheet_names(session, reverse)

            ranges = [f"{name}!A:A" for name in sheet_names]

            data = await self._fetch_json(
                session, self.batch_values_url, params={"ranges": ranges}
            )

            value_ranges = data.get("valueRanges", [])
            if reverse:
                value_ranges = list(reversed(value_ranges))

            for value_range in value_ranges:
                sheet_name = value_range["range"].split("!")[0]
                rows = value_range.get("values", [])

                row_iter = (
                    reversed(list(enumerate(rows, start=1)))
                    if reverse
                    else enumerate(rows, start=1)
                )

                for row_number, row in row_iter:
                    if row and self._clean_cell(row[0]) == code:
                        full_range = (
                            f"{sheet_name}!A{row_number}:{self.max_columns}{row_number}"
                        )

                        row_resp = await self._fetch_json(
                            session, self.single_values_url.format(range=full_range)
                        )

                        results.append(
                            {
                                "worksheet": sheet_name,
                                "row_number": row_number,
                                "row_data": self._clean_row(
                                    row_resp.get("values", [[]])[0]
                                ),
                            }
                        )

        return {"found": bool(results), "matches": results}

    # ==========================================================
    # 3️⃣ CLIENT GROUP — SSxxxx → ALL DPK TRACK CODES
    # ==========================================================
    async def find_client_group(
        self, client_code: str | list[str], reverse: bool = False
    ) -> Dict[str, Any]:
        """
        Find client group with all track codes.

        For a client code like "SS500", this will find all rows where:
        - Column A = client_code (header row)
        - Subsequent rows with empty Column A but data in Column B (track codes)

        Args:
            client_code: Client code or list of codes to search for

        Returns:
            Dict with "found" (bool) and "matches" (list of dicts):
                - worksheet: sheet name
                - row_number: header row number
                - row_data: full row data from header
                - track_codes: list of all track codes (from B column)
        """
        if isinstance(client_code, list):
            client_codes_upper_list = [c.strip().upper() for c in client_code if c]
        else:
            client_codes_upper_list = [client_code.strip().upper()]

        results: List[Dict[str, Any]] = []

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            sheet_names = await self._get_last_sheet_names(session, reverse)

            for sheet_name in sheet_names:
                ab_url = self.single_values_url.format(range=f"{sheet_name}!A:B")
                data = await self._fetch_json(session, ab_url)
                rows = data.get("values", [])

                found = False
                header_row_number: int | None = None
                track_codes: List[str] = []
                matched_code: str = ""
                for idx, row in enumerate(rows, start=1):
                    a_col = self._clean_cell(row[0]) if len(row) > 0 else ""
                    b_col = self._clean_cell(row[1]) if len(row) > 1 else ""

                    if a_col.strip().upper() in client_codes_upper_list:
                        found = True
                        header_row_number = idx
                        matched_code = a_col.strip().upper()

                        if b_col:
                            track_codes.append(b_col)
                        continue

                    if found and not a_col:
                        if b_col:
                            track_codes.append(b_col)
                        continue

                    if found and a_col:
                        break

                if found and header_row_number:
                    results.append(
                        {
                            "flight_name": sheet_name,
                            "row_number": header_row_number,
                            "client_code": matched_code,
                            "track_codes": track_codes,
                        }
                    )

        return {"found": bool(results), "matches": results}

    # ==========================================================
    # 4️⃣ GET LAST FLIGHT SHEET NAMES
    # ==========================================================
    async def get_flight_sheet_names(self, last_n: int = 5) -> List[str]:
        """
        Get last N flight sheet names starting with 'M'.
        Example:
            M123-2025
            M456-M789-2025
        """
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            # Temporarily adjust last_n_sheets for this request
            old_n = self.last_n_sheets
            self.last_n_sheets = last_n

            names = await self._get_last_sheet_names(session)

            self.last_n_sheets = old_n  # Restore original

        return names

    # ==========================================================
    # 5️⃣ GET ALL CLIENTS IN A FLIGHT
    # ==========================================================
    async def get_all_clients_in_flight(self, flight_name: str) -> List[Dict[str, Any]]:
        """
        Get all clients and their data from a specific flight sheet.

        Sheet structure:
            A: Client Code
            B: Track Code
            C: Weight
            D: Price per kg
            E: Total payment
            F: Payment status

        Args:
            flight_name: Name of the flight sheet

        Returns:
            List of client dictionaries with their data and track codes
        """
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            url = self.single_values_url.format(range=f"{flight_name}!A:F")
            data = await self._fetch_json(session, url)

        rows = data.get("values", [])
        if not rows:
            return []

        clients: List[Dict[str, Any]] = []

        current_client: Optional[str] = None
        current_track_codes: List[str] = []
        current_row_data: List[Any] = []
        current_row_number: Optional[int] = None

        # Skip header row (row 1)
        for idx, row in enumerate(rows[1:], start=2):
            a_col = self._clean_cell(row[0]) if len(row) > 0 else ""
            b_col = self._clean_cell(row[1]) if len(row) > 1 else ""

            # New client code found
            if a_col:
                # Save previous client if exists
                if current_client:
                    clients.append(
                        {
                            "flight": flight_name,
                            "client_code": current_client,
                            "row_number": current_row_number,
                            "track_codes": current_track_codes.copy(),
                            "weight_kg": self._clean_cell(current_row_data[2])
                            if len(current_row_data) > 2
                            else None,
                            "price_per_kg": self._clean_cell(current_row_data[3])
                            if len(current_row_data) > 3
                            else None,
                            "total_payment": self._clean_cell(current_row_data[4])
                            if len(current_row_data) > 4
                            else None,
                            "payment_status": self._clean_cell(current_row_data[5])
                            if len(current_row_data) > 5
                            else None,
                        }
                    )

                # Start new client
                current_client = a_col
                current_row_number = idx
                current_row_data = row
                current_track_codes = [b_col] if b_col else []

            # Continuation of current client (empty A, but has B)
            elif b_col and current_client:
                current_track_codes.append(b_col)

        # Save last client
        if current_client:
            clients.append(
                {
                    "flight": flight_name,
                    "client_code": current_client,
                    "row_number": current_row_number,
                    "track_codes": current_track_codes.copy(),
                    "weight_kg": self._clean_cell(current_row_data[2])
                    if len(current_row_data) > 2
                    else None,
                    "price_per_kg": self._clean_cell(current_row_data[3])
                    if len(current_row_data) > 3
                    else None,
                    "total_payment": self._clean_cell(current_row_data[4])
                    if len(current_row_data) > 4
                    else None,
                    "payment_status": self._clean_cell(current_row_data[5])
                    if len(current_row_data) > 5
                    else None,
                }
            )

        return clients

    # ==========================================================
    # 6️⃣ GET TRACK CODES BY FLIGHT AND CLIENT
    # ==========================================================
    async def get_track_codes_by_flight_and_client(
        self, flight_name: str, client_code: str | list[str]
    ) -> List[str]:
        """
        Get track codes for a specific client in a specific flight sheet.

        Opens ONLY the specified sheet (flight_name).
        Reads columns A:B.
        Finds row where column A == client_code.
        Collects:
            - column B from that row
            - subsequent rows where:
                - column A is empty
                - column B has value
        Stops when next non-empty column A appears.

        Args:
            flight_name: Name of the flight sheet
            client_code: Client code or list of codes to search for

        Returns:
            List of track codes. Empty list if not found or on error.
        """
        if isinstance(client_code, list):
            client_codes_upper_list = [c.strip().upper() for c in client_code if c]
        else:
            client_codes_upper_list = [client_code.strip().upper()]

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                url = self.single_values_url.format(range=f"{flight_name}!A:B")
                data = await self._fetch_json(session, url)
        except Exception:
            return []

        rows = data.get("values", [])
        if not rows:
            return []

        track_codes: List[str] = []
        found = False
        matched_code = ""

        for row in rows:
            a_col = self._clean_cell(row[0]) if len(row) > 0 else ""
            b_col = self._clean_cell(row[1]) if len(row) > 1 else ""

            if a_col.strip().upper() in client_codes_upper_list:
                found = True
                matched_code = a_col.strip().upper()
                if b_col:
                    track_codes.append(b_col)
                continue

            if found:
                if not a_col and b_col:
                    track_codes.append(b_col)
                elif a_col:
                    break

        return track_codes
