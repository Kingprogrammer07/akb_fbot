from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
import webauthn
from webauthn.helpers.structs import (
    PublicKeyCredentialCreationOptions,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialRequestOptions,
)
from webauthn.helpers.parse_registration_credential_json import parse_registration_credential_json
from webauthn.helpers.parse_authentication_credential_json import parse_authentication_credential_json

from src.config import config
from src.bot.bot_instance import bot
from src.api.dependencies import get_db, get_redis, get_admin_from_jwt, AdminJWTPayload, require_permission
from src.infrastructure.cache.keys import CacheKeys
from src.infrastructure.database.dao.admin_account import AdminAccountDAO
from src.infrastructure.database.dao.admin_audit_log import AdminAuditLogDAO
from src.infrastructure.database.dao.admin_passkey import AdminPasskeyDAO
from src.infrastructure.services.admin_alert_service import AdminAlertService
from src.infrastructure.schemas.admin_auth import (
    CheckUsernameRequest,
    CheckUsernameResponse,
    PinLoginRequest,
    PinLoginResponse,
    WebAuthnBeginRequest,
    WebAuthnBeginResponse,
    WebAuthnCompleteRequest,
    WebAuthnCompleteResponse,
    WebAuthnLoginBeginRequest,
    WebAuthnLoginBeginResponse,
    WebAuthnLoginCompleteRequest,
    WebAuthnLoginCompleteResponse,
    AdminLogoutRequest,
    ChangePinRequest,
    ResetPinRequest,
    MessageResponse,
    MyPasskeysResponse,
)
from src.api.utils.admin_jwt import create_admin_token
from src.api.utils.security import hash_pin, verify_pin
from urllib.parse import urlparse
import base64
import re

router = APIRouter(prefix="/admin/auth", tags=["Admin Auth"])

# ---------------------------------------------------------------------------
# PIN Based Login
# ---------------------------------------------------------------------------

@router.post("/check-username", response_model=CheckUsernameResponse)
async def check_username(
    request: CheckUsernameRequest,
    session: AsyncSession = Depends(get_db)
) -> CheckUsernameResponse:
    """Step 1: Get the role and check if passkey is available."""
    print(f"Checking username: {request.system_username}")
    print("*" * 20)
    account = await AdminAccountDAO.get_by_username(session, request.system_username)
    print(f"Account found: {account.system_username if account else 'None'}, active: {account.is_active if account else 'N/A'}")
    if not account or not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin account not found or disabled"
        )
    passkeys = await AdminPasskeyDAO.list_for_admin(session, account.id)
    return CheckUsernameResponse(
        role_name=account.role_name,
        has_passkey=len(passkeys) > 0
    )


