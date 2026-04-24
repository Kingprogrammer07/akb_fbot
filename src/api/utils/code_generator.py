from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.utils.constants import AVIA_CODES



async def generate_client_code(session: AsyncSession, region: str, district: str) -> str:
    safe_district = str(district).strip().lower() if district else ""
    
    # 1. Prefiksni aniqlash
    assigned_prefix = AVIA_CODES.get(safe_district)
    if not assigned_prefix and safe_district.upper() in AVIA_CODES.values():
        assigned_prefix = safe_district.upper()
    if not assigned_prefix:
        assigned_prefix = "NON"  # Belgilangan prefiks topilmasa, umumiy prefiks
        
    # 2. LOGIKA: Toshkent (1 dan) vs Viloyatlar (30 dan)
    if assigned_prefix.startswith("ST"):
        start_number = 1
        # Toshkent uchun qidiruv faqat shu tuman prefiksi bilan cheklanadi
        regex_pattern = f"^{assigned_prefix}[0-9]+$"
    else:
        # Boshqa viloyatlar uchun 30 dan boshlanadi
        start_number = 30
        region_base = assigned_prefix[:2]
        # Butun viloyatdagi (SA, SF, SS...) barcha raqamlarni birga ko'radi
        regex_pattern = f"^{region_base}[A-Z]*[0-9]+$"

    # PostgreSQL uchun LOCK orqali race condition oldini olish
    await session.execute(text("LOCK TABLE clients IN SHARE ROW EXCLUSIVE MODE"))

    params = {
        "start": start_number,
        "regex_pattern": regex_pattern
    }

    # 3. SQL so'rovi: Bo'shliqlarni to'ldirish (Gap filling)
    # SUBSTRING(... FROM '[0-9]+') raqamni aniq sug'urib oladi
    query = text("""
    WITH target_codes AS (
        SELECT client_code AS code FROM clients WHERE client_code IS NOT NULL
        UNION ALL
        SELECT extra_code AS code FROM clients WHERE extra_code IS NOT NULL
    ),
    nums AS (
        SELECT CAST(SUBSTRING(UPPER(code) FROM '[0-9]+') AS INT) AS num
        FROM target_codes
        WHERE UPPER(code) ~ :regex_pattern
    )
    SELECT COALESCE(
        -- 1. Eng kichik bo'shliqni qidiramiz (start_number dan yuqorida)
        (SELECT n.num + 1 
         FROM nums n 
         LEFT JOIN nums n2 ON n.num + 1 = n2.num 
         WHERE n.num >= :start AND n2.num IS NULL 
         ORDER BY n.num LIMIT 1),
         
        -- 2. Agar hali start_number gacha birorta kod bo'lmasa, start_number'ni o'zini beradi
        (SELECT CASE 
            WHEN NOT EXISTS (SELECT 1 FROM nums WHERE num >= :start) THEN :start
            ELSE MAX(num) + 1 
         END FROM nums)
    )
    """)

    result = await session.execute(query, params)
    generated_num = result.scalar_one()
    
    # Mabodo nums bo'm-bo'sh bo'lsa COALESCE ichidagi ikkinchi SELECT start_number'ni beradi.
    if generated_num is None:
        generated_num = start_number

    return f"{assigned_prefix}{generated_num}"