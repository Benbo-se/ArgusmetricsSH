"""
Pageview model for storing analytics time-series data.

Scaling note: When pageview volume exceeds ~50M rows/year, consider
PostgreSQL native table partitioning (PARTITION BY RANGE on timestamp),
or TimescaleDB hypertables (the bundled image ships the extension).
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base


class Pageview(Base):
    """
    Pageview model for storing analytics events as time-series data.

    Stores analytics pageview events as time-series data in PostgreSQL.

    Attributes:
        id: Primary key
        website_id: Foreign key to website
        path: Page path/URL visited
        referrer: Referrer URL (where visitor came from)
        country: Visitor's country code (e.g., 'SE', 'NO', 'DK')
        device_type: Device type (e.g., 'desktop', 'mobile', 'tablet')
        browser: Browser name (e.g., 'Chrome', 'Firefox', 'Safari')
        visitor_hash: Hashed visitor identifier for unique visitor tracking
        timestamp: Timestamp of the pageview
        utm_source: UTM source parameter (e.g., 'google', 'newsletter')
        utm_medium: UTM medium parameter (e.g., 'cpc', 'email')
        utm_campaign: UTM campaign parameter (e.g., 'summer_sale')
        utm_content: UTM content parameter (e.g., 'banner_ad')
        utm_term: UTM term parameter (e.g., 'running_shoes')
        screen_width: Screen width in pixels
        screen_height: Screen height in pixels
        scroll_depth: Maximum scroll depth percentage (0-100)
        properties: Custom key-value properties (JSONB) for segmentation
    """

    __tablename__ = "pageviews"

    # Insert-heavy table: every index is a write tax, so single-column indexes
    # that are prefix-covered by the composites below (website_id, visitor_hash,
    # timestamp) or too low-cardinality to ever win (country, device, browser)
    # are deliberately absent.
    id = Column(Integer, primary_key=True, index=True)
    website_id = Column(Integer, ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)

    # Denormalised from websites.user_email so row-level security policies can
    # filter on an indexed column instead of joining through websites on every
    # row. Maintained by a database trigger, not by application code: this is a
    # security-relevant value, and a trigger cannot be forgotten by a new code
    # path or a manual fix over psql. Do not set it by hand.
    owner_email = Column(String(255), nullable=True, index=True)
    path = Column(String(2048), nullable=False)
    referrer = Column(String(2048), nullable=True)
    country = Column(String(2), nullable=True)
    device_type = Column(String(50), nullable=True)
    browser = Column(String(100), nullable=True)
    visitor_hash = Column(String(64), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # UTM parameters for campaign tracking
    utm_source = Column(String(255), nullable=True)
    utm_medium = Column(String(255), nullable=True)
    utm_campaign = Column(String(255), nullable=True)
    utm_content = Column(String(255), nullable=True)
    utm_term = Column(String(255), nullable=True)

    # Screen size tracking (Sprint 2)
    screen_width = Column(Integer, nullable=True)
    screen_height = Column(Integer, nullable=True)

    # Scroll depth tracking (Sprint 2) - max scroll percentage reached
    scroll_depth = Column(Integer, nullable=True)  # 0-100

    # Custom properties (Session 6) - for advanced filtering/segmentation
    properties = Column(JSONB, nullable=True)

    # Composite indexes for common query patterns
    __table_args__ = (
        Index('idx_pageviews_website_timestamp', 'website_id', 'timestamp'),
        Index('idx_pageviews_website_visitor', 'website_id', 'visitor_hash'),
        # "Top pages over a date range" is the most common dashboard query
        Index('idx_pageviews_website_path_time', 'website_id', 'path', 'timestamp'),
        Index('idx_pageviews_properties', 'properties', postgresql_using='gin'),
    )

    def __repr__(self) -> str:
        return f"<Pageview(website_id={self.website_id}, path='{self.path}', timestamp={self.timestamp})>"
