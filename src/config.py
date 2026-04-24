from pathlib import Path
from urllib.parse import quote

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class BotConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix='BOT_', env_file=BASE_DIR / '.env', env_file_encoding='utf-8', extra='ignore'
    )

    TOKEN: SecretStr
    WEBHOOK_URL: str | None = None
    ADMIN_ACCESS_IDs: set[int] | None
    
    # WebApp URLs
    WEBAPP_BASE_URL: str = Field(
        'https://example.com',
        description='WebApp base URL'
    )

    @property
    def webapp_register_url(self) -> str:
        """Get WebApp registration URL."""
        return f"{self.WEBAPP_BASE_URL}/auth/register"

    @property
    def webapp_login_url(self) -> str:
        """Get WebApp login URL."""
        return f"{self.WEBAPP_BASE_URL}/auth/login"

    @property
    def webapp_import_url(self) -> str:
        """Get WebApp import URL."""
        return f"{self.WEBAPP_BASE_URL}/import"

    @property
    def webapp_client_add(self) -> str:
        """Get WebApp client add URL."""
        return f"{self.WEBAPP_BASE_URL}/client/add"

    def webapp_client_edit(self, client_id: int) -> str:
        """Get WebApp client edit URL."""
        return f"{self.WEBAPP_BASE_URL}/client/edit/{client_id}"
        
    @property
    def webapp_flights(self) -> str:
        """Get WebApp flights URL."""
        return f"{self.WEBAPP_BASE_URL}/flights"

    @property
    def webapp_verification_search(self) -> str:
        """Get WebApp verification search URL."""
        # return f"{self.WEBAPP_BASE_URL}/verification/search"
        return f"{self.WEBAPP_BASE_URL}/pos"

    @property
    def webapp_request_page_url(self) -> str:
        """Get WebApp request page URL."""
        return f"{self.WEBAPP_BASE_URL}/user/home?tab=request"

    def webapp_verification_search_user(self, client_id: int) -> str:
        """Get WebApp verification search URL."""
        return f"{self.WEBAPP_BASE_URL}/verification/profile/{client_id}"

    # Group and Channel IDs
    TASDIQLASH_GROUP_ID: int = Field(
        ...,
        description='Group ID for approval requests'
    )
    TASDIQLANGANLAR_CHANNEL_ID: int = Field(
        ...,
        description='Channel ID for approved clients'
    )
    TOLOVLARNI_TASDIQLASH_GROUP_ID: int = Field(
        -1001000000000,
        description='Group ID for payment confirmation requests'
    )
    TOLOV_TASDIQLANGAN_CHANNEL_ID: int = Field(
        -1001000000001,
        description='Channel ID for confirmed payments'
    )

    # Account payments channel (Click/Payme confirmations)
    HISOBGA_TOLOV_CHANNEL_ID: int = Field(
        -1001000000007,
        description='Channel ID for account payment confirmations (Click/Payme)'
    )

    UZPOST_TOLOVLARNI_TASDIQLASH_GROUP_ID: int = Field(
        -1001000000002,
        description='Group ID for UZPOST payment confirmation requests'
    )
    
    UZPOST_DELIVERY_REQUEST_CHANNEL_ID: int = Field(
        -1001000000003,
        description='Channel ID for UZPOST delivery requests'
    )

    AKB_DELIVERY_REQUEST_CHANNEL_ID: int = Field(
        -1001000000004,
        description='Channel ID for AKB delivery requests'
    )

    YANDEX_DELIVERY_REQUEST_CHANNEL_ID: int = Field(
        -1001000000005,
        description='Channel ID for Yandex delivery requests'
    )
    
    BTS_DELIVERY_REQUEST_CHANNEL_ID: int = Field(
        -1001000000006,
        description='Channel ID for BTS delivery requests'
    )
    
    
    # Foto Hisobot Channel IDs
    FOTO_HISOBOT_SUCCESS_CHANNEL_ID: int = Field(
        ...,
        description='Channel ID for successful cargo photo report sends'
    )
    FOTO_HISOBOT_FAIL_CHANNEL_ID: int = Field(
        ...,
        description='Channel ID for failed cargo photo report sends (blocked/errors)'
    )
    
    # Database Backup
    DATABASE_BACKUP_CHANNEL_ID: int | None = Field(
        None,
        description='Channel ID for automatic daily database backups (optional)'
    )

    # Wallet-related channels
    REFUND_CHANNEL_ID: int = Field(
        -1001000000008,
        description='Channel ID for refund requests from users'
    )
    DEBT_GROUP_ID: int = Field(
        -1001000000009,
        description='Group ID for debt payment confirmations'
    )

    E_TIJORAT_CHANNEL_ID: int = Field(
        -1001000000010,
        description='Channel ID for E-Tijorat requests'
    )

    WAREHOUSE_TAKEN_AWAY_PROVE_GROUP_ID: int = Field(
        -1001000000011,
        description='Group ID for warehouse taken-away proof notifications (photos + delivery method)'
    )

    AKB_XORAZM_FILIALI_GROUP_ID: int = Field(
        -1001000000012,
        description='Group ID for AKB Xorazm filiali — receives cargo reports for GX-coded clients not registered in the client DB'
    )

    AKB_OSTATKA_GROUP_ID: int = Field(
        -1001000000013,
        description='Group ID for ostatka (A- prefixed) flights — receives per-client cargo reports and daily leftover statistics'
    )

    def get_bot_link(self) -> str:
        same_name = quote(self.USERNAME, safe='')
        return f'https://t.me/{same_name}'


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix='POSTGRES_',
        env_file=BASE_DIR / '.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )

    DB: str = Field('postgres', min_length=3)
    USER: str = Field('postgres', min_length=3)
    PASSWORD: SecretStr = Field(SecretStr('password'), min_length=8)
    PORT: int = Field(5432, ge=1024, le=65535)
    HOST: str = Field('postgres')
    DRIVER: str = Field('postgresql+asyncpg')

    @property
    def database_url(self) -> str:
        user = quote(self.USER)
        password = quote(self.PASSWORD.get_secret_value())
        return f'{self.DRIVER}://{user}:{password}@{self.HOST}:{self.PORT}/{self.DB}'


class RedisConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix='REDIS_', env_file=BASE_DIR / '.env', env_file_encoding='utf-8', extra='ignore'
    )

    HOST: str = Field('redis')
    PORT: int = Field(6379, ge=1024, le=65535)
    DB: int = Field(0)
    USERNAME: str | None = None
    PASSWORD: SecretStr | None = None
    TTL: int | None = Field(3600, description='Default TTL in seconds')
    MAX_CONNECTIONS: int = Field(10)

    @property
    def dsn(self) -> str:
        credentials = ''
        if self.PASSWORD:
            credentials += f':{quote(self.PASSWORD.get_secret_value())}'
        if self.USERNAME:
            credentials += quote(self.USERNAME)
        if credentials:
            credentials += '@'
        return f'redis://{credentials}{self.HOST}:{self.PORT}/{self.DB}'


class LoggingConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix='LOG_', env_file=BASE_DIR / '.env', env_file_encoding='utf-8', extra='ignore'
    )

    LEVEL: str = Field('DEBUG')
    FILE_ENABLED: bool = Field(True)
    BACKUP_COUNT: int = Field(15)
    TELEGRAM_ENABLED: bool = Field(True)
    @field_validator('LEVEL')
    def validate_log_level(cls, value):
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if value.upper() not in valid_levels:
            raise ValueError(f'Log level must be one of {valid_levels}')
        return value.upper()


class APIConfig(BaseSettings):
    """API and CORS configuration."""
    model_config = SettingsConfigDict(
        env_prefix='API_', env_file=BASE_DIR / '.env', env_file_encoding='utf-8', extra='ignore'
    )

    HOST: str = Field('0.0.0.0')
    PORT: int = Field(8010, ge=1024, le=65535)

    # CORS settings
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["*"])
    CORS_ALLOW_CREDENTIALS: bool = Field(True)
    CORS_ALLOW_METHODS: list[str] = Field(default_factory=lambda: ["*"])
    CORS_ALLOW_HEADERS: list[str] = Field(default_factory=lambda: ["*"])

    # Currency Converter API
    CURRENCY_API_KEY: str = Field(
        default="https://open.er-api.com/v6/latest/USD", min_length=20, description='Currency API key')

    # ── China Partner Import API ────────────────────────────────────────────
    # Shared secret for the partner company's shipment creation endpoint.
    # Set API_CHINA_PARTNER_KEY=<random-64-char-hex> in .env
    # and share it with the partner out-of-band (never commit it).
    CHINA_PARTNER_KEY: SecretStr = Field(
        SecretStr("change-me-generate-a-random-64-char-hex-key"),
        description="Static API key for POST /api/v1/shipment/create",
    )

    # ── Admin Panel JWT Settings ────────────────────────────────────────────
    # Add these to .env:  API_JWT_SECRET, API_JWT_ALGORITHM, API_JWT_EXPIRE_MINUTES
    # API_ADMIN_PANEL_ORIGIN is required for WebAuthn (e.g. https://admin.example.com)
    JWT_SECRET: SecretStr = Field(
        SecretStr('changeme-please-set-a-real-secret-in-env-min-32-chars'),
        description='Secret key for signing Admin JWT tokens'
    )
    JWT_ALGORITHM: str = Field('HS256', description='JWT signing algorithm')
    JWT_EXPIRE_MINUTES: int = Field(480, ge=5, description='Admin JWT lifetime in minutes (default 8h)')
    ADMIN_PANEL_ORIGIN: str | None = Field(
        None, description='Origin for WebAuthn RP (e.g. https://admin.example.com). Required for passkey endpoints.'
    )


class GoogleSheetsConfig(BaseSettings):
    """Google Sheets API configuration."""
    model_config = SettingsConfigDict(
        env_prefix='GOOGLE_SHEETS_',
        env_file=BASE_DIR / '.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )

    SHEETS_ID: str = Field(..., min_length=20, description='Google Sheets spreadsheet ID')
    API_KEY: str = Field(..., min_length=20, description='Google Sheets API key')


class AWSConfig(BaseSettings):
    """AWS S3 configuration."""
    model_config = SettingsConfigDict(
        env_prefix='AWS_',
        env_file=BASE_DIR / '.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )

    ACCESS_KEY_ID: str = Field(..., min_length=10, description='AWS Access Key ID')
    SECRET_ACCESS_KEY: SecretStr = Field(..., description='AWS Secret Access Key')
    REGION: str = Field('eu-north-1', description='AWS region')
    BUCKET_NAME: str = Field('akb-media', description='S3 bucket name')


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file_encoding='utf-8', extra='ignore')

    telegram: BotConfig = BotConfig()
    database: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    logging: LoggingConfig = LoggingConfig()
    api: APIConfig = APIConfig()
    google_sheets: GoogleSheetsConfig = GoogleSheetsConfig()
    aws: AWSConfig = AWSConfig()


config = Config()
