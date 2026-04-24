"""
Database seeders — idempotent functions that populate reference/lookup data.

Each seeder is safe to call multiple times: it checks whether records already
exist before inserting, so re-running on an already-seeded database is a no-op.

Call order on startup:
    1. seed_permissions  — ensures Permission rows exist
    2. seed_roles        — creates built-in roles and assigns permissions
                           (must run after seed_permissions so it can look up
                           Permission objects by slug)
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.role import Permission, Role

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Permission definitions
#
# Each resource maps to the set of actions that can be granted on it.
# Keep this list as the single source of truth for what the RBAC system knows.
# New entries will be inserted on the next startup; existing ones are skipped.
# ---------------------------------------------------------------------------

_PERMISSION_DEFINITIONS: dict[str, list[str]] = {
    # Admin account management — super-admin only in practice; super-admin bypasses
    # RBAC checks implicitly but these rows must exist so the permission IDs are
    # available when building custom roles via the management UI.
    "admin_accounts":  ["read", "create", "update", "delete"],
    # Role and permission management
    "roles":           ["read", "create", "update", "delete"],
    # Audit log access — read-only; write is performed by the system internally.
    "audit_logs":      ["read"],
    # clients:finance_read  →  GET  /admin/clients/{id}/finances + payment-detail + flights
    # clients:finance_update is reserved for future balance correction endpoints.
    "clients":        ["read", "verify", "update", "ban", "finance_read", "finance_update"],
    "cargo":          ["read", "create", "update", "delete"],
    "payments":       ["read", "approve", "reject", "export"],
    "flights":        ["read", "create", "update", "delete"],
    # POS (Point of Sale) Fast Cashier — intentionally a separate resource so
    # that a "Cashier" role can be granted counter-specific write access without
    # inheriting the broader payment admin operations (approve refunds, export).
    # pos:process  →  POST /payments/process-bulk
    # pos:read     →  GET  /payments/cashier-log
    # pos:adjust   →  POST /payments/adjust-balance
    "pos":            ["process", "read", "adjust", "update_status"],
    # auth:passkey gates WebAuthn passkey registration and device management.
    # Assign this to any role that should be able to register hardware keys or
    # biometrics (e.g. "Accountant").  Super-admin bypasses all RBAC checks
    # implicitly and does not need this permission explicitly assigned.
    "auth":           ["passkey"],
    # carousel: controls access to the admin-facing carousel content management
    # routes.  Not assigned to any seeded role by default — super-admin grants
    # this explicitly to whichever roles should manage carousel items.
    "carousel":       ["read", "create", "update", "delete"],
    # warehouse:read       → view flight transactions list
    # warehouse:mark_taken → mark cargo as taken-away (upload proof photos)
    #   mark_taken is deliberately separate so super-admin can grant it only to
    #   trusted warehouse workers while basic read access is less sensitive.
    "warehouse":      ["read", "mark_taken"],
    # expected_cargo:manage → full CRUD over the pre-arrival cargo manifest
    #   (create track codes, search, replace, rename flights, delete, export,
    #    and resolve a track code to a Client record).  A single broad permission
    #    is intentional here — only trusted logistics staff should access this
    #    manifest at all, so read/write/delete granularity adds no real security
    #    benefit and would complicate role assignment needlessly.
    "expected_cargo":   ["manage"],
    # flight_schedule:manage → full CRUD over the manager-maintained flight calendar
    #   (list by year, create, update, delete).  A single broad permission keeps
    #   role assignment simple — only ops managers need to touch this data.
    "flight_schedule":  ["manage"],
}


async def seed_permissions(session: AsyncSession) -> None:
    """
    Populate the ``permissions`` table from ``_PERMISSION_DEFINITIONS``.

    Strategy: load all existing (resource, action) pairs into a set, then
    bulk-insert only the ones that are missing. This is safe under concurrent
    startups because the ``uq_permission_resource_action`` unique constraint
    on the table will reject true duplicates at the DB level.
    """
    existing_result = await session.execute(
        select(Permission.resource, Permission.action)
    )
    existing_slugs: set[tuple[str, str]] = {
        (row.resource, row.action) for row in existing_result
    }

    to_insert: list[Permission] = []
    for resource, actions in _PERMISSION_DEFINITIONS.items():
        for action in actions:
            if (resource, action) not in existing_slugs:
                to_insert.append(Permission(resource=resource, action=action))

    if not to_insert:
        logger.debug("seed_permissions: all permissions already present, nothing to insert")
        return

    session.add_all(to_insert)
    await session.commit()
    logger.info(
        "seed_permissions: inserted %d new permission(s): %s",
        len(to_insert),
        [f"{p.resource}:{p.action}" for p in to_insert],
    )


# ---------------------------------------------------------------------------
# Default role definitions
#
# These represent the INITIAL state for first-time role creation only.
# Once a role exists in the DB the seeder never touches its permissions again,
# so super-admins can freely edit or delete these roles from the management UI
# without the seeder reverting their changes on the next startup.
#
# super-admin is intentionally absent:
#   • It is created interactively by scripts/seed_super_admin.py.
#   • It bypasses all RBAC checks in code, so no permission rows are needed.
#   • It should have is_custom=False (set by the script) so it cannot be
#     accidentally deleted via the management API.
#
# worker / accountant use is_custom=True so the super-admin CAN edit or
# delete them from the UI.  is_custom=False is reserved solely for super-admin.
# ---------------------------------------------------------------------------

_ROLE_DEFINITIONS: dict[str, dict] = {
    "worker": {
        "description": (
            "Ishchi - faqat yuk fotohisobotlarini boshqaradi, mijozlar va moliyaviy ma'lumotlarga kira olmaydi. "
        ),
        # is_custom=True so the super-admin can edit permissions or delete this
        # role from the management UI without being blocked by the system-role guard.
        "is_custom": True,
        "home_page": "/flights",
        "initial_permissions": [
            "flights:read",
            "flights:create",
            "flights:update",
        ],
    },
    "accountant": {
        "description": (
            "Kassir - mijozlar va ularning to'lov tarixini ko'rish, moliyaviy tuzatishlar kiritish, va tezkor kassirlik amallarini bajarish uchun mo'ljallangan. "
        ),
        "is_custom": True,
        "home_page": "/pos",
        "initial_permissions": [
            "pos:process",
            "pos:read",
            "pos:adjust",
            "pos:update_status",
            "auth:passkey",  # Face ID / hardware key for payment counter login
        ],
    },
    "manager": {
        "description": (
            "Menejer - mijozlar, ularning tranzaksiyalari va moliyaviy ma'lumotlarini boshqarish uchun mo'ljallangan. "
        ),
        "is_custom": True,
        "home_page": "/admin/clients",
        "initial_permissions": [
            "clients:read",
            "clients:update",
            "clients:finance_read",
        ],
    },
    "warehouse": {
        "description": (
            "Omborchi - yuk fotohisobotlarini boshqarish va mijoz tranzaksiyalarini ko'rish uchun mo'ljallangan, lekin moliyaviy ma'lumotlarga kira olmaydi. "
        ),
        "is_custom": True,
        "home_page": "/admin/warehouse",
        "initial_permissions": [
            # Search clients to find their transactions
            "clients:read",
            # Browse flight transaction lists
            "warehouse:read",
            # Mark cargo as taken-away with delivery proof photos
            "warehouse:mark_taken",
        ],
    },
}


async def seed_roles(session: AsyncSession) -> None:
    """
    Create default roles and keep their ``initial_permissions`` in sync.

    Strategy (safe for production re-runs):
    - If the role does NOT exist → create it with all ``initial_permissions``.
    - If the role already exists → add any ``initial_permissions`` that are
      currently missing from the DB row.  Permissions already present (whether
      seeded or added manually by a super-admin) are never removed.

    The additive-only approach fixes the common case where a new permission is
    added to ``initial_permissions`` after the role was first created (e.g.
    ``auth:passkey`` added to an existing ``accountant`` role).
    """
    from sqlalchemy.orm import selectinload

    # Load all permissions into a lookup map once — avoids N+1 queries.
    all_perms_result = await session.execute(select(Permission))
    perm_by_slug: dict[str, Permission] = {
        p.slug: p for p in all_perms_result.scalars().all()
    }

    any_change = False

    for role_name, role_def in _ROLE_DEFINITIONS.items():
        role_result = await session.execute(
            select(Role)
            .options(selectinload(Role.permissions))
            .where(Role.name == role_name)
        )
        role = role_result.scalar_one_or_none()

        if role is None:
            # First-time creation: assign all initial permissions.
            initial_perms: list[Permission] = []
            for slug in role_def["initial_permissions"]:
                perm = perm_by_slug.get(slug)
                if perm is None:
                    logger.error(
                        "seed_roles: permission %r not found in DB — "
                        "ensure seed_permissions ran before seed_roles",
                        slug,
                    )
                    continue
                initial_perms.append(perm)

            role = Role(
                name=role_name,
                description=role_def["description"],
                is_custom=role_def["is_custom"],
                home_page=role_def["home_page"],
            )
            role.permissions.extend(initial_perms)
            session.add(role)

            logger.info(
                "seed_roles: created role %r with %d initial permission(s): %s",
                role_name,
                len(initial_perms),
                [p.slug for p in initial_perms],
            )
            any_change = True

        else:
            # Role exists — add any missing initial permissions (additive only).
            existing_slugs: set[str] = {p.slug for p in role.permissions}
            missing: list[Permission] = []

            for slug in role_def["initial_permissions"]:
                if slug in existing_slugs:
                    continue
                perm = perm_by_slug.get(slug)
                if perm is None:
                    logger.error(
                        "seed_roles: permission %r not found in DB — "
                        "ensure seed_permissions ran before seed_roles",
                        slug,
                    )
                    continue
                missing.append(perm)

            if missing:
                role.permissions.extend(missing)
                logger.info(
                    "seed_roles: added %d missing permission(s) to existing role %r: %s",
                    len(missing),
                    role_name,
                    [p.slug for p in missing],
                )
                any_change = True
            else:
                logger.debug(
                    "seed_roles: role %r already has all initial permissions, skipping",
                    role_name,
                )

    if not any_change:
        logger.debug("seed_roles: all default roles are up-to-date, nothing to change")
        return

    await session.commit()
