"""
ProcessedStripeEvent model for Stripe webhook idempotency.

Stores the IDs of Stripe events that have already been processed so the
webhook handler can safely ignore duplicate deliveries (Stripe may send the
same event more than once).
"""
from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from app.database import Base


class ProcessedStripeEvent(Base):
    """
    Tracks Stripe webhook events that have already been handled.

    Attributes:
        event_id: Stripe event ID (primary key, indexed for fast lookup)
        processed_at: Timestamp when the event was processed
    """

    __tablename__ = "processed_stripe_events"

    event_id = Column(String(255), primary_key=True, index=True, nullable=False)
    processed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<ProcessedStripeEvent(event_id='{self.event_id}', processed_at={self.processed_at})>"