@router.post("/login-pin", response_model=PinLoginResponse)
async def login_pin(
    request: PinLoginRequest,
    req: Request,
    session: AsyncSession = Depends(get_db)
) -> PinLoginResponse:
    """Step 2: Login via PIN, create session, and alert if new device."""
    from src.infrastructure.tools.datetime_utils import get_current_time
    
    account = await AdminAccountDAO.get_by_username(session, request.system_username)
    if not account or not account.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    now = get_current_time()
    if account.locked_until and account.locked_until > now:
        raise HTTPException(status_code=423, detail="Account is temporarily locked")

    ip = req.client.host if req.client else None
    ua = request.device_info or req.headers.get("user-agent", "Unknown")

    # Verify PIN using raw bcrypt
    if not verify_pin(request.pin, account.pin_hash):
        new_count = await AdminAccountDAO.increment_failed_attempts(session, account.id)
        await session.commit()
        
        await AdminAuditLogDAO.log(
            session=session,
            action="LOGIN_FAILED",
            admin_id=account.id,
            details={"attempt": new_count, "reason": "invalid_pin"},
            ip_address=ip,
            user_agent=ua
        )
        await session.commit()

        if new_count == 4:
            s_admins = await AdminAccountDAO.get_all_super_admins(session)
            s_admin_ids = [sa.telegram_id for sa in s_admins if sa.telegram_id]
            import asyncio
            asyncio.create_task(
                AdminAlertService.alert_4th_attempt(
                    bot, s_admin_ids, account.system_username, ip, ua, str(now)
                )
            )
            
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Success
    await AdminAccountDAO.reset_failed_attempts(session, account.id)
    
    # Check for new device BEFORE logging the new successful login
    last_log = await AdminAuditLogDAO.get_last_login(session, account.id)
    
    await AdminAuditLogDAO.log(
        session=session,
        action="LOGIN_SUCCESS",
        admin_id=account.id,
        details={"method": "pin"},
        ip_address=ip,
        user_agent=ua
    )
    await session.commit()

    # Alert if new device
    if last_log and (last_log.ip_address != ip or last_log.user_agent != ua):
        s_admins = await AdminAccountDAO.get_all_super_admins(session)
        s_admin_ids = [sa.telegram_id for sa in s_admins if sa.telegram_id]
        
        # Fire and forget alerts
        import asyncio
        asyncio.create_task(
            AdminAlertService.alert_new_device_to_admin(
                bot, account.telegram_id, account.system_username, ip, ua, str(now),
                super_admins_ids=s_admin_ids,
            )
        )
        asyncio.create_task(
            AdminAlertService.alert_new_device_to_super_admins(
                bot, s_admin_ids, account.system_username, ip, ua
            )
        )

    role_permissions = [p.slug for p in account.role.permissions] if account.role else []
    token, jti = create_admin_token(
        admin_id=account.id,
        role_name=account.role_name,
        secret=config.api.JWT_SECRET.get_secret_value(),
        algorithm=config.api.JWT_ALGORITHM,
        expire_minutes=config.api.JWT_EXPIRE_MINUTES,
        home_page=account.role.home_page if account.role else None,
        permissions=role_permissions,
    )
    return PinLoginResponse(
        access_token=token,
        role_name=account.role_name,
        admin_id=account.id,
        home_page=account.role.home_page if account.role else None,
    )


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@router.post("/logout", status_code=200)
async def logout(
    request: AdminLogoutRequest,
    admin: AdminJWTPayload = Depends(get_admin_from_jwt),
    redis: Redis = Depends(get_redis),
    session: AsyncSession = Depends(get_db)
):
    """Logout drops the JWT into a Redis blocklist to revoke it early."""
    blocklist_key = CacheKeys.admin_jwt_blocklist(admin.jti)
    ttl = config.api.JWT_EXPIRE_MINUTES * 60
    await redis.setex(blocklist_key, ttl, "revoked")
    
    await AdminAuditLogDAO.log(
        session=session,
        action="LOGOUT",
        admin_id=admin.admin_id,
        details={"device_info": request.device_info}
    )
    await session.commit()
    
    return {"message": "Logged out successfully"}


# ---------------------------------------------------------------------------
# Token Refresh
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=PinLoginResponse)
async def refresh_token(
    admin: AdminJWTPayload = Depends(get_admin_from_jwt),
    session: AsyncSession = Depends(get_db),
) -> PinLoginResponse:
    """
    Issue a fresh JWT containing up-to-date permissions and home_page.

    Called silently by the frontend when it detects that the cached JWT
    payload is stale (e.g., after a super-admin changes the caller's role
    permissions).  The existing token is validated first — only a currently
    valid, non-revoked token may obtain a refresh.

    The old token is NOT revoked; it remains valid until its original ``exp``.
    This is intentional: silent background refreshes must not invalidate the
    tab that triggered them.  The new token replaces the old one in the
    frontend's storage.

    Returns:
        A new PinLoginResponse with a fresh JWT encoding the current DB state.

    Raises:
        401 if the token is missing, expired, or blocklisted.
        404 if the admin account no longer exists (deactivated between requests).
    """
    account = await AdminAccountDAO.get_by_id_with_relations(session, admin.admin_id)
    if not account or not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin account not found or deactivated",
        )

    role_permissions = [p.slug for p in account.role.permissions] if account.role else []

    new_token, _jti = create_admin_token(
        admin_id=account.id,
        role_name=account.role_name,
        secret=config.api.JWT_SECRET.get_secret_value(),
        algorithm=config.api.JWT_ALGORITHM,
        expire_minutes=config.api.JWT_EXPIRE_MINUTES,
        home_page=account.role.home_page if account.role else None,
        permissions=role_permissions,
    )

    return PinLoginResponse(
        access_token=new_token,
        role_name=account.role_name,
        admin_id=account.id,
        home_page=account.role.home_page if account.role else None,
    )


