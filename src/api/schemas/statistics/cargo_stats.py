from pydantic import BaseModel, Field
from decimal import Decimal


class CargoVolumeStats(BaseModel):
    total_cargos: int = Field(
        ..., description="Jami kelgan yuklar (qutilar/mijoz paketlari) soni"
    )
    total_weight_kg: Decimal = Field(..., description="Jami kelgan yuklar vazni (kg)")
    avg_weight_per_client: Decimal = Field(
        ..., description="Bitta mijozga to'g'ri keladigan o'rtacha vazn (kg)"
    )
    avg_weight_per_track: Decimal = Field(
        ..., description="Bitta paket (trek) uchun o'rtacha vazn (kg)"
    )


class CargoBottleneckStats(BaseModel):
    china_unaccounted: int = Field(
        ..., description="Xitoyda bor, lekin O'zbekistonga hali kiritilmagan yuklar"
    )
    uz_pending_payment: int = Field(
        ...,
        description="O'zbekistonda bor, hisobot yuborilgan lekin to'lov qilinmagan (Kutib qolgan)",
    )
    uz_paid_not_taken: int = Field(
        ..., description="To'lovi qilingan, lekin ombordan olinmagan"
    )
    uz_taken_away: int = Field(
        ..., description="Mijozlar to'lab, o'zi olib ketgan yuklar"
    )
    post_approved: int = Field(
        ..., description="Pochtaga (Dostavka, UzPost, BTS) topshirilgan yuklar"
    )


class CargoSpeedStats(BaseModel):
    china_to_uz_days: Decimal = Field(
        ..., description="Xitoydan O'zbekistonga o'rtacha kelish vaqti (kunlarda)"
    )
    uz_warehouse_days: Decimal = Field(
        ...,
        description="O'zbekistonda yukni olib ketishgacha omborda turish vaqti (kunlarda)",
    )
    full_cycle_days: Decimal = Field(
        ...,
        description="Xitoydan to mijoz qo'liga tekkuncha umumiy aylanma tezlik (kunlarda)",
    )


class FlightVolumeItem(BaseModel):
    flight_name: str = Field(..., description="Reys nomi")
    cargo_count: int = Field(..., description="Shu reysdagi yuklar soni")
    total_weight_kg: Decimal = Field(..., description="Shu reysdagi jami vazn (kg)")


class TrackSearchTrendItem(BaseModel):
    period_name: str = Field(..., description="Sana (YYYY-MM-DD)")
    search_count: int = Field(..., description="Shu kunda track kod qidirishlar soni")


class CargoStatsResponse(BaseModel):
    volume: CargoVolumeStats = Field(
        ..., description="Asosiy yuk hajmi ko'rsatkichlari"
    )
    bottlenecks: CargoBottleneckStats = Field(
        ..., description="Muammoli nuqtalar va holatlar"
    )
    speed: CargoSpeedStats = Field(..., description="Yuklanish va aylanma tezliklari")
    top_flights: list[FlightVolumeItem] = Field(
        ..., description="Eng katta hajmli reyslar (Top 10)"
    )
    period_trends: list[TrackSearchTrendItem] = Field(
        ..., description="Kunlik track kod qidiruv statistikasi (trend grafik uchun)"
    )