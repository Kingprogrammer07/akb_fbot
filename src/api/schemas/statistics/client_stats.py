from datetime import date
from pydantic import BaseModel, Field


class OverviewStats(BaseModel):
    total_clients: int = Field(..., description="Jami mijozlar soni")
    new_clients: int = Field(..., description="Yangi ro'yxatdan o'tgan mijozlar")
    active_clients: int = Field(..., description="Aktiv mijozlar")
    passive_clients: int = Field(..., description="Passiv bo'lib qolgan mijozlar")
    zombie_clients: int = Field(
        ..., description="Zombi mijozlar (hech qachon yuk buyurtma qilmagan)"
    )
    logged_in_clients: int = Field(
        ..., description="Hozirda tizimga kirgan (is_logged_in=True) mijozlar soni"
    )


class RetentionStats(BaseModel):
    repeat_clients: int = Field(..., description="Qayta buyurtma qilgan mijozlar")
    one_time_clients: int = Field(..., description="Bir marta ishlatib ketgan mijozlar")
    most_frequent_clients: int = Field(
        ...,
        description="Eng ko'p buyurtma beradigan mijozlar (5+ reys)",
    )


class DistrictDetail(BaseModel):
    """Tuman/shahar darajasidagi ko'rsatkichlar."""
    code: str = Field(..., description="4-harfli AVIA kod, masalan STCH")
    count: int = Field(..., description="Shu tumandagi mijozlar soni")
    revenue: float = Field(0.0, description="Jami hisoblangan summa (so'm)")
    paid: float = Field(0.0, description="Jami to'langan summa (so'm)")
    debt: float = Field(0.0, description="Jami qarzdorlik (so'm)")


class RegionDetail(BaseModel):
    """Viloyat/shahar darajasidagi ko'rsatkichlar (tumanlar bilan birga)."""
    code: str = Field(..., description="2-harfli AVIA kod, masalan ST")
    count: int = Field(..., description="Hududdagi jami mijozlar soni")
    revenue: float = Field(0.0, description="Jami hisoblangan summa (so'm)")
    paid: float = Field(0.0, description="Jami to'langan summa (so'm)")
    debt: float = Field(0.0, description="Jami qarzdorlik (so'm)")
    districts: dict[str, DistrictDetail] = Field(
        default_factory=dict,
        description="Tuman nomi → ko'rsatkichlar (revenue bo'yicha kamayib tartiblangan)",
    )


class DeliveryStatItem(BaseModel):
    method: str = Field(
        ...,
        description="Yetkazib berish usuli (Masalan: O'zi olib ketish, Dostavka, Pochta)",
    )
    count: int = Field(..., description="Buyurtmalar soni")


class ClientStatsResponse(BaseModel):
    overview: OverviewStats = Field(..., description="Umumiy ko'rsatkichlar")
    retention: RetentionStats = Field(
        ..., description="Mijozlarni saqlab qolish (Retention) ko'rsatkichlari"
    )
    regions: dict[str, RegionDetail] = Field(
        ...,
        description=(
            "Hudud nomi → ko'rsatkichlar. "
            "Har bir region ichida districts (tuman nomi → ko'rsatkichlar). "
            "Revenue bo'yicha kamayib tartiblangan."
        ),
    )
    delivery_methods: list[DeliveryStatItem] = Field(
        ..., description="Yetkazib berish usullari bo'yicha"
    )
