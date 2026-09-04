"""
API Token model for programmatic access to analytics data.

Allows users to create API tokens for accessing their analytics data
from external applications or scripts.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from app.database import Base


class ApiToken(Base):
    """
    API Token model for programmatic API access.

    Attributes:
        id: Primary key
        website_id: Foreign key to website this token is for
        name: Human-readable token name (e.g., "Production Server")
        token: The actual token string (64 chars, hashed)
        created_at: When the token was created
        last_used_at: When the token was last used (for tracking)
    """

    __tablename__ = "api_tokens"

    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    token = Column(String(128), nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Index for fast token lookups
    __table_args__ = (
        # No index on token here: unique=True on the column already creates
        # ix_api_tokens_token, which enforces uniqueness and serves the lookup
        # by hash. A second, non-unique index on the same column only cost
        # write time.
    )

    def __repr__(self) -> str:
        return f"<ApiToken(id={self.id}, name='{self.name}', website_id={self.website_id})>"
