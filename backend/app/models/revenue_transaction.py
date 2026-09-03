"""
Revenue Transaction model for e-commerce tracking.

Tracks purchases and revenue from e-commerce sites with multi-currency support.
"""
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from app.database import Base


class RevenueTransaction(Base):
    """
    Revenue transaction model for e-commerce tracking.

    Attributes:
        id: Primary key
        website_id: Foreign key to websites table
        transaction_id: Unique transaction ID from e-commerce platform
        timestamp: When the transaction occurred
        amount: Transaction amount (in minor currency units, e.g., cents)
        currency: Currency code (USD, EUR, SEK, etc.)
        product_name: Product name (optional)
        product_id: Product ID (optional)
        visitor_id: Hashed visitor ID for attribution
        path: Page path where transaction occurred
        referrer: Referrer URL
        country: Country code from GeoIP
    """

    __tablename__ = "revenue_transactions"

    id = Column(Integer, primary_key=True, index=True)
    website_id = Column(Integer, ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_id = Column(String(255), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Amount stored in minor units (e.g., cents for USD)
    # So $19.99 would be stored as 1999
    amount = Column(Numeric(15, 2), nullable=False)
    currency = Column(String(3), default='USD', nullable=False)  # ISO 4217 currency code

    # Product details (optional)
    product_name = Column(String(500), nullable=True)
    product_id = Column(String(255), nullable=True)

    # Attribution
    visitor_id = Column(String(255), nullable=True, index=True)
    path = Column(String(2000), nullable=True)
    referrer = Column(String(2000), nullable=True)
    country = Column(String(2), nullable=True)

    # Composite index for website + timestamp queries
    __table_args__ = (
        Index('idx_revenue_website_timestamp', 'website_id', 'timestamp'),
    )

    def __repr__(self) -> str:
        return f"<RevenueTransaction(id={self.id}, website_id={self.website_id}, amount={self.amount}, currency='{self.currency}', transaction_id='{self.transaction_id}')>"
