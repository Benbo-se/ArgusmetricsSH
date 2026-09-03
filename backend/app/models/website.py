"""
Website model for analytics tracking configuration.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from app.database import Base


class Website(Base):
    """
    Website model for storing analytics tracking configuration.

    Attributes:
        id: Primary key
        name: Website name/label
        domain: Website domain (unique)
        user_email: Foreign key to owner's email
        tracking_code: Unique tracking code for analytics (indexed)
        created_at: Timestamp when website was added
        updated_at: Timestamp when website was last updated
        is_active: Whether tracking is active for this website
        is_public: Whether public dashboard is enabled
        public_share_token: Unique token for public dashboard access
    """

    __tablename__ = "websites"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    domain = Column(String(255), unique=True, nullable=False, index=True)
    user_email = Column(String(255), ForeignKey("users.email", ondelete="CASCADE"), nullable=False, index=True)
    tracking_code = Column(String(255), unique=True, nullable=False, index=True)
    verification_token = Column(String(64), unique=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False, index=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    is_active = Column(Boolean, default=True, nullable=False)

    # Email Reports Configuration
    email_reports_enabled = Column(Boolean, default=False, nullable=False, index=True)
    email_reports_frequency = Column(String(20), nullable=True)  # 'weekly' or 'monthly'
    email_reports_recipient = Column(String(255), nullable=True)
    email_reports_day = Column(Integer, nullable=True)  # 1-7 for weekly (Mon-Sun), 1-31 for monthly

    # Public Dashboard Configuration
    is_public = Column(Boolean, default=False, nullable=False)
    public_share_token = Column(String(32), unique=True, nullable=True, index=True)
    public_password_hash = Column(String(255), nullable=True)  # Password protection for public dashboards
    public_password_enabled = Column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<Website(name='{self.name}', domain='{self.domain}', active={self.is_active})>"
