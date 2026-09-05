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
    # The nightly purge deletes in batches rather than one statement. The
    # first run after retention is enabled would otherwise be a single
    # transaction over every row the product has ever recorded.
    RETENTION_BATCH_SIZE: int = Field(
        default=10_000, description="Rows deleted per transaction by the retention purge"
    )
    RETENTION_MAX_ROWS_PER_RUN: int = Field(
        default=0,
        description="Cap per table per run (0 = no cap). Useful for the first run.",
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

    # CORS. There is deliberately no origin setting: the tracking endpoints
    # are called from every customer's website, so the origin is a wildcard,
    # and it is safe only because credentials are off. See main.py, where the
    # reasoning is written out in full. A CORS_ORIGINS setting used to exist
    # here and was read by nothing, while the compose file refused to start
    # without an ALLOWED_ORIGINS that reached no code at all.
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
    # Declared rather than inferred. Left unset, is_production falls back to
    # the old rule, so nothing changes for a deployment that does not set it.
    ENVIRONMENT: Optional[str] = Field(
        default=None,
        description="production | development | test. Decides is_production.",
    )
    # Per account, not per website: a pageview costs the same whichever
    # domain it came from, and splitting a blog, a shop and a landing page
    # across three domains is normal rather than three customers' worth of
    # usage. 0 disables the limit, which is what an instance serving only its
    # owner wants.
    MONTHLY_EVENT_LIMIT: int = Field(
        default=0, description="Events per account per month. 0 = no limit"
    )
    # Not a packaging lever, an abuse stop. High enough that nobody running
    # real sites meets it, low enough that a script hits it in seconds.
    MAX_WEBSITES_PER_ACCOUNT: int = Field(
        default=100, description="Websites one account may create"
    )
    # "text" for a person reading along while developing, "json" for a
    # deployment where the log is read by a machine first. See
    # app/logging_setup.py.
    LOG_FORMAT: str = Field(default="text", description="Log format: text | json")
    # "memory" counts per process, which is correct for a single worker and
    # wrong for several. See app/middleware/rate_limit.py.
    RATE_LIMIT_BACKEND: str = Field(
        default="memory", description="Rate limiter backend: 'memory' today"
    )
    # Signup, login, verification and password reset, throttled harder than the
    # rest because they are what a brute-force or email-bombing run targets.
    # Configurable so an end-to-end suite, which drives dozens of signups from
    # one address, can raise it without the limiter being removed from the code
    # it is meant to protect. test_auth_rate_limit proves it still works.
    AUTH_RATE_LIMIT_ATTEMPTS: int = Field(
        default=10, description="Auth attempts allowed per IP per window"
    )
    AUTH_RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=300, description="Window for AUTH_RATE_LIMIT_ATTEMPTS"
    )

    # Analytics & Monitoring
    # /metrics answers how much work the instance is doing, which is a
    # business number: pageviews per hour, how many websites, how many
    # accounts. Without a token the endpoint refuses, rather than defaulting
    # to open and relying on whoever set up the reverse proxy.
    METRICS_TOKEN: Optional[str] = Field(
        default=None,
        description="Bearer token for /metrics. Unset means the endpoint is off.",
    )
    SENTRY_DSN: Optional[str] = Field(default=None, description="Sentry DSN for error tracking")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # Feature Flags. Both are checked where the behaviour happens, and
    # test_feature_flags proves it: all three flags in this section were read
    # by nothing, and ENABLE_REGISTRATION=false closed nothing at all while
    # looking exactly like it had. A third, ENABLE_ANALYTICS, was removed
    # rather than wired, because switching it off only stopped the product
    # doing its job.
    ENABLE_REGISTRATION: bool = Field(
        default=True, description="Whether anyone may create an account"
    )
    # True by default. It was False while nothing read it, which meant
    # nothing; now that it is wired, False would silently make every new
    # account usable without proving the address. Turning it off has to be a
    # decision, and it is only safe on an instance with registration closed.
    ENABLE_EMAIL_VERIFICATION: bool = Field(
        default=True, description="Require email verification before an account works"
    )

    # E2E Testing (allows test emails to get verify_url without DEBUG mode)
    E2E_TEST_SECRET: Optional[str] = Field(default=None, description="Secret for E2E tests to get verify_url for @test.argusmetrics.io emails")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

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
        """Whether this process is serving real users.

        It decides whether TrustedHostMiddleware is installed, whether session
        cookies are Secure, whether the API docs are exposed, and whether the
        signup endpoint may ever hand back a verification link. Getting it
        wrong is not a small thing in either direction.

        ENVIRONMENT decides it when set, because a deployment should be able to
        say what it is rather than have it guessed.

        The fallback is the original rule, kept so existing deployments that
        set neither behave exactly as before: not DEBUG, and a BASE_URL that
        does not look local. That inference is why ENVIRONMENT existed as an
        undeclared variable being passed around and quietly ignored.
        """
        declared = (self.ENVIRONMENT or "").strip().lower()
        if declared in ("production", "prod"):
            return True
        if declared in ("development", "dev", "test", "testing", "ci", "staging"):
            return False

        return not self.DEBUG and "localhost" not in self.BASE_URL


