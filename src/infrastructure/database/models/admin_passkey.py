"""
AdminPasskey SQLAlchemy model.

Stores WebAuthn credential data for passkey (FaceID/TouchID) login.
Each admin account may have multiple registered passkeys (one per device).
"""
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models.base import Base


class AdminPasskey(Base):
    """Registered WebAuthn credential for an admin account."""

    __tablename__ = "admin_passkeys"

    admin_account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # WebAuthn credential identifier (base64url-encoded, globally unique)
    credential_id: Mapped[str] = mapped_column(
        String(512), unique=True, nullable=False, index=True
    )

    # COSE-encoded public key (base64url or raw bytes stored as text)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)

    # Monotonically increasing counter to detect cloned authenticators
    sign_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Human-readable label (e.g. "iPhone 15 Pro Face ID")
    device_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # ── Relationships ──────────────────────────────────────────────────────

    admin_account: Mapped["AdminAccount"] = relationship(  # noqa: F821
        "AdminAccount",
        back_populates="passkeys",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AdminPasskey admin={self.admin_account_id} device={self.device_name!r}>"
