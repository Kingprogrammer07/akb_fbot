"""
Super Admin Management Router.

Prefix  : /admin/manage
Tags    : ["Super Admin Management"]

All endpoints require a valid Admin JWT (X-Admin-Authorization: Bearer <token>)
and the specific RBAC permission enforced per route.
"""
import math

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.api.dependencies import (
    AdminJWTPayload,
    get_db,
    get_redis,
    require_permission,
)
from src.api.utils.security import hash_pin
from src.infrastructure.database.dao.admin_account import AdminAccountDAO
from src.infrastructure.database.dao.admin_audit_log import AdminAuditLogDAO
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.dao.permission import PermissionDAO
from src.infrastructure.database.dao.role import RoleDAO
from src.infrastructure.schemas.admin_management import (
    AdminAccountListResponse,
    AdminAccountResponse,
    AuditLogListResponse,
    AuditLogResponse,
    CreateAdminAccountRequest,
    CreateRoleRequest,
    PermissionResponse,
    ResetAdminPinRequest,
    RoleResponse,
    UpdateAdminAccountRequest,
    UpdateAdminStatusRequest,
    UpdateRolePermissionsRequest,
    UpdateRoleRequest,
)
from src.infrastructure.services.admin_rbac_service import RBACService

router = APIRouter(prefix="/admin/manage", tags=["Super Admin Management"])


# ---------------------------------------------------------------------------
# Helper: build role_snapshot from JWT payload
# ---------------------------------------------------------------------------

def _role_snapshot(admin: AdminJWTPayload) -> str:
    return admin.role_name


# ===========================================================================
# 1.  Admin Accounts Management
# ===========================================================================

