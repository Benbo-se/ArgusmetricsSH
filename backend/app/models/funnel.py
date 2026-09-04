"""
Funnel models for tracking multi-step user journeys.

Allows tracking conversion funnels like:
1. Landing page -> Product page -> Checkout -> Thank you page
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, Index
from sqlalchemy.sql import func
from app.database import Base


class Funnel(Base):
    """
    Funnel definition model.

    Attributes:
        id: Primary key
        website_id: Foreign key to websites table
        name: Funnel name (e.g., "Checkout Flow")
        steps: JSON array of step definitions
        created_at: When funnel was created
        is_active: Whether funnel is actively tracking
    """

    __tablename__ = "funnels"

    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)

    # Steps stored as JSON array:
    # [{"step": 1, "name": "Landing", "path": "/"}, {"step": 2, "name": "Product", "path": "/product"}]
    steps = Column(JSON, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<Funnel(id={self.id}, name='{self.name}', website_id={self.website_id})>"


class FunnelEvent(Base):
    """
    Funnel event tracking model.

    Tracks when visitors progress through funnel steps.

    Attributes:
        id: Primary key
        funnel_id: Foreign key to funnels table
        visitor_id: Hashed visitor ID
        step_number: Which step in the funnel (1, 2, 3, etc.)
        step_name: Name of the step
        path: Page path visited
        timestamp: When the step was reached
        completed: Whether visitor completed entire funnel
        session_id: Session identifier for grouping
    """

    __tablename__ = "funnel_events"

    id = Column(Integer, primary_key=True)
    funnel_id = Column(Integer, ForeignKey("funnels.id", ondelete="CASCADE"), nullable=False, index=True)

    # Denormalised from websites.user_email so row-level security policies can
    # filter on an indexed column instead of joining through websites on every
    # row. Maintained by a database trigger, not by application code: this is a
    # security-relevant value, and a trigger cannot be forgotten by a new code
    # path or a manual fix over psql. Do not set it by hand.
    owner_email = Column(String(255), nullable=True, index=True)
    visitor_id = Column(String(255), nullable=False, index=True)
    step_number = Column(Integer, nullable=False)
    step_name = Column(String(255), nullable=False)
    path = Column(String(2000), nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed = Column(Boolean, default=False, nullable=False)
    session_id = Column(String(255), nullable=True, index=True)

    # Composite indexes for efficient queries
    __table_args__ = (
        Index('idx_funnel_visitor', 'funnel_id', 'visitor_id'),
        Index('idx_funnel_step', 'funnel_id', 'step_number'),
        Index('idx_funnel_timestamp', 'funnel_id', 'timestamp'),
        # Written by the tracking endpoints, which row-level security keeps
        # write-only. INSERT ... RETURNING needs the new row to be readable,
        # so take the id from the sequence beforehand instead.
        {"implicit_returning": False},
    )

    def __repr__(self) -> str:
        return f"<FunnelEvent(id={self.id}, funnel_id={self.funnel_id}, step={self.step_number}, visitor='{self.visitor_id}')>"
