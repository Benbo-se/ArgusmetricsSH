"""
Application configuration using Pydantic BaseSettings.
Environment variables are loaded from .env file or system environment.
"""
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden via environment variables.
    For local development, create a .env file in the backend directory.
    """

    # Application
    APP_NAME: str = Field(default="Argusmetrics", description="Application name")
    BRAND_NAME: str = Field(default="argusmetrics", description="Brand name for DNS verification (e.g., 'argusmetrics')")
    BASE_URL: str = Field(default="https://www.argusmetrics.io", description="Base URL for the application")
    DEBUG: bool = Field(default=False, description="Enable debug mode")
    API_V1_PREFIX: str = Field(default="/api/v1", description="API version prefix")

    # Security
    SECRET_KEY: str = Field(..., description="Secret key for JWT encoding (required)")
    ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, description="Access token expiry in minutes")
    SESSION_EXPIRY_DAYS: int = Field(default=30, description="Session expiry in days")
    MAGIC_TOKEN_EXPIRY_SECONDS: int = Field(default=900, description="Magic-link token validity in seconds")
    TRUSTED_PROXIES: str = Field(
        default="",
        description="Comma-separated proxy IPs/CIDRs whose X-Forwarded-For is trusted. Empty = trust none (use socket peer)."
    )
    GEOIP_DB_PATH: Optional[str] = Field(
        default=None,
        description="Path to a MaxMind GeoLite2-Country.mmdb. If unset/absent, country resolution is skipped (no third-party IP lookups)."
    )
    DATA_RETENTION_DAYS: int = Field(
        default=0,
        description="Delete analytics events older than this many days (0 = keep forever). Applied nightly."
    )
    EMAIL_LOG_RETENTION_DAYS: int = Field(
        default=90,
        description="Delete email_logs rows (they contain recipient addresses) older than this many days."
    )
    # Database
    DATABASE_URL: str = Field(
        default="postgresql://argusmetrics:argusmetrics@localhost/argusmetrics",
        description="PostgreSQL database URL"
    )
    DB_POOL_SIZE: int = Field(default=5, description="Database connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=10, description="Database max overflow connections")
    DB_POOL_PRE_PING: bool = Field(default=True, description="Enable connection health checks")
    DB_ECHO: bool = Field(default=False, description="Enable SQLAlchemy query logging")

    # CORS
    CORS_ORIGINS: str = Field(
        default="*",
        description="Allowed CORS origins (comma-separated or * for all)"
    )
    CORS_ALLOW_CREDENTIALS: bool = Field(default=False, description="Allow credentials in CORS")
    CORS_ALLOW_METHODS: List[str] = Field(default=["*"], description="Allowed HTTP methods")
    CORS_ALLOW_HEADERS: List[str] = Field(default=["*"], description="Allowed HTTP headers")

    # Email Settings (for notifications, password reset, etc.)
    EMAIL_BACKEND: str = Field(default="lettermint", description="Email backend: 'lettermint' or 'smtp'")

    # Lettermint Settings (EU-based email service)
    LETTERMINT_API_KEY: Optional[str] = Field(default=None, description="Lettermint API key")
    LETTERMINT_API_URL: str = Field(default="https://api.lettermint.co/v1/send", description="Lettermint API endpoint")
    LETTERMINT_FROM_EMAIL: str = Field(default="noreply@argusmetrics.io", description="From email address")
    LETTERMINT_FROM_NAME: str = Field(default="Argusmetrics", description="From name")

    # SMTP Settings (fallback)
    SMTP_HOST: Optional[str] = Field(default=None, description="SMTP server host")
    SMTP_PORT: int = Field(default=587, description="SMTP server port")
    SMTP_USER: Optional[str] = Field(default=None, description="SMTP username")
    SMTP_PASSWORD: Optional[str] = Field(default=None, description="SMTP password")
    SMTP_FROM_EMAIL: str = Field(default="noreply@argusmetrics.io", description="From email address")
    SMTP_FROM_NAME: str = Field(default="Argusmetrics", description="From name")
    SMTP_USE_TLS: bool = Field(default=True, description="Use TLS for SMTP")

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = Field(default=True, description="Enable rate limiting")
    RATE_LIMIT_PER_MINUTE: int = Field(default=60, description="Requests per minute per IP")
    RATE_LIMIT_PER_HOUR: int = Field(default=1000, description="Requests per hour per IP")
    RATE_LIMIT_PER_DAY: int = Field(default=10000, description="Requests per day per IP")
    # Signup, login, verification and password reset, throttled harder than the
    # rest because they are what a brute-force or email-bombing run targets.
    # Configurable so an end-to-end suite, which drives dozens of signups from
    # one address, can raise it without the limiter being removed from the code
    # it is meant to protect. test_auth_rate_limit proves it still works.
    # "memory" counts per process, which is correct for a single worker and
    # wrong for several. See app/middleware/rate_limit.py.
    RATE_LIMIT_BACKEND: str = Field(
        default="memory", description="Rate limiter backend: 'memory' today"
    )
    AUTH_RATE_LIMIT_ATTEMPTS: int = Field(
        default=10, description="Auth attempts allowed per IP per window"
    )
    AUTH_RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=300, description="Window for AUTH_RATE_LIMIT_ATTEMPTS"
    )

    # Analytics & Monitoring
    SENTRY_DSN: Optional[str] = Field(default=None, description="Sentry DSN for error tracking")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # Feature Flags
    ENABLE_REGISTRATION: bool = Field(default=True, description="Enable user registration")
    ENABLE_EMAIL_VERIFICATION: bool = Field(default=False, description="Require email verification")
    ENABLE_ANALYTICS: bool = Field(default=True, description="Enable analytics tracking")

    # E2E Testing (allows test emails to get verify_url without DEBUG mode)
    E2E_TEST_SECRET: Optional[str] = Field(default=None, description="Secret for E2E tests to get verify_url for @test.argusmetrics.io emails")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        """Get CORS origins as a list."""
        if isinstance(self.CORS_ORIGINS, str):
            return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
        return self.CORS_ORIGINS

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def validate_database_url(cls, v):
        """Ensure database URL uses postgresql:// scheme."""
        if v and v.startswith("postgres://"):
            # Convert postgres:// to postgresql:// for SQLAlchemy 1.4+
            return v.replace("postgres://", "postgresql://", 1)
        return v

    @property
    def sqlalchemy_database_uri(self) -> str:
        """Get SQLAlchemy-compatible database URI."""
        return self.DATABASE_URL

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return not self.DEBUG and "localhost" not in self.BASE_URL


# Global settings instance
settings = Settings()
