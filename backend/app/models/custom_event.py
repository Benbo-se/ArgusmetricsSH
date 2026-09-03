"""
Custom Event model for storing flexible event tracking with properties.

This allows tracking ANY event with custom properties (key-value pairs),
unlike Goals which track specific named conversions.

Example use case:
- Goal: Track "Newsletter Signup" conversions
- Custom Event: Track button_click with properties {button: 'CTA', color: 'blue', position: 'header'}
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base


class CustomEvent(Base):
    """
    Custom Event model for flexible event tracking with properties.

    Allows tracking any event with custom properties stored as JSONB.
    Properties are flexible key-value pairs that can vary per event.

    Attributes:
        id: Primary key
        website_id: Foreign key to website
        event_name: Name of the event (e.g., 'button_click', 'video_play')
        properties: JSONB field for custom key-value properties
        path: Page path where event occurred
        referrer: Referrer URL (optional)
        country: Visitor's country code (optional)
        device_type: Device type (desktop/mobile/tablet)
        browser: Browser name
        visitor_hash: Hashed visitor identifier for unique tracking
        timestamp: When the event occurred (indexed for time-series queries)

    Example:
        CustomEvent(
            event_name='button_click',
            properties={'button': 'signup', 'variant': 'blue', 'page': 'home'},
            path='/landing',
            ...
        )
    """

    __tablename__ = "custom_events"

    id = Column(Integer, primary_key=True, index=True)
    website_id = Column(Integer, ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True)

    # Denormalised from websites.user_email so row-level security policies can
    # filter on an indexed column instead of joining through websites on every
    # row. Maintained by a database trigger, not by application code: this is a
    # security-relevant value, and a trigger cannot be forgotten by a new code
    # path or a manual fix over psql. Do not set it by hand.
    owner_email = Column(String(255), nullable=True, index=True)
    event_name = Column(String(255), nullable=False, index=True)
    properties = Column(JSONB, nullable=True)  # Flexible key-value properties
    path = Column(String(2048), nullable=True)
    referrer = Column(String(2048), nullable=True)
    country = Column(String(2), nullable=True, index=True)
    device_type = Column(String(50), nullable=True)
    browser = Column(String(100), nullable=True)
    visitor_hash = Column(String(64), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    # Composite indexes for common query patterns. No cross-tenant
    # (event_name, timestamp) index: every real query is scoped by website_id.
    __table_args__ = (
        Index('idx_custom_events_website_timestamp', 'website_id', 'timestamp'),
        Index('idx_custom_events_website_event', 'website_id', 'event_name'),
        # Unique-visitor counts on events
        Index('idx_custom_events_website_visitor', 'website_id', 'visitor_hash'),
    )

    def __repr__(self) -> str:
        return f"<CustomEvent(website_id={self.website_id}, event='{self.event_name}', timestamp={self.timestamp})>"