# ---------------------------------------------------------------------------
# PIN Management
# ---------------------------------------------------------------------------

@router.post("/change-pin", response_model=MessageResponse)
async def change_pin(
    request: ChangePinRequest,
    admin: AdminJWTPayload = Depends(get_admin_from_jwt),
    session: AsyncSession = Depends(get_db)
) -> MessageResponse:
    """Self-service PIN change for any logged-in admin."""
    account = await AdminAccountDAO.get_by_id_with_relations(session, admin.admin_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Admin account not found")

    if not verify_pin(request.old_pin, account.pin_hash):
        # We don't increment failed attempts here to avoid a self-denial-of-service,
        # but you could if desired.
        raise HTTPException(status_code=400, detail="Incorrect old PIN")

    new_hash = hash_pin(request.new_pin)
    await AdminAccountDAO.update_pin_and_unlock(session, account.id, new_hash)

    await AdminAuditLogDAO.log(
        session=session,
        action="CHANGED_OWN_PIN",
        admin_id=account.id,
        details={}
    )
    await session.commit()
    
    return MessageResponse(message="PIN changed successfully")


@router.post("/users/{admin_account_id}/reset-pin", response_model=MessageResponse)
async def reset_pin(
    admin_account_id: int,
    request: ResetPinRequest,
    admin: AdminJWTPayload = Depends(require_permission("admin_users", "update")),
    session: AsyncSession = Depends(get_db)
) -> MessageResponse:
    """Super-Admin rescue function to reset an admin's PIN and unlock their account."""
    target_account = await AdminAccountDAO.get_by_id_with_relations(session, admin_account_id)
    if not target_account:
        raise HTTPException(status_code=404, detail="Target admin account not found")

    new_hash = hash_pin(request.new_pin)
    await AdminAccountDAO.update_pin_and_unlock(session, target_account.id, new_hash)

    await AdminAuditLogDAO.log(
        session=session,
        action="RESET_USER_PIN",
        admin_id=admin.admin_id,
        details={"target_admin_id": target_account.id, "target_username": target_account.system_username}
    )
    await AdminAuditLogDAO.log(
        session=session,
        action="PIN_RESET_BY_ADMIN",
        admin_id=target_account.id,
        details={"reset_by_admin_id": admin.admin_id}
    )
    await session.commit()

    return MessageResponse(message="PIN reset successfully and account unlocked")


# ---------------------------------------------------------------------------
# WebAuthn (Passkey) Flows
# ---------------------------------------------------------------------------

@router.post("/webauthn/register/begin", response_model=WebAuthnBeginResponse)
async def webauthn_register_begin(
    req: WebAuthnBeginRequest,
    admin: AdminJWTPayload = Depends(require_permission("auth", "passkey")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis)
) -> WebAuthnBeginResponse:
    """Register a new hardware key or biometric passkey. Requires the `auth:passkey` RBAC permission."""
        
    rp_id = config.api.ADMIN_PANEL_ORIGIN
    if not rp_id:
        raise HTTPException(status_code=501, detail="API_ADMIN_PANEL_ORIGIN not configured.")
        
    from urllib.parse import urlparse
    import re

    parsed = urlparse(rp_id)
    hostname = parsed.hostname or rp_id

    # WebAuthn rejects IP addresses as rp_id (browsers enforce registrable-domain rules).
    # Fall back to "localhost" so local/IP-based deployments still work during testing.
    is_ip = re.match(r"^\d{1,3}(\.\d{1,3}){3}$", hostname)
    rp_domain = "localhost" if is_ip else hostname
        
    account = await AdminAccountDAO.get_by_id_with_relations(session, admin.admin_id)
    if not account:
        raise HTTPException(status_code=404, detail="Admin account not found")

    existing_passkeys = await AdminPasskeyDAO.list_for_admin(session, admin.admin_id)

    import secrets
    import json
    import traceback
    challenge_str = secrets.token_urlsafe(32)
    challenge = challenge_str.encode('utf-8')
    await redis.setex(f"webauthn_challenge:reg:{admin.admin_id}", 300, challenge_str)

    try:
        exclude_credentials = [
            # credential_id stored as base64url; decode to raw bytes for py_webauthn
            PublicKeyCredentialDescriptor(id=base64.urlsafe_b64decode(pk.credential_id + "=="))
            for pk in existing_passkeys
        ]
        registration_opts = webauthn.generate_registration_options(
            rp_id=rp_domain,
            rp_name="AKB Admin Panel",
            user_id=str(admin.admin_id).encode("utf-8"),
            user_name=account.system_username,
            challenge=challenge,
            exclude_credentials=exclude_credentials,
            attestation=webauthn.helpers.structs.AttestationConveyancePreference.NONE,
        )
        return WebAuthnBeginResponse(options=json.loads(webauthn.options_to_json(registration_opts)))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"WebAuthn options generation failed: {e}")


