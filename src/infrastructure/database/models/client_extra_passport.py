"""Client extra passports model."""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, String, Date, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base
from src.infrastructure.tools.datetime_utils import get_current_time


class ClientExtraPassport(Base):
    """Client extra passports model for storing additional passport documents."""

    __tablename__ = "client_extra_passports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    client_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)
    passport_series: Mapped[str] = mapped_column(String(10), nullable=False)
    pinfl: Mapped[str] = mapped_column(String(14), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    passport_images: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of file_ids
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, onupdate=get_current_time, nullable=False
    )

    def __repr__(self) -> str:
        return f"<ClientExtraPassport(id={self.id}, telegram_id={self.telegram_id}, passport_series={self.passport_series})>"
