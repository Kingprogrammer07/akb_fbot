from typing import List, Optional
from pydantic import BaseModel, Field


class PeriodicRevenue(BaseModel):
    period: str = Field(..., description="Sana yoki davr (masalan, '2023-10')")
    revenue: float = Field(0.0, description="Jami hisoblangan summa")
    paid: float = Field(0.0, description="Jami to'langan summa")
    debt: float = Field(0.0, description="Shu davrda yuzaga kelgan qarzdorlik")


class PaymentMethodStat(BaseModel):
    method: str = Field(..., description="To'lov usuli (online, cash, click, payme)")
    total_amount: float = Field(
        0.0, description="Ushbu usul orqali to'langan jami summa"
    )
    count: int = Field(0, description="To'lovlar soni")


class RegionStat(BaseModel):
    region_code: str = Field(
        ...,
        description="2-harfli viloyat/shahar kodi (ST, SV, SS, SA, ...)",
    )
    region_name: str = Field(..., description="Hudud nomi (O'zbek tilida, dekodlangan)")
    revenue: float = Field(0.0, description="Viloyat bo'yicha jami hisoblangan summa")
    paid: float = Field(0.0, description="Viloyat bo'yicha to'langan summa")
    debt: float = Field(0.0, description="Viloyat bo'yicha qarzdorlik")


class TopClientStat(BaseModel):
    client_code: str = Field(..., description="Mijoz kodi")
    revenue: float = Field(0.0, description="Mijozga hisoblangan jami summa")
    paid: float = Field(0.0, description="Mijoz to'lagan summa")
    debt: float = Field(0.0, description="Mijoz qarzdorligi")


class FlightCollectionStat(BaseModel):
    flight_name: str = Field(..., description="Reys nomi")
    revenue: float = Field(0.0, description="Reys bo'yicha jami hisoblangan summa")
    paid: float = Field(0.0, description="Reys bo'yicha to'langan summa")
    collection_rate: float = Field(
        0.0, description="Undirilish foizi (To'langan / Hisoblangan)"
    )


class FinancialStatsResponse(BaseModel):
    total_revenue: float = Field(0.0, description="Jami hisoblangan summa (brutto)")
    total_paid: float = Field(0.0, description="Jami to'langan summa")
    total_debt: float = Field(0.0, description="Jami qarzdorlik summasi")
    total_profitability: float = Field(
        0.0, description="Sof foyda: Jami to'langan - (Jami KG * $8 * kurs)"
    )
    overdue_debt: float = Field(0.0, description="15 kundan o'tgan qarzdorlik")
    average_payment: float = Field(0.0, description="O'rtacha to'lov summasi")

    periodic_revenue: List[PeriodicRevenue] = Field(default_factory=list)
    payment_methods: List[PaymentMethodStat] = Field(default_factory=list)
    regions: List[RegionStat] = Field(default_factory=list)
    top_clients: List[TopClientStat] = Field(default_factory=list)
    flight_collections: List[FlightCollectionStat] = Field(default_factory=list)