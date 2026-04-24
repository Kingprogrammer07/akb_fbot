"""
Role & Permission SQLAlchemy models.

Tables:
    roles           — named roles (e.g. 'super-admin', 'accountant')
    permissions     — discrete resource+action pairs (e.g. finance:read)
    role_permissions — M2M association between roles and permissions
"""
from sqlalchemy import (
    Boolean,
    ForeignKey,
    String,
    Table,
    Text,
    UniqueConstraint,
    Column,
    Integer,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models.base import Base


# ---------------------------------------------------------------------------
# Association table  (no ORM class — plain Table object)
# ---------------------------------------------------------------------------

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "role_id",
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        Integer,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


# ---------------------------------------------------------------------------
# Permission
# ---------------------------------------------------------------------------

class Permission(Base):
    """A single atomic permission: resource + action."""

    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("resource", "action", name="uq_permission_resource_action"),
    )

    # Override base `id` to keep it cleaner (Base already defined id)
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)

    # Back-populated by Role.permissions
    roles: Mapped[list["Role"]] = relationship(
        "Role",
        secondary=role_permissions,
        back_populates="permissions",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Permission {self.resource}:{self.action}>"

    @property
    def slug(self) -> str:
        """'finance:read' — used for Redis set membership checks."""
        return f"{self.resource}:{self.action}"


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------

class Role(Base):
    """A named role that groups permissions."""

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    home_page: Mapped[str | None] = mapped_column(String(255), nullable=True, default="/admin")

    # Many-to-many relationship with permissions
    permissions: Mapped[list[Permission]] = relationship(
        "Permission",
        secondary=role_permissions,
        back_populates="roles",
        lazy="selectin",  # auto-loaded — needed for RBAC checks
    )

    # One-to-many relationship with admin accounts
    admin_accounts: Mapped[list["AdminAccount"]] = relationship(  # noqa: F821
        "AdminAccount",
        back_populates="role",
        lazy="noload",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Role {self.name!r}>"
