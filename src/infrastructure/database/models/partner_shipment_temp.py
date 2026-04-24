from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from src.infrastructure.database.models.base import Base
from src.infrastructure.tools.datetime_utils import get_current_time


class PartnerShipmentTemp(Base):
    __tablename__ = "partner_shipments_temp"

    id: Mapped[int] = mapped_column(primary_key=True)
    track_code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    client_code: Mapped[str] = mapped_column(String(50), index=True)
    flight_name: Mapped[str] = mapped_column(String(50), index=True)
    received_date: Mapped[str] = mapped_column(String(50))
    weight_kg: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[str] = mapped_column(String(20))

    item_name_ru: Mapped[str | None] = mapped_column(String(200), nullable=True)
    item_name_cn: Mapped[str | None] = mapped_column(String(200), nullable=True)
    box_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    photo_s3_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time
    )
