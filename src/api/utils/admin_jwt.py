import uuid
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from fastapi import HTTPException, status
import logging

logger = logging.getLogger(__name__)


def create_admin_token(
    admin_id: int,
    role_name: str,
    secret: str,
    algorithm: str,
    expire_minutes: int,
    home_page: str | None = None,
    permissions: list[str] | None = None,
) -> tuple[str, str]:
    """
    Generate a new Admin JWT.

    Args:
        admin_id:       Admin DB primary key — stored as the ``sub`` claim.
        role_name:      Role name string — used for RBAC checks on every request.
        secret:         HMAC signing secret.
        algorithm:      JWT algorithm identifier (e.g. ``"HS256"``).
        expire_minutes: Token lifetime in minutes.
        home_page:      Role's configured landing page (e.g. ``"/admin/pos"``).
                        Embedded so the frontend can redirect immediately after
                        login without a separate API call.
        permissions:    Flat list of ``"resource:action"`` slugs for this role.
                        Embedded so the frontend can gate UI elements at parse
                        time without a separate permissions API call.

    Returns:
        Tuple of ``(token_string, jti_string)``.
        ``jti`` is a UUID4 included for manual logout (JTI blocklist in Redis).
    """
    jti = str(uuid.uuid4())
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)

    to_encode: dict = {
        "sub": str(admin_id),
        "role": role_name,
        "jti": jti,
        "exp": expire,
        # Always present so the frontend never needs a null-check; super-admin
        # receives an empty list because it bypasses RBAC checks entirely.
        "permissions": permissions or [],
    }

    # Only embed when present — keeps token compact for roles without a
    # custom landing page while remaining backward-compatible with clients
    # that already handle a missing claim.
    if home_page is not None:
        to_encode["home_page"] = home_page
    
    # Safe guard, check secret
    if not secret:
        raise ValueError("JWT_SECRET is empty. Please set API_JWT_SECRET in .env.")
        
    encoded_jwt = jwt.encode(to_encode, secret, algorithm=algorithm)
    return encoded_jwt, jti


def decode_admin_token(token: str, secret: str, algorithm: str) -> dict:
    """
    Decode and validate token signature and expiry.
    Raises HTTPException (401) on invalid signature, expired, or malformed payload.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate admin credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # jwt_decode also inherently checks 'exp' claim validity if provided
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        
        # Verify required claims
        admin_id_str = payload.get("sub")
        role_name = payload.get("role")
        jti = payload.get("jti")
        
        if admin_id_str is None or role_name is None or jti is None:
            logger.warning("Decoded token is missing required claims")
            raise credentials_exception
            
        return payload
    except JWTError as e:
        logger.warning(f"JWT decode failed: {e}")
        raise credentials_exception
