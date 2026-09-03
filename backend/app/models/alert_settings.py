"""
Alert Settings model for configuring traffic spike alerts.

Allows users to configure when they should receive alerts about unusual traffic.
"""
from sqlalchemy import Column, Integer, Float, Boolean, ForeignKey, String
from sqlalchemy.sql import func
from app.database import Base


class AlertSettings(Base):
    """
    Alert Settings model for traffic spike alerts configuration.

    Attributes:
        id: Primary key
        website_id: Foreign key to website (one-to-one relationship)
        spike_threshold: Multiplier for spike detection (e.g., 2.0 = 200% of typical)
        email_enabled: Whether to send email alerts
        alert_email: Email address to send alerts to
    """

    __tablename__ = "alert_settings"

    id = Column(Integer, primary_key=True, index=True)
    website_id = Column(Integer, ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    spike_threshold = Column(Float, nullable=False, default=2.0)  # 200% of typical
    email_enabled = Column(Boolean, nullable=False, default=True)
    alert_email = Column(String(255), nullable=False)

    def __repr__(self) -> str:
        return f"<AlertSettings(website_id={self.website_id}, threshold={self.spike_threshold}x)>"