#: Settings a person running their own instance is expected to set, or at
#: least to know exists. Everything here must appear in docker/.env.example
#: with an explanation, and must be forwarded by docker-compose.prod.yml: a
#: variable the compose file does not pass through does nothing at all, which
#: is a worse failure than an undocumented one because it looks like it worked.
#:
#: ENABLE_REGISTRATION is the reason this list exists. An instance exposed to
#: the internet with open signup, whose owner never knew the setting was there,
#: is a real problem rather than a documentation gap.
OPERATOR_SETTINGS = frozenset({
    # Identity and mode
    "APP_NAME", "BRAND_NAME", "BASE_URL", "ENVIRONMENT", "DEBUG",
    # Secrets and storage
    "SECRET_KEY", "DATABASE_URL",
    # Sessions and links
    "SESSION_EXPIRY_DAYS", "MAGIC_TOKEN_EXPIRY_SECONDS",
    # Network trust
    "TRUSTED_PROXIES", "GEOIP_DB_PATH",
    # Retention, which is a promise made in the privacy policy
    "DATA_RETENTION_DAYS", "RETENTION_BATCH_SIZE", "RETENTION_MAX_ROWS_PER_RUN",
    "EMAIL_LOG_RETENTION_DAYS",
    # Who may use the instance
    "ENABLE_REGISTRATION", "ENABLE_EMAIL_VERIFICATION",
    "MONTHLY_EVENT_LIMIT", "MAX_WEBSITES_PER_ACCOUNT",
    # Throttling
    "RATE_LIMIT_ENABLED", "RATE_LIMIT_PER_MINUTE", "RATE_LIMIT_PER_HOUR",
    "RATE_LIMIT_PER_DAY", "AUTH_RATE_LIMIT_ATTEMPTS",
    "AUTH_RATE_LIMIT_WINDOW_SECONDS",
    # Email delivery
    "EMAIL_BACKEND",
    "LETTERMINT_API_KEY", "LETTERMINT_FROM_EMAIL", "LETTERMINT_FROM_NAME",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
    "SMTP_FROM_EMAIL", "SMTP_FROM_NAME", "SMTP_USE_TLS",
    # Operations
    "LOG_LEVEL", "LOG_FORMAT", "SENTRY_DSN", "METRICS_TOKEN",
    "DB_POOL_SIZE", "DB_MAX_OVERFLOW",
})

#: Settings nobody deploying this should touch, listed rather than merely left
#: out. Together with OPERATOR_SETTINGS these must cover every field exactly,
#: which test_settings_are_documented enforces: a setting added later belongs
#: to neither set, the test fails, and somebody has to decide which it is.
#: That decision is the whole point. Leaving it undecided is how the gap in
#: issue #13 opened in the first place.
INTERNAL_SETTINGS = frozenset({
    # Protocol details. Changing these breaks clients, not deployments.
    "API_V1_PREFIX", "ALGORITHM", "ACCESS_TOKEN_EXPIRE_MINUTES",
    "LETTERMINT_API_URL",
    # CORS beyond the origin list: the app decides these, not the operator.
    "CORS_ALLOW_CREDENTIALS", "CORS_ALLOW_METHODS", "CORS_ALLOW_HEADERS",
    # Connection tuning with one sensible answer, and query logging that would
    # write every visitor's data to the log if switched on in a deployment.
    "DB_POOL_PRE_PING", "DB_ECHO",
    # Only one backend exists today. It becomes operator-facing the day a
    # second one does.
    "RATE_LIMIT_BACKEND",
    # Set by the test harness, never by a deployment.
    "E2E_TEST_SECRET",
})


# Global settings instance
settings = Settings()