@router.post("/webauthn/register/complete", response_model=WebAuthnCompleteResponse)
async def webauthn_register_complete(
    request: WebAuthnCompleteRequest,
    admin: AdminJWTPayload = Depends(require_permission("auth", "passkey")),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis)
) -> WebAuthnCompleteResponse:
    """Complete passkey registration and save to DB. Requires the `auth:passkey` RBAC permission."""
    challenge_key = f"webauthn_challenge:reg:{admin.admin_id}"
    expected_challenge_str = await redis.get(challenge_key)
    if not expected_challenge_str:
        raise HTTPException(status_code=400, detail="Challenge expired or not found")
    expected_challenge = expected_challenge_str.encode('utf-8')
        
    origin = config.api.ADMIN_PANEL_ORIGIN
    if not origin:
        raise HTTPException(status_code=501, detail="API_ADMIN_PANEL_ORIGIN not configured.")

    parsed = urlparse(origin)
    hostname = parsed.hostname or origin
    is_ip = re.match(r"^\d{1,3}(\.\d{1,3}){3}$", hostname)
    rp_domain = "localhost" if is_ip else hostname

    try:
        credential = parse_registration_credential_json(request.attestation_response)

        verification = webauthn.verify_registration_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_rp_id=rp_domain,
            expected_origin=origin,
            require_user_verification=True
        )

        # Store credential_id as base64url (no padding) — this matches the format
        # that py_webauthn returns in AuthenticationCredential.id during login,
        # so get_by_credential_id() works without any conversion at lookup time.
        # Store public_key as standard base64 — it's opaque binary, never compared externally.
        new_passkey_data = {
            "admin_account_id": admin.admin_id,
            "credential_id": base64.urlsafe_b64encode(verification.credential_id).rstrip(b"=").decode("ascii"),
            "public_key": base64.b64encode(verification.credential_public_key).decode("ascii"),
            "sign_count": verification.sign_count,
            "device_name": request.device_name
        }
        
        # Manually create object because using base DAO add expects a pydantic model 
        # (our DAO was bound to AdminPasskey base which sometimes takes Dict if overriden, 
        # but let's just use raw session)
        from src.infrastructure.database.models.admin_passkey import AdminPasskey
        new_passkey = AdminPasskey(**new_passkey_data)
        session.add(new_passkey)
        
        await AdminAuditLogDAO.log(
            session=session,
            action="PASSKEY_REGISTERED",
            admin_id=admin.admin_id,
            details={"device_name": request.device_name}
        )
        
        await session.commit()
        await redis.delete(challenge_key)
        
        return WebAuthnCompleteResponse(message="Passkey registered successfully")

    except webauthn.helpers.exceptions.InvalidRegistrationResponse as e:
        raise HTTPException(status_code=400, detail=f"WebAuthn verification failed: {e}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal error during WebAuthn registration")


