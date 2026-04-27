from datetime import date
from sqlalchemy import String, DateTime, Date, Text, Boolean, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import Base
from src.infrastructure.tools.datetime_utils import get_current_time


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=True
    )

    full_name: Mapped[str] = mapped_column(String(256))
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    language_code: Mapped[str] = mapped_column(String(5), default="uz", nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=True)

    passport_series: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pinfl: Mapped[str | None] = mapped_column(String(14), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    district: Mapped[str | None] = mapped_column(String(128), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Stores Telegram file_id(s) - single string or JSON array
    passport_images: Mapped[str | None] = mapped_column(Text, nullable=True)

    client_code: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True
    )
    extra_code: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True
    )

    legacy_code: Mapped[str | None] = mapped_column(
        String(10), unique=True, nullable=True
    )

    username: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Telegram username (without @)"
    )

    # Referral system
    referrer_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    referrer_client_code: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Login status
    is_logged_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Tracks last bot interaction — updated by LastSeenMiddleware on every update
    last_seen_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), default=get_current_time
    )

    @property
    def active_codes(self) -> list[str]:
        """Returns a list of all valid codes for this client."""
        codes = []
        if self.extra_code:
            codes.append(self.extra_code.upper())
        if self.client_code:
            codes.append(self.client_code.upper())
        if self.legacy_code:
            codes.append(self.legacy_code.upper())
        return list(dict.fromkeys(codes))

    @property
    def primary_code(self) -> str:
        """Returns the single highest-priority code for string formatting (Redis, S3)."""
        return (
            self.extra_code
            or self.client_code
            or self.legacy_code
            or str(self.telegram_id)
        )

    @property
    def payment_code(self) -> str:
        """
        Returns the canonical code for transaction writes (NEVER legacy_code).
        Used to prevent duplicate transactions under different aliases.
        """
        if self.extra_code:
            return self.extra_code.upper()
        if self.client_code:
            return self.client_code.upper()
        return self.legacy_code.upper() if self.legacy_code else str(self.telegram_id)
