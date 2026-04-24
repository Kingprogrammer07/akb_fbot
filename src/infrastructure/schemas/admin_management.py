"""
Pydantic schemas for Super Admin Management APIs.

Covers: admin account CRUD, role/permission management, and audit log queries.
"""
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Home page path for a role — the frontend route the admin lands on after
# login.  We validate length and require a leading slash rather than keeping
# a Literal allowlist, so that new sections can be added to the frontend
# without requiring a schema migration.
# ---------------------------------------------------------------------------

ValidHomePage = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^/.*")]


# ---------------------------------------------------------------------------
# Client nested representation (minimal fields needed for admin panel)
# ---------------------------------------------------------------------------

class ClientBriefResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_id: int | None
    full_name: str
    phone: str | None
    username: str | None
    client_code: str | None


# ---------------------------------------------------------------------------
# Admin Accounts
# ---------------------------------------------------------------------------

class AdminAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    system_username: str
    is_active: bool
    failed_login_attempts: int
    role_id: int
    role_name: str
    client: ClientBriefResponse
    created_at: datetime


class CreateAdminAccountRequest(BaseModel):
    """Promote an existing Client to an admin account.

    The client is resolved by ``client_code`` (extra_code / client_code / legacy_code
    priority lookup). Telegram identity is derived automatically from the DB record
    — callers never need to supply it.

    The resulting AdminAccount authenticates entirely via system_username + PIN
    and does NOT require the linked Client to have a telegram_id.
    """

    client_code: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Client code (extra_code / client_code / legacy_code) to link",
    )
    role_id: int
    system_username: str = Field(..., min_length=3, max_length=64)
    pin: str = Field(..., min_length=4, max_length=64, description="Plain-text PIN — will be bcrypt-hashed")


class UpdateAdminAccountRequest(BaseModel):
    """Partial update for an admin account's mutable fields.

    All fields are optional — only the ones explicitly supplied will be changed.
    To reset a locked-out admin, set a new PIN (which also clears the lockout).
    """

    system_username: Annotated[str, Field(min_length=3, max_length=64)] | None = None
    pin: Annotated[str, Field(min_length=4, max_length=64)] | None = Field(
        None, description="New plain-text PIN — will be bcrypt-hashed"
    )
    role_id: int | None = None


class AdminAccountListResponse(BaseModel):
    """Paginated admin account list."""

    items: list[AdminAccountResponse]
    total_count: int
    total_pages: int
    page: int
    size: int


class UpdateAdminStatusRequest(BaseModel):
    is_active: bool


class ResetAdminPinRequest(BaseModel):
    """Request body for super-admin initiated PIN reset."""

    new_pin: str = Field(..., min_length=4, max_length=64, description="New plain-text PIN — will be bcrypt-hashed")


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource: str
    action: str


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    is_custom: bool
    home_page: ValidHomePage | None
    permissions: list[PermissionResponse]


class CreateRoleRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str | None = None
    home_page: ValidHomePage = "/admin"
    permission_ids: list[int] = Field(default_factory=list)


class UpdateRolePermissionsRequest(BaseModel):
    permission_ids: list[int]


# ---------------------------------------------------------------------------
# Audit Logs
# ---------------------------------------------------------------------------

class UpdateRoleRequest(BaseModel):
    """Partial update for role metadata. All fields are optional."""

    name: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = None
    home_page: ValidHomePage | None = None


# ---------------------------------------------------------------------------
# Audit Logs
# ---------------------------------------------------------------------------


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    admin_account_id: int | None
    role_snapshot: str | None
    actor_system_username: str | None
    actor_label: str | None
    action: str
    details: dict[str, Any] | None
    ip_address: str | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    """Paginated audit log list."""

    items: list[AuditLogResponse]
    total_count: int
    total_pages: int
    page: int
    size: int
