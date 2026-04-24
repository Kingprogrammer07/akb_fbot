"""Delivery Request model."""
from sqlalchemy import String, DateTime, Text, Boolean, BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base
from src.infrastructure.tools.datetime_utils import get_current_time


class DeliveryRequest(Base):
    __tablename__ = "delivery_requests"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Client info
    client_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    client_code: Mapped[str] = mapped_column(String(10), nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # Delivery details
    delivery_type: Mapped[str] = mapped_column(String(20), nullable=False)  # uzpost, yandex, akb, bts
    flight_names: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of flight names

    # Client details at time of request
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    region: Mapped[str] = mapped_column(String(128), nullable=False)
    address: Mapped[str] = mapped_column(String(512), nullable=False)

    # UZPOST prepayment (optional, only for UZPOST)
    prepayment_receipt_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending, approved, rejected
    admin_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Admin who processed
    processed_by_admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    processed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), default=get_current_time
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, onupdate=get_current_time
    )