@router.post("/webauthn/login/begin", response_model=WebAuthnLoginBeginResponse)
async def webauthn_login_begin(
    request: WebAuthnLoginBeginRequest,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis)
) -> WebAuthnLoginBeginResponse:
    account = await AdminAccountDAO.get_by_username(session, request.system_username)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Admin account not found")
        
    origin = config.api.ADMIN_PANEL_ORIGIN
    if not origin:
        raise HTTPException(status_code=501, detail="API_ADMIN_PANEL_ORIGIN not configured.")

    parsed = urlparse(origin)
    hostname = parsed.hostname or origin

    # WebAuthn rejects IP addresses as rp_id (browsers enforce registrable-domain rules).
    # Fall back to "localhost" so local/IP-based deployments still work during testing.
    is_ip = re.match(r"^\d{1,3}(\.\d{1,3}){3}$", hostname)
    rp_domain = "localhost" if is_ip else hostname

    passkeys = await AdminPasskeyDAO.list_for_admin(session, account.id)
    if not passkeys:
        raise HTTPException(status_code=400, detail="No passkeys registered for this account")

    import secrets
    import json
    import traceback
    challenge_str = secrets.token_urlsafe(32)
    challenge = challenge_str.encode('utf-8')
    # Store as text — raw bytes can't be decoded by Redis with decode_responses=True
    await redis.setex(f"webauthn_challenge:login:{request.system_username}", 300, challenge_str)

    try:
        allow_credentials = [
            # credential_id stored as base64url; decode to raw bytes for py_webauthn
            PublicKeyCredentialDescriptor(id=base64.urlsafe_b64decode(pk.credential_id + "=="))
            for pk in passkeys
        ]
        auth_opts = webauthn.generate_authentication_options(
            rp_id=rp_domain,
            challenge=challenge,
            allow_credentials=allow_credentials,
        )
        return WebAuthnLoginBeginResponse(options=json.loads(webauthn.options_to_json(auth_opts)))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"WebAuthn options generation failed: {e}")