@router.get(
    "/admin-accounts",
    response_model=AdminAccountListResponse,
    summary="List admin accounts (paginated)",
)
async def list_admin_accounts(
    role_id: int | None = Query(None, description="Filter by role ID"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    admin: AdminJWTPayload = Depends(require_permission("admin_accounts", "read")),
    session: AsyncSession = Depends(get_db),
) -> AdminAccountListResponse:
    total_count = await AdminAccountDAO.count_admins(
        session, role_id=role_id, is_active=is_active
    )
    accounts = await AdminAccountDAO.get_all_admins(
        session,
        skip=(page - 1) * size,
        limit=size,
        role_id=role_id,
        is_active=is_active,
    )
    return AdminAccountListResponse(
        items=[AdminAccountResponse.model_validate(a) for a in accounts],
        total_count=total_count,
        total_pages=math.ceil(total_count / size) if total_count else 0,
        page=page,
        size=size,
    )


@router.post(
    "/admin-accounts",
    response_model=AdminAccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create admin account",
)
async def create_admin_account(
    body: CreateAdminAccountRequest,
    admin: AdminJWTPayload = Depends(require_permission("admin_accounts", "create")),
    session: AsyncSession = Depends(get_db),
) -> AdminAccountResponse:
    """
    Promote an existing Client to an admin account.

    The client is resolved by ``client_code`` using priority lookup
    (extra_code → client_code → legacy_code).  Telegram identity is derived
    automatically — callers never need to supply it.
    """
    client = await ClientDAO.get_by_client_code(session, body.client_code)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{body.client_code}' kodli mijoz topilmadi.",
        )

    role = await RoleDAO.get_by_id(session, body.role_id)
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rol topilmadi.")

    # Guard against promoting a client who already has an admin account.
    existing_account = await AdminAccountDAO.get_by_client_id(session, client.id)
    if existing_account:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{body.client_code}' kodli mijoz allaqachon admin hisobiga ega.",
        )

    pin_hash = hash_pin(body.pin)

    try:
        account = await AdminAccountDAO.create_admin(
            session=session,
            client_id=client.id,
            role_id=body.role_id,
            system_username=body.system_username,
            pin_hash=pin_hash,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    await AdminAuditLogDAO.log(
        session=session,
        action="CREATED_ADMIN",
        admin_id=admin.admin_id,
        role_snapshot=_role_snapshot(admin),
        details={
            "new_admin_id": account.id,
            "new_admin_username": account.system_username,
            "client_code": body.client_code,
            "role_id": body.role_id,
        },
    )
    await session.commit()
    refreshed = await AdminAccountDAO.get_by_id_with_relations(session, account.id)
    return AdminAccountResponse.model_validate(refreshed)


@router.get(
    "/admin-accounts/{admin_account_id}",
    response_model=AdminAccountResponse,
    summary="Get a single admin account by ID",
)
async def get_admin_account(
    admin_account_id: int,
    admin: AdminJWTPayload = Depends(require_permission("admin_accounts", "read")),
    session: AsyncSession = Depends(get_db),
) -> AdminAccountResponse:
    target = await AdminAccountDAO.get_by_id_with_relations(session, admin_account_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin hisob topilmadi.")
    return AdminAccountResponse.model_validate(target)


@router.patch(
    "/admin-accounts/{admin_account_id}/status",
    response_model=AdminAccountResponse,
    summary="Activate or deactivate an admin account",
)
async def update_admin_status(
    admin_account_id: int,
    body: UpdateAdminStatusRequest,
    admin: AdminJWTPayload = Depends(require_permission("admin_accounts", "update")),
    session: AsyncSession = Depends(get_db),
) -> AdminAccountResponse:
    target = await AdminAccountDAO.get_by_id_with_relations(session, admin_account_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin hisob topilmadi.")

    target.is_active = body.is_active
    await session.flush()

    await AdminAuditLogDAO.log(
        session=session,
        action="UPDATED_ADMIN_STATUS",
        admin_id=admin.admin_id,
        role_snapshot=_role_snapshot(admin),
        details={
            "target_admin_id": target.id,
            "target_username": target.system_username,
            "is_active": body.is_active,
        },
    )
    await session.commit()
    await session.refresh(target)
    return AdminAccountResponse.model_validate(target)


@router.patch(
    "/admin-accounts/{admin_account_id}",
    response_model=AdminAccountResponse,
    summary="Update admin account (username, PIN, or role)",
)
async def update_admin_account(
    admin_account_id: int,
    body: UpdateAdminAccountRequest,
    admin: AdminJWTPayload = Depends(require_permission("admin_accounts", "update")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> AdminAccountResponse:
    """
    Partially update an admin's mutable fields.

    - ``system_username``: checked for uniqueness before applying.
    - ``pin``: hashed with bcrypt; also resets failed-login counter and lockout.
    - ``role_id``: verified to exist; RBAC cache for the old role is invalidated
      so the admin gets fresh permissions on their next request.
    """
    if not body.model_dump(exclude_none=True):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Yangilash uchun kamida bitta maydon yuborilishi shart.",
        )

    target = await AdminAccountDAO.get_by_id_with_relations(session, admin_account_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin hisob topilmadi.")

    changes: dict = {}

    if body.system_username is not None and body.system_username != target.system_username:
        conflict = await AdminAccountDAO.get_by_username(session, body.system_username)
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"'{body.system_username}' foydalanuvchi nomi allaqachon band.",
            )
        target.system_username = body.system_username
        changes["system_username"] = body.system_username

    if body.pin is not None:
        # update_pin_and_unlock also resets failed_login_attempts and locked_until.
        await AdminAccountDAO.update_pin_and_unlock(session, admin_account_id, hash_pin(body.pin))
        changes["pin"] = "***"

    old_role_name: str | None = None
    if body.role_id is not None and body.role_id != target.role_id:
        new_role = await RoleDAO.get_by_id(session, body.role_id)
        if not new_role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rol topilmadi.")
        old_role_name = target.role.name if target.role else None
        target.role_id = body.role_id
        changes["role_id"] = body.role_id

    await AdminAuditLogDAO.log(
        session=session,
        action="UPDATED_ADMIN",
        admin_id=admin.admin_id,
        role_snapshot=_role_snapshot(admin),
        details={"target_admin_id": admin_account_id, "changes": changes},
    )
    await session.commit()

    # Invalidate RBAC cache for the previous role so stale permissions expire.
    if old_role_name:
        await RBACService.invalidate_role(redis, old_role_name)

    refreshed = await AdminAccountDAO.get_by_id_with_relations(session, admin_account_id)
    return AdminAccountResponse.model_validate(refreshed)


@router.delete(
    "/admin-accounts/{admin_account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete an admin account",
)
async def delete_admin_account(
    admin_account_id: int,
    admin: AdminJWTPayload = Depends(require_permission("admin_accounts", "delete")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> None:
    """
    Permanently remove an admin account.

    Safety constraints:
    - An admin cannot delete their own account.
    - The underlying Client record is never touched — only the AdminAccount row.
    - The RBAC Redis cache for the deleted admin's role is invalidated immediately.
    """
    if admin_account_id == admin.admin_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O'z admin hisobingizni o'chira olmaysiz.",
        )

    target = await AdminAccountDAO.get_by_id_with_relations(session, admin_account_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin hisob topilmadi.")

    role_name_for_cache = target.role.name if target.role else None
    deleted_username = target.system_username

    await session.delete(target)

    await AdminAuditLogDAO.log(
        session=session,
        action="DELETED_ADMIN",
        admin_id=admin.admin_id,
        role_snapshot=_role_snapshot(admin),
        details={
            "deleted_admin_id": admin_account_id,
            "deleted_username": deleted_username,
        },
    )
    await session.commit()

    if role_name_for_cache:
        await RBACService.invalidate_role(redis, role_name_for_cache)


# ===========================================================================
# 2.  Roles & Permissions Management
# ===========================================================================

@router.get(
    "/system-permissions",
    response_model=list[PermissionResponse],
    summary="List all available permissions",
)
async def list_permissions(
    admin: AdminJWTPayload = Depends(require_permission("roles", "read")),
    session: AsyncSession = Depends(get_db),
) -> list[PermissionResponse]:
    perms = await PermissionDAO.get_all_permissions(session)
    return [PermissionResponse.model_validate(p) for p in perms]


@router.get(
    "/system-roles",
    response_model=list[RoleResponse],
    summary="List all roles with their permissions",
)
async def list_roles(
    admin: AdminJWTPayload = Depends(require_permission("roles", "read")),
    session: AsyncSession = Depends(get_db),
) -> list[RoleResponse]:
    roles = await RoleDAO.get_all_roles(session)
    return [RoleResponse.model_validate(r) for r in roles]


@router.post(
    "/system-roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new custom role with permissions",
)
async def create_role(
    body: CreateRoleRequest,
    admin: AdminJWTPayload = Depends(require_permission("roles", "create")),
    session: AsyncSession = Depends(get_db),
) -> RoleResponse:
    # Reject duplicate names early with a clear error
    existing = await RoleDAO.get_by_name(session, body.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{body.name}' nomli rol allaqachon mavjud",
        )

    role = await RoleDAO.create_role(session, name=body.name, description=body.description, home_page=body.home_page)

    # Attach permissions if provided
    if body.permission_ids:
        role = await RoleDAO.update_role_permissions(session, role.id, body.permission_ids)

    await AdminAuditLogDAO.log(
        session=session,
        action="CREATED_ROLE",
        admin_id=admin.admin_id,
        role_snapshot=_role_snapshot(admin),
        details={"role_id": role.id, "role_name": role.name, "permission_ids": body.permission_ids},
    )
    await session.commit()
    await session.refresh(role)
    return RoleResponse.model_validate(role)


@router.put(
    "/system-roles/{role_id}/permissions",
    response_model=RoleResponse,
    summary="Replace permissions for a role (invalidates RBAC cache)",
)
async def update_role_permissions(
    role_id: int,
    body: UpdateRolePermissionsRequest,
    admin: AdminJWTPayload = Depends(require_permission("roles", "update")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> RoleResponse:
    role = await RoleDAO.update_role_permissions(session, role_id, body.permission_ids)
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rol topilmadi")
    print(body.model_dump())
    await AdminAuditLogDAO.log(
        session=session,
        action="UPDATED_ROLE_PERMISSIONS",
        admin_id=admin.admin_id,
        role_snapshot=_role_snapshot(admin),
        details={"role_id": role.id, "role_name": role.name, "permission_ids": body.permission_ids},
    )
    await session.commit()

    # Invalidate RBAC Redis cache so the new permissions take effect immediately
    await RBACService.invalidate_role(redis, role.name)

    await session.refresh(role)
    return RoleResponse.model_validate(role)


@router.delete(
    "/system-roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom role (blocked if system role or active admins assigned)",
)
async def delete_role(
    role_id: int,
    admin: AdminJWTPayload = Depends(require_permission("roles", "delete")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> None:
    """
    Permanently delete a custom role.

    Safety constraints enforced:
    - The role must have ``is_custom=True``; built-in system roles are immutable.
    - No active admin accounts may be assigned to the role at deletion time.

    On success the RBAC Redis cache for this role is invalidated immediately so
    that any in-flight permission checks do not continue to reference stale data.
    """
    try:
        deleted_role = await RoleDAO.delete_role(session, role_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    if not deleted_role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    role_name_for_cache = deleted_role.name

    await AdminAuditLogDAO.log(
        session=session,
        action="DELETED_ROLE",
        admin_id=admin.admin_id,
        role_snapshot=_role_snapshot(admin),
        details={"deleted_role_id": role_id, "deleted_role_name": role_name_for_cache},
    )
    await session.commit()

    # Flush the RBAC permission cache for the now-deleted role so that any
    # concurrent JWT holders referencing it find no permissions on next check.
    await RBACService.invalidate_role(redis, role_name_for_cache)


# ===========================================================================
# 3.  Audit Logs
# ===========================================================================

@router.get(
    "/system-audit-logs",
    response_model=AuditLogListResponse,
    summary="List system audit logs with optional filters (paginated)",
)
async def list_audit_logs(
    admin_account_id: int | None = Query(None, description="Filter by admin account ID"),
    role_snapshot: str | None = Query(None, description="Filter by role name at time of action"),
    action: str | None = Query(None, description="Filter by action name (e.g. LOGIN_SUCCESS)"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    admin: AdminJWTPayload = Depends(require_permission("audit_logs", "read")),
    session: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    total_count = await AdminAuditLogDAO.count_logs(
        session,
        admin_id=admin_account_id,
        role_snapshot=role_snapshot,
        action=action,
    )
    logs = await AdminAuditLogDAO.get_logs(
        session,
        skip=(page - 1) * size,
        limit=size,
        admin_id=admin_account_id,
        role_snapshot=role_snapshot,
        action=action,
    )
    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        total_count=total_count,
        total_pages=math.ceil(total_count / size) if total_count else 0,
        page=page,
        size=size,
    )


@router.get(
    "/admin-accounts/{admin_account_id}/audit-logs",
    response_model=AuditLogListResponse,
    summary="Audit log history for a specific admin (paginated)",
)
async def get_admin_audit_logs(
    admin_account_id: int,
    action: str | None = Query(None, description="Filter by action name (e.g. LOGIN_SUCCESS)"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    admin: AdminJWTPayload = Depends(require_permission("audit_logs", "read")),
    session: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    """Return the full action history for one admin, newest first."""
    target = await AdminAccountDAO.get_by_id_with_relations(session, admin_account_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin hisob topilmadi.")

    total_count = await AdminAuditLogDAO.count_logs(
        session, admin_id=admin_account_id, action=action
    )
    logs = await AdminAuditLogDAO.get_logs(
        session,
        skip=(page - 1) * size,
        limit=size,
        admin_id=admin_account_id,
        action=action,
    )
    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        total_count=total_count,
        total_pages=math.ceil(total_count / size) if total_count else 0,
        page=page,
        size=size,
    )


@router.post(
    "/admin-accounts/{admin_account_id}/reset-pin",
    response_model=AdminAccountResponse,
    summary="Reset an admin's PIN (also clears lockout)",
)
async def reset_admin_pin(
    admin_account_id: int,
    body: ResetAdminPinRequest,
    admin: AdminJWTPayload = Depends(require_permission("admin_accounts", "update")),
    session: AsyncSession = Depends(get_db),
) -> AdminAccountResponse:
    """
    Set a new PIN for the target admin account.

    Side effects:
    - Resets ``failed_login_attempts`` to 0.
    - Clears ``locked_until`` (unlocks a brute-force-locked account).

    Use this when an admin forgets their PIN or when a PIN may have been
    compromised and must be rotated immediately.
    """
    target = await AdminAccountDAO.get_by_id_with_relations(session, admin_account_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin hisob topilmadi.")

    await AdminAccountDAO.update_pin_and_unlock(
        session, admin_account_id, hash_pin(body.new_pin)
    )

    await AdminAuditLogDAO.log(
        session=session,
        action="RESET_ADMIN_PIN",
        admin_id=admin.admin_id,
        role_snapshot=_role_snapshot(admin),
        details={
            "target_admin_id": admin_account_id,
            "target_username": target.system_username,
        },
    )
    await session.commit()

    refreshed = await AdminAccountDAO.get_by_id_with_relations(session, admin_account_id)
    return AdminAccountResponse.model_validate(refreshed)


# ===========================================================================
# 4.  Role Metadata Update
# ===========================================================================


@router.patch(
    "/system-roles/{role_id}",
    response_model=RoleResponse,
    summary="Update role metadata (name, description, home_page)",
)
async def update_role(
    role_id: int,
    body: UpdateRoleRequest,
    admin: AdminJWTPayload = Depends(require_permission("roles", "update")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> RoleResponse:
    """
    Partially update a role's name, description, or home_page.

    On rename, the RBAC Redis cache is invalidated for both the old name and
    the new name so that any admin still holding a JWT with the old role name
    gets a fresh permission load on their next request, and any stale entry
    under the new name is cleared too.
    """
    role = await RoleDAO.get_by_id(session, role_id)
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rol topilmadi")

    # Capture the current name before mutation for accurate cache invalidation.
    old_role_name = role.name

    if body.name is not None and body.name != role.name:
        # Guard against duplicate names with a clean 409 rather than letting
        # the DB unique constraint surface as an unhandled IntegrityError.
        conflicting = await RoleDAO.get_by_name(session, body.name)
        if conflicting:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"'{body.name}' nomli rol allaqachon mavjud",
            )
        role.name = body.name

    if body.description is not None:
        role.description = body.description
    if body.home_page is not None:
        role.home_page = body.home_page

    await AdminAuditLogDAO.log(
        session=session,
        action="UPDATED_ROLE",
        admin_id=admin.admin_id,
        role_snapshot=_role_snapshot(admin),
        details={"role_id": role_id, "changes": body.model_dump(exclude_none=True)},
    )
    await session.commit()
    await session.refresh(role)

    # Flush the RBAC permission cache so stale entries don't outlive the rename.
    await RBACService.invalidate_role(redis, old_role_name)
    if body.name is not None and body.name != old_role_name:
        await RBACService.invalidate_role(redis, body.name)

    return RoleResponse.model_validate(role)
