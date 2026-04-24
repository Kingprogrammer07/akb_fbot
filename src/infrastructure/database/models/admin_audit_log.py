"""
AdminAuditLog SQLAlchemy model.

Immutable security audit trail for all admin actions.
Intentionally does NOT use the Base class (no updated_at — logs never change).
"""
from typing import Any

from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models.base import Base


class AdminAuditLog(Base):
    """
    Immutable record of admin actions and security events.

    Uses Base for consistency (created_at from Base is kept, updated_at is
    irrelevant but harmless for an append-only table).

    Common `action` values:
        LOGIN_SUCCESS, LOGIN_FAILED, LOCKED_OUT,
        PASSKEY_REGISTERED, PASSKEY_LOGIN,
        LOGOUT, PERMISSION_DENIED
    """

    __tablename__ = "admin_audit_logs"

    # Nullable FK — preserved even if admin account is deleted (SET NULL)
    admin_account_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Snapshot of the admin's role name at the time of the action (historical context)
    role_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    actor_system_username: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Immutable snapshot of the acting admin's system username",
    )

    # Arbitrary structured payload (e.g. {"reason": "wrong_pin", "attempt": 3})
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)   # IPv4 or IPv6
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ── Relationships ──────────────────────────────────────────────────────

    admin_account: Mapped["AdminAccount | None"] = relationship(  # noqa: F821
        "AdminAccount",
        back_populates="audit_logs",
        lazy="noload",
    )

    @property
    def actor_label(self) -> str | None:
        """Render a stable actor label for audit-log responses."""
        username = self.actor_system_username
        if not username and getattr(self, "admin_account", None):
            username = self.admin_account.system_username

        if username and self.admin_account_id is not None:
            return f"{username} (ID: {self.admin_account_id})"
        if username:
            return username
        if self.admin_account_id is not None:
            return f"ID: {self.admin_account_id}"
        return None

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AdminAuditLog action={self.action!r} "
            f"admin={self.admin_account_id} at={self.created_at}>"
        )