@router.post("/webauthn/login/complete", response_model=WebAuthnLoginCompleteResponse)
async def webauthn_login_complete(
    request: WebAuthnLoginCompleteRequest,
    req: Request,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis)
) -> WebAuthnLoginCompleteResponse:
    account = await AdminAccountDAO.get_by_username(session, request.system_username)
    if not account or not account.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    challenge_key = f"webauthn_challenge:login:{request.system_username}"
    expected_challenge_str = await redis.get(challenge_key)
    if not expected_challenge_str:
        raise HTTPException(status_code=400, detail="Challenge expired or not found")
    expected_challenge = expected_challenge_str.encode('utf-8')

    origin = config.api.ADMIN_PANEL_ORIGIN
    if not origin:
        raise HTTPException(status_code=501, detail="API_ADMIN_PANEL_ORIGIN not configured.")

    parsed = urlparse(origin)
    hostname = parsed.hostname or origin
    is_ip = re.match(r"^\d{1,3}(\.\d{1,3}){3}$", hostname)
    rp_domain = "localhost" if is_ip else hostname

    try:
        credential = parse_authentication_credential_json(request.assertion_response)

        # Find which passkey was used — credential.id is base64url (no padding),
        # which matches how we stored credential_id in webauthn_register_complete.
        pk_record = await AdminPasskeyDAO.get_by_credential_id(session, credential.id)
        if not pk_record or pk_record.admin_account_id != account.id:
            raise HTTPException(status_code=401, detail="Passkey not recognized for this account")

        # Decode public_key from the base64 string we stored at registration time
        public_key_bytes = base64.b64decode(pk_record.public_key)

        verification = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_rp_id=rp_domain,
            expected_origin=origin,
            credential_public_key=public_key_bytes,
            credential_current_sign_count=pk_record.sign_count,
            require_user_verification=True
        )

        # Update sign count
        await AdminPasskeyDAO.update_sign_count(session, pk_record.id, verification.new_sign_count)
        
        # Log success and alert new device logic
        ip = req.client.host if req.client else None
        ua = request.device_info or req.headers.get("user-agent", "Unknown")
        
        last_log = await AdminAuditLogDAO.get_last_login(session, account.id)
        
        await AdminAuditLogDAO.log(
            session=session,
            action="PASSKEY_LOGIN_SUCCESS",
            admin_id=account.id,
            details={"method": "webauthn"},
            ip_address=ip,
            user_agent=ua
        )
        await session.commit()
        await redis.delete(challenge_key)
        
        from src.infrastructure.tools.datetime_utils import get_current_time
        if last_log and (last_log.ip_address != ip or last_log.user_agent != ua):
            s_admins = await AdminAccountDAO.get_all_super_admins(session)
            s_admin_ids = [sa.telegram_id for sa in s_admins if sa.telegram_id]
            import asyncio
            asyncio.create_task(
                AdminAlertService.alert_new_device_to_admin(
                    bot, account.telegram_id, account.system_username, ip, ua,
                    str(get_current_time()), super_admins_ids=s_admin_ids,
                )
            )
            asyncio.create_task(
                AdminAlertService.alert_new_device_to_super_admins(
                    bot, s_admin_ids, account.system_username, ip, ua
                )
            )

        role_permissions = [p.slug for p in account.role.permissions] if account.role else []

        token, jti = create_admin_token(
            admin_id=account.id,
            role_name=account.role_name,
            secret=config.api.JWT_SECRET.get_secret_value(),
            algorithm=config.api.JWT_ALGORITHM,
            expire_minutes=config.api.JWT_EXPIRE_MINUTES,
            home_page=account.role.home_page if account.role else None,
            permissions=role_permissions,
        )

        return WebAuthnLoginCompleteResponse(
            access_token=token,
            role_name=account.role_name,
            admin_id=account.id,
            home_page=account.role.home_page if account.role else None,
        )

    except webauthn.helpers.exceptions.InvalidAuthenticationResponse as e:
        raise HTTPException(status_code=400, detail=f"WebAuthn verification failed: {e}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal error during WebAuthn login")


# ---------------------------------------------------------------------------
# Passkey device check
# ---------------------------------------------------------------------------

@router.get("/webauthn/my-passkeys", response_model=MyPasskeysResponse)
async def get_my_passkeys(
    device_name: str,
    admin: AdminJWTPayload = Depends(require_permission("auth", "passkey")),
    session: AsyncSession = Depends(get_db),
) -> MyPasskeysResponse:
    """Check if the admin has a passkey registered for the exact device calling the API.

    The frontend uses this to disable the "Register Passkey" button when the
    current device already has a credential, while still allowing registration
    from a new device.
    """
    passkeys = await AdminPasskeyDAO.list_for_admin(session, admin.admin_id)
    has_current = any(pk.device_name == device_name for pk in passkeys)
    return MyPasskeysResponse(
        has_current_device_passkey=has_current,
        total_passkeys=len(passkeys),
    )
