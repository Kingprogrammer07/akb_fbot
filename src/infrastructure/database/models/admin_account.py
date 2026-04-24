"""
AdminAccount SQLAlchemy model.

Represents the admin identity layer, linked 1-to-1 with a Client (which holds
the Telegram identity needed for security alerts).
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models.base import Base


class AdminAccount(Base):
    """
    Admin user credential and state record.

    Each admin must already exist as a `Client` (to have a Telegram account
    for security alerts). This model stores the admin-specific identity:
    their system login username, hashed PIN, role, and lockout state.
    """

    __tablename__ = "admin_accounts"

    # ── Relationships to existing tables ──────────────────────────────────

    # 1-to-1 link to clients table (the Telegram identity)
    client_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clients.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
        index=True,
    )

    # Role FK
    role_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # ── Auth credentials ───────────────────────────────────────────────────

    system_username: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="Username used for admin panel login (not Telegram username)",
    )

    pin_hash: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        comment="bcrypt hash of the 4-digit (or longer) PIN",
    )

    # ── Security / lockout state ───────────────────────────────────────────

    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="If set and in the future, logins are rejected until this time",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Soft-disable an admin account without deleting it",
    )

    # ── ORM relationships ──────────────────────────────────────────────────

    # The underlying Telegram client record (eager-loaded for alert sending)
    client: Mapped["Client"] = relationship(  # noqa: F821
        "Client",
        lazy="selectin",
        foreign_keys=[client_id],
    )

    role: Mapped["Role"] = relationship(  # noqa: F821
        "Role",
        back_populates="admin_accounts",
        lazy="selectin",  # always load role (needed for RBAC)
    )

    passkeys: Mapped[list["AdminPasskey"]] = relationship(  # noqa: F821
        "AdminPasskey",
        back_populates="admin_account",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    audit_logs: Mapped[list["AdminAuditLog"]] = relationship(  # noqa: F821
        "AdminAuditLog",
        back_populates="admin_account",
        cascade="save-update",
        lazy="noload",
    )

    # ── Convenience properties ─────────────────────────────────────────────

    @property
    def role_name(self) -> str:
        """Safe shortcut – Role is always eager-loaded."""
        return self.role.name if self.role else ""

    @property
    def telegram_id(self) -> int | None:
        """Shortcut to the linked client's Telegram ID (for alerts)."""
        return self.client.telegram_id if self.client else None

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AdminAccount username={self.system_username!r} "
            f"role={self.role_name!r} active={self.is_active}>"
        )
