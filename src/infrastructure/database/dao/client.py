from sqlalchemy import and_, select, or_, func, case, exists, text, Integer, cast
from sqlalchemy.ext.asyncio import AsyncSession
import re
from src.infrastructure.database.models.client import Client


class ClientDAO:
    @staticmethod
    async def get_by_id(session: AsyncSession, client_id: int) -> Client | None:
        """Get client by ID."""
        result = await session.execute(select(Client).where(Client.id == client_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_telegram_id(
        session: AsyncSession, telegram_id: int
    ) -> Client | None:
        result = await session.execute(
            select(Client).where(Client.telegram_id == telegram_id).limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_client_code(session: AsyncSession, client_code: str):
        clean_code = client_code.strip().upper()

        # Ustuvorlik (Priority) bo'yicha CASE mantiqi:
        # 1. extra_code (Yangi to'g'ri kodlar) - Eng yuqori ustuvorlik
        # 2. client_code (Asosiy kodlar)
        # 3. legacy_code (Eski xato kodlar) - Eng past ustuvorlik
        priority_case = case(
            (func.upper(Client.extra_code) == clean_code, 1),
            (func.upper(Client.client_code) == clean_code, 2),
            (func.upper(Client.legacy_code) == clean_code, 3),
            else_=4,
        )

        stmt = (
            select(Client)
            .where(
                or_(
                    func.upper(Client.client_code) == clean_code,
                    func.upper(Client.extra_code) == clean_code,
                    func.upper(Client.legacy_code) == clean_code,
                )
            )
            .order_by(priority_case)  # Ustuvorlik bo'yicha tartiblash
            .limit(1)  # Faqat bitta, eng to'g'ri natijani olish
        )

        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_extra_code(session: AsyncSession, extra_code: str):
        extra_code = extra_code.strip()
        result = await session.execute(
            select(Client)
            .where(func.trim(func.upper(Client.extra_code)) == func.upper(extra_code))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_phone(session: AsyncSession, phone: str) -> Client | None:
        """Get client by phone number."""
        result = await session.execute(
            select(Client).where(Client.phone == phone).limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_client_code_or_phone(
        session: AsyncSession, client_code: str | None = None, phone: str | None = None
    ) -> Client | None:
        """Get client by client_code OR phone number."""
        conditions = []
        if client_code:
            conditions.append(
                or_(Client.client_code == client_code, Client.extra_code == client_code)
            )
        if phone:
            conditions.append(Client.phone == phone)

        if not conditions:
            return None

        result = await session.execute(select(Client).where(or_(*conditions)).limit(1))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_client_code_and_phone(
        session: AsyncSession, client_code: str, phone: str
    ) -> Client | None:
        """
        Get client by client_code AND phone (handling format inconsistencies).

        Logic:
        1. Strips all non-digit characters from input phone.
        2. Extracts the last 9 digits (Uzbekistan standard core number).
        3. Checks DB for ANY valid variation: local (90...), with code (99890...), with plus (+99890...).
        """

        # 1. Client code ni tozalash
        code_clean = client_code.strip().upper()

        # 2. Telefondan faqat raqamlarni ajratib olish (probel, +, - larni olib tashlaydi)
        digits_only = re.sub(r"\D", "", phone)

        # 3. Asosiy 9 ta raqamni olish (agar raqam qisqa bo'lsa, borini oladi)
        # Masalan: 998901234567 -> 901234567
        core_phone = digits_only[-9:] if len(digits_only) >= 9 else digits_only

        if not core_phone:
            return None

        # 4. Bazada bo'lishi mumkin bo'lgan barcha formatlar ro'yxatini tuzamiz
        possible_formats = {
            core_phone,  # 901234567 (Lokal)
            f"998{core_phone}",  # 998901234567 (Kod bilan, plyussiz)
            f"+998{core_phone}",  # +998901234567 (To'liq xalqaro)
        }

        # 5. Bazadan qidirish (Client.phone ushbu variantlardan biriga teng bo'lsa)
        result = await session.execute(
            select(Client)
            .where(
                or_(Client.client_code == code_clean, Client.extra_code == code_clean),
                Client.phone.in_(possible_formats),
            )
            .limit(1)
        )

        return result.scalar_one_or_none()

    @staticmethod
    async def check_unique_fields(
        session: AsyncSession,
        telegram_id: int | None = None,
        phone: str | None = None,
        pinfl: str | None = None,
        passport_series: str | None = None,
    ) -> dict[str, bool]:
        """Check if unique fields already exist in database."""
        conflicts = {}

        if telegram_id:
            existing = await ClientDAO.get_by_telegram_id(session, telegram_id)
            conflicts["telegram_id"] = existing is not None

        if phone:
            existing = await ClientDAO.get_by_phone(session, phone)
            conflicts["phone"] = existing is not None

        if pinfl:
            result = await session.execute(
                select(Client).where(Client.pinfl == pinfl).limit(1)
            )
            conflicts["pinfl"] = result.first() is not None

        if passport_series:
            result = await session.execute(
                select(Client).where(Client.passport_series == passport_series).limit(1)
            )
            conflicts["passport_series"] = result.first() is not None

        return conflicts

    @staticmethod
    async def check_unique_fields_for_update(
        session: AsyncSession,
        exclude_client_id: int,
        phone: str | None = None,
        pinfl: str | None = None,
        passport_series: str | None = None,
    ) -> dict[str, bool]:
        """
        Update vaqtida unikal likni tekshirish.
        Joriy client_id (exclude_client_id) qidiruvdan chiqarib tashlanadi.
        """
        conflicts = {}

        if phone:
            # Telefon bor va ID bizniki EMAS
            query = (
                select(Client)
                .where(and_(Client.phone == phone, Client.id != exclude_client_id))
                .limit(1)
            )
            result = await session.execute(query)
            conflicts["phone"] = result.first() is not None

        if pinfl:
            query = (
                select(Client)
                .where(and_(Client.pinfl == pinfl, Client.id != exclude_client_id))
                .limit(1)
            )
            result = await session.execute(query)
            conflicts["pinfl"] = result.first() is not None

        if passport_series:
            query = (
                select(Client)
                .where(
                    and_(
                        Client.passport_series == passport_series,
                        Client.id != exclude_client_id,
                    )
                )
                .limit(1)
            )
            result = await session.execute(query)
            conflicts["passport_series"] = result.first() is not None

        return conflicts

    @staticmethod
    async def get_all(session: AsyncSession) -> list[Client]:
        # """
        # Vaqtinchalik: Faqat berilgan 153 ta xato kodga ega mijozlarni qaytaradi.
        # Filtr legacy_code ustuni bo'yicha ishlaydi.
        # """
        # # Siz tanlab bergan kodlar ro'yxati
        # target_legacy_codes = [
        #     "SVOC1", "SJFR1", "SSPD8", "SSPY3", "SBBS11", "SSSS24", "SVAG7", "SHHZ7", "SDKT5", "SSOQ2",
        #     "SAAN5", "SVOM9", "SHHZ2", "SFQV1", "SVCR2", "SHBG1", "SSSS23", "SVZG22", "SKNS1", "SFFS2",
        #     "SBBS1", "SDKO1", "SAAN2", "SHYA3", "SSJB5", "SDSH2", "SAAS5", "SABL6", "SABB3", "SBGJ2",
        #     "SRYR1", "SDQS10", "SRGS3", "SBBS13", "SVOM11", "SDDH1", "SAMR3", "SHXN1", "SNUQ4", "SDCH1",
        #     "SFFS11", "SVQB8", "SVOQ8", "SNUY3", "SVOH4", "SSSM2", "SVAG8", "SVQC5", "SKZR4", "SJJS11",
        #     "SVCR4", "SVZG28", "SXTS11", "SFFU2", "SVYS4", "SSPX3", "SQBR3", "SDKO2", "SNPP6", "SDQS3",
        #     "SAXJ1", "SNMB2", "SHXS3", "SAJL1", "SXBD1", "SAAK15", "SVOC4", "SJGL1", "SAOL2", "SJJZ2",
        #     "SRYR4", "SVBS1", "SFQQ3", "SDQS5", "SSSS25", "SHUS4", "SVCR6", "SNCH2", "SFRS4", "SAAS6",
        #     "SBBX4", "SFUK3", "SDCH5", "SAAK7", "SSTL4", "SNNR6", "SSIS2", "SFFS6", "SJJS13", "SRYR5",
        #     "SJZM4", "SHYB2", "SXTS12", "SABB4", "SVOM4", "SSPD9", "SVCR8", "SBRM1", "SFQS1", "SSJB9",
        #     "SVOA2", "SXQQ4", "SSUR4", "SVQB5", "SSPD4", "SBSF3", "SDKO4", "SSJB4", "SXQQ5", "SASH2",
        #     "SFBV2", "SSKS3", "SFFS13", "SKNS8", "SVQB6", "SNNS11", "SXUZ2", "SBBS15", "SAAN4", "SRGS4",
        #     "SJJS6", "SSOQ3", "SNNS12", "SXQZ1", "SHYA2", "SFRS3", "SNUQ2", "SDKT3", "SNNS6", "SHUS5",
        #     "SSPD6", "SJJS7", "SVYL7", "SNPP3", "SVYC5", "SNPP4", "SNPP5", "SVQC4", "SVYL11", "SKNS10",
        #     "SJBX2", "SSTL3", "SAAK14", "SRSR7", "SBBS9", "SFBD3", "SQEL2", "SSSM3", "SXTM1", "SJZF1",
        #     "SRSR8", "SBBS10", "SKZR3"
        # ]

        # # Qidiruvni osonlashtirish uchun hammasini katta harfga o'tkazib olamiz
        # target_legacy_codes = [code.upper() for code in target_legacy_codes]

        # result = await session.execute(
        #     select(Client)
        #     .where(
        #         # legacy_code ushbu ro'yxat ichida bo'lishi shart
        #         func.upper(Client.client_code).in_(target_legacy_codes)
        #     )
        #     .order_by(Client.created_at.desc())
        # )

        # return list(result.scalars().all())
        # # --- ASLIY KOD (COMMENT) ---
        result = await session.execute(
            select(Client)
            # .where(Client.telegram_id.isnot(None))
            .order_by(Client.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_client_codes(
        session: AsyncSession, client_codes: list[str]
    ) -> list[Client]:
        """
        Get clients by list of client codes.

        Args:
            session: Database session
            client_codes: List of client codes (e.g., ["ss501", "ss502", "ss503"])

        Returns:
            List of Client objects with telegram_id
        """
        if not client_codes:
            return []

        # Normalize client codes to lowercase for case-insensitive search
        normalized_codes = [code.strip().lower() for code in client_codes]

        result = await session.execute(
            select(Client)
            .where(
                func.lower(Client.client_code).in_(normalized_codes),
                Client.telegram_id.isnot(None),
            )
            .order_by(Client.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_clients_by_code_list(
        session: AsyncSession,
        codes: list[str],
    ) -> list[Client]:
        """
        Bulk-fetch Client rows for a list of raw cargo client codes.

        Unlike ``get_by_client_codes``, this method checks all three code
        columns (extra_code, client_code, legacy_code) so that aliases created
        by migration or data-correction workflows are resolved correctly.
        Clients without a telegram_id are included — callers must decide how
        to handle them (e.g. skip, log to fail channel).

        Args:
            session: Open async DB session.
            codes:   Raw client codes from flight_cargos.client_id.
                     Case is normalised internally.

        Returns:
            List of matching Client ORM objects (no guaranteed order).
        """
        if not codes:
            return []
        upper_codes = [c.strip().upper() for c in codes if c.strip()]
        if not upper_codes:
            return []
        result = await session.execute(
            select(Client).where(
                or_(
                    func.upper(Client.extra_code).in_(upper_codes),
                    func.upper(Client.client_code).in_(upper_codes),
                    func.upper(Client.legacy_code).in_(upper_codes),
                )
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_all(session: AsyncSession) -> int:
        """Count all clients with telegram_id."""
        result = await session.execute(
            select(func.count(Client.id))
            # .where(Client.telegram_id.isnot(None))
        )
        return result.scalar_one()

    @staticmethod
    async def create(session: AsyncSession, data: dict) -> Client:
        """Create a new client."""
        # Auto-generate client_code if not provided
        # if 'client_code' not in data or not data['client_code']:
        #     data['client_code'] = await ClientDAO.generate_unique_client_code(session)

        client = Client(**data)
        session.add(client)
        await session.flush()
        await session.refresh(client)
        return client

    @staticmethod
    async def update(session: AsyncSession, client: Client, data: dict) -> Client:
        """Update existing client."""
        for key, value in data.items():
            if hasattr(client, key):
                setattr(client, key, value)
        await session.flush()
        await session.refresh(client)
        return client

    @staticmethod
    async def delete(session: AsyncSession, client: Client) -> None:
        """Delete a client."""
        await session.delete(client)
        await session.flush()

    @staticmethod
    async def count_referrals(session: AsyncSession, referrer_telegram_id: int) -> int:
        """Count how many clients were referred by a specific user (by telegram_id)."""
        # Guard clause: prevent counting all NULL referrers when id is None
        if not referrer_telegram_id:
            return 0

        result = await session.execute(
            select(func.count(Client.id)).where(
                Client.referrer_telegram_id == referrer_telegram_id,
                Client.referrer_telegram_id.is_not(None),
            )
        )
        return result.scalar() or 0

    @staticmethod
    async def count_referrals_by_client_code(
        session: AsyncSession, client_code: str
    ) -> int:
        """Count how many clients were referred by a specific client (by client_code)."""
        # Guard clause: prevent query on empty/None client_code
        if not client_code:
            return 0

        # First, get the client to find their telegram_id
        client = await ClientDAO.get_by_client_code(session, client_code)
        if not client or not client.telegram_id:
            return 0
        # Count referrals using the referrer's telegram_id
        result = await session.execute(
            select(func.count(Client.id)).where(
                Client.referrer_telegram_id == client.telegram_id,
                Client.referrer_telegram_id.is_not(None),
            )
        )
        return result.scalar() or 0

    @staticmethod
    async def count_extra_passports(session: AsyncSession, telegram_id: int) -> int:
        """Count extra passports for a client (by telegram_id)."""
        from src.infrastructure.database.dao.client_extra_passport import (
            ClientExtraPassportDAO,
        )

        return await ClientExtraPassportDAO.count_by_telegram_id(session, telegram_id)

    @staticmethod
    async def count_extra_passports_by_client_code(
        session: AsyncSession, client_code: str
    ) -> int:
        """Count extra passports for a client (by client_code)."""
        from src.infrastructure.database.dao.client_extra_passport import (
            ClientExtraPassportDAO,
        )

        return await ClientExtraPassportDAO.count_by_client_code(session, client_code)

    @staticmethod
    async def search_by_phone(session: AsyncSession, phone: str) -> list[Client]:
        """
        Search clients by phone number (partial match).

        Normalizes phone number by removing spaces, dashes, and plus signs
        before searching.

        Args:
            session: Database session
            phone: Phone number to search for (can be partial)

        Returns:
            List of matching clients
        """
        # Normalize phone - remove non-digits
        normalized_phone = "".join(c for c in phone if c.isdigit())
        if not normalized_phone:
            return []

        # Search with LIKE for partial match
        result = await session.execute(
            select(Client)
            .where(
                func.regexp_replace(Client.phone, "\\D", "", "g").contains(
                    normalized_phone
                )
            )
            .order_by(Client.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def search_by_client_code_or_phone(
        session: AsyncSession, query: str
    ) -> Client | None:
        """
        Search for a client by client_code OR phone number.

        First tries exact match on client_code, then tries phone number match.

        Args:
            session: Database session
            query: Search query (could be client_code or phone number)

        Returns:
            Client if found, None otherwise
        """
        # Normalize query
        query = query.strip()

        # First try exact client_code match
        client = await ClientDAO.get_by_client_code(session, query.upper())
        if client:
            return client

        # Try exact extra_code match
        client = await ClientDAO.get_by_extra_code(session, query.upper())
        if client:
            return client

        # Try phone number search (normalize to digits only)
        normalized_phone = "".join(c for c in query if c.isdigit())
        if normalized_phone:
            # Try exact phone match first
            client = await ClientDAO.get_by_phone(session, query)
            if client:
                return client

            # Try partial phone match (last digits)
            result = await session.execute(
                select(Client)
                .where(
                    func.regexp_replace(Client.phone, "\\D", "", "g").endswith(
                        normalized_phone
                    )
                )
                .limit(1)
            )
            return result.scalar_one_or_none()

        return None

    @staticmethod
    async def search_clients_paginated(
        session: AsyncSession,
        page: int = 1,
        size: int = 20,
        # --- Targeted single-field filters (use only ONE at a time) ---
        code: str | None = None,
        phone: str | None = None,
        name: str | None = None,
        # --- Fallback: searches all fields at once (original behaviour) ---
        query: str | None = None,
    ) -> tuple[list["Client"], int]:
        """
        Paginated client search with two modes:

        **Targeted mode** — pass exactly one of ``code``, ``phone``, or ``name``
        to restrict the search to that single field.  This avoids false positives
        (e.g. a code like "ss511" accidentally matching an unrelated full_name).

        - ``code``  → ILIKE on extra_code / client_code / legacy_code (OR)
        - ``phone`` → digit-normalised containment on the phone column
        - ``name``  → ILIKE on full_name

        **General mode** — pass ``query`` to search across all fields at once
        (codes + name + phone) with OR logic.  Kept for backwards-compatibility
        and fast "I'll try everything" searches.

        Priority: targeted params take precedence over ``query`` when both are
        supplied.  If nothing is supplied, returns all clients (paginated).
        """
        condition = None

        if code is not None:
            q_upper = code.strip().upper()
            condition = or_(
                func.upper(Client.extra_code).ilike(f"%{q_upper}%"),
                func.upper(Client.client_code).ilike(f"%{q_upper}%"),
                func.upper(Client.legacy_code).ilike(f"%{q_upper}%"),
            )

        elif phone is not None:
            digits_only = "".join(c for c in phone if c.isdigit())
            if digits_only:
                condition = func.regexp_replace(Client.phone, r"\D", "", "g").contains(
                    digits_only
                )

        elif name is not None:
            condition = Client.full_name.ilike(f"%{name.strip()}%")

        elif query is not None:
            # General fallback: OR across all fields (original behaviour).
            q = query.strip()
            q_upper = q.upper()
            digits_only = "".join(c for c in q if c.isdigit())

            combined = or_(
                func.upper(Client.extra_code).ilike(f"%{q_upper}%"),
                func.upper(Client.client_code).ilike(f"%{q_upper}%"),
                func.upper(Client.legacy_code).ilike(f"%{q_upper}%"),
                Client.full_name.ilike(f"%{q}%"),
            )
            if digits_only:
                combined = or_(
                    combined,
                    func.regexp_replace(Client.phone, r"\D", "", "g").contains(
                        digits_only
                    ),
                )
            condition = combined

        count_stmt = select(func.count(Client.id))
        items_stmt = select(Client).order_by(Client.created_at.desc())

        if condition is not None:
            count_stmt = count_stmt.where(condition)
            items_stmt = items_stmt.where(condition)

        total: int = (await session.execute(count_stmt)).scalar_one()

        offset = (page - 1) * size
        clients = list(
            (await session.execute(items_stmt.limit(size).offset(offset)))
            .scalars()
            .all()
        )
        return clients, total
