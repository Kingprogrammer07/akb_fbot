class CacheKeys:
    """Generates cache keys with bot prefix."""

    @staticmethod
    def user_by_telegram_id(telegram_id: int) -> str:
        """Generate key for user by telegram_id."""
        return f'bot:user:telegram_id:{telegram_id}'

    @staticmethod
    def role_permissions(role_name: str) -> str:
        """Key for cached RBAC permissions for a specific role."""
        return f"rbac:role_permissions:{role_name}"

    @staticmethod
    def admin_jwt_blocklist(jti: str) -> str:
        """Key for early-revoked JWTs (e.g. on manual logout)."""
        return f"admin:jwt:blocklist:{jti}"

    @staticmethod
    def admin_identity(admin_id: int) -> str:
        """
        Key for an admin's current active-status and role name.

        Short-lived: it exists so authentication can enforce live account state
        without a database round-trip per request.
        """
        return f"admin:identity:{admin_id}"

    @staticmethod
    def admin_identity_version(admin_id: int) -> str:
        """
        Monotonic counter bumped whenever an admin's identity changes.

        Cached identities carry the counter value they were read under, so an
        in-flight request that started before a revocation cannot write its
        stale snapshot back over the invalidated entry.
        """
        return f"admin:identity:ver:{admin_id}"

    @staticmethod
    def carousel_presigned_url(s3_key: str) -> str:
        """Cached presigned URL for a carousel S3 object.

        TTL must stay below the presigned URL expiry (7 days) so clients
        never receive an already-expired link.
        """
        return f"carousel:presigned:{s3_key}"
