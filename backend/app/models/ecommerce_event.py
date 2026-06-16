"""
E-commerce event model for revenue tracking.

Tracks purchase events, product views, cart additions, and revenue data.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, DECIMAL, Index, CheckConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base


class EcommerceEvent(Base):
    """
    E-commerce event model for tracking revenue and product interactions.

    Supports various e-commerce events like product views, cart additions,
    checkout initiation, and purchases with full revenue tracking.

    Attributes:
        id: Primary key
        website_id: Foreign key to website
        event_type: Type of e-commerce event
        event_name: Custom event name
        transaction_id: Unique transaction identifier (for purchases)
        revenue: Transaction revenue amount
        currency: ISO 4217 currency code (e.g., 'USD', 'EUR', 'SEK')
        tax: Tax amount
        shipping: Shipping cost
        product_id: Product SKU or ID
        product_name: Product name
        product_category: Product category
        product_brand: Product brand
        product_variant: Product variant (size, color, etc.)
        quantity: Product quantity
        price: Product price
        properties: Additional custom properties (JSONB)
        visitor_hash: Hashed visitor identifier
        country: Visitor's country code
        device_type: Device type (desktop/mobile/tablet)
        browser: Browser name
        timestamp: Event timestamp
        utm_source: UTM source parameter
        utm_medium: UTM medium parameter
        utm_campaign: UTM campaign parameter
        utm_content: UTM content parameter
        utm_term: UTM term parameter
    """

    __tablename__ = "ecommerce_events"

    id = Column(Integer, primary_key=True, index=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False, index=True)

    # Event details
    event_type = Column(String(50), nullable=False, index=True)
    event_name = Column(String(255), nullable=False)

    # Transaction details
    transaction_id = Column(String(255), nullable=True, index=True)

    # Revenue data
    revenue = Column(DECIMAL(15, 2), nullable=True)
    currency = Column(String(3), nullable=False, default='USD', index=True)
    tax = Column(DECIMAL(15, 2), nullable=True)
    shipping = Column(DECIMAL(15, 2), nullable=True)

    # Product details
    product_id = Column(String(255), nullable=True, index=True)
    product_name = Column(String(500), nullable=True)
    product_category = Column(String(255), nullable=True)
    product_brand = Column(String(255), nullable=True)
    product_variant = Column(String(255), nullable=True)
    quantity = Column(Integer, nullable=True, default=1)
    price = Column(DECIMAL(15, 2), nullable=True)

    # Additional context
    properties = Column(JSONB, nullable=True)

    # Visitor tracking
    visitor_hash = Column(String(64), nullable=False, index=True)

    # Location & device
    country = Column(String(2), nullable=True, index=True)
    device_type = Column(String(50), nullable=True, index=True)
    browser = Column(String(100), nullable=True)

    # Timing
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    # Marketing attribution
    utm_source = Column(String(255), nullable=True)
    utm_medium = Column(String(255), nullable=True)
    utm_campaign = Column(String(255), nullable=True)
    utm_content = Column(String(255), nullable=True)
    utm_term = Column(String(255), nullable=True)

    # Composite indexes for common query patterns
    __table_args__ = (
        Index('idx_ecommerce_website_timestamp', 'website_id', 'timestamp'),
        Index('idx_ecommerce_revenue_queries', 'website_id', 'event_type', 'timestamp'),
        # Idempotency: a (website, transaction_id) purchase can only be recorded
        # once, so forged/duplicate purchase events can't inflate revenue.
        Index(
            'uq_ecommerce_purchase_txn', 'website_id', 'transaction_id',
            unique=True,
            postgresql_where=text("event_type = 'purchase' AND transaction_id IS NOT NULL"),
        ),
        CheckConstraint('revenue IS NULL OR revenue >= 0', name='ecommerce_revenue_positive'),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name='ecommerce_currency_valid'),
        CheckConstraint(
            "event_type IN ('view_item', 'add_to_cart', 'remove_from_cart', 'begin_checkout', 'add_payment_info', 'add_shipping_info', 'purchase', 'refund')",
            name='ecommerce_event_type_valid'
        ),
    )

    def __repr__(self) -> str:
        return f"<EcommerceEvent(id={self.id}, type='{self.event_type}', product='{self.product_name}', revenue={self.revenue})>"

    def to_dict(self):
        """Convert event to dictionary for API responses."""
        return {
            'id': self.id,
            'website_id': self.website_id,
            'event_type': self.event_type,
            'event_name': self.event_name,
            'transaction_id': self.transaction_id,
            'revenue': float(self.revenue) if self.revenue else None,
            'currency': self.currency,
            'tax': float(self.tax) if self.tax else None,
            'shipping': float(self.shipping) if self.shipping else None,
            'product_id': self.product_id,
            'product_name': self.product_name,
            'product_category': self.product_category,
            'product_brand': self.product_brand,
            'product_variant': self.product_variant,
            'quantity': self.quantity,
            'price': float(self.price) if self.price else None,
            'properties': self.properties,
            'visitor_hash': self.visitor_hash,
            'country': self.country,
            'device_type': self.device_type,
            'browser': self.browser,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'utm_source': self.utm_source,
            'utm_medium': self.utm_medium,
            'utm_campaign': self.utm_campaign,
            'utm_content': self.utm_content,
            'utm_term': self.utm_term,
        }
