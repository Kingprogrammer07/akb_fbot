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
    def carousel_presigned_url(s3_key: str) -> str:
        """Cached presigned URL for a carousel S3 object.

        TTL must stay below the presigned URL expiry (7 days) so clients
        never receive an already-expired link.
        """
        return f"carousel:presigned:{s3_key}"
