"""
Goal model for tracking custom conversion events.

Goals allow users to track specific events like signups, purchases, downloads, etc.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Goal(Base):
    """
    Goal model for defining trackable conversion events.

    Attributes:
        id: Primary key
        website_id: Foreign key to website
        name: Human-readable goal name (e.g., "Newsletter Signup")
        event_name: Event identifier used in tracking (e.g., "newsletter_signup")
        created_at: When the goal was created
    """

    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, index=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    event_name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    conversions = relationship("GoalConversion", back_populates="goal", cascade="all, delete-orphan")

    # Composite index for quick lookups
    __table_args__ = (
        Index('idx_goals_website_event', 'website_id', 'event_name'),
    )

    def __repr__(self) -> str:
        return f"<Goal(id={self.id}, name='{self.name}', event_name='{self.event_name}')>"


class GoalConversion(Base):
    """
    GoalConversion model for storing conversion events.

    Attributes:
        id: Primary key
        goal_id: Foreign key to goal
        website_id: Foreign key to website
        visitor_hash: Hashed visitor identifier
        timestamp: When the conversion happened
    """

    __tablename__ = "goal_conversions"

    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=False, index=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False, index=True)
    visitor_hash = Column(String(64), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    # Relationships
    goal = relationship("Goal", back_populates="conversions")

    # Composite indexes for common query patterns
    __table_args__ = (
        Index('idx_goal_conversions_website_timestamp', 'website_id', 'timestamp'),
        Index('idx_goal_conversions_goal_timestamp', 'goal_id', 'timestamp'),
    )

    def __repr__(self) -> str:
        return f"<GoalConversion(goal_id={self.goal_id}, visitor_hash='{self.visitor_hash[:8]}...', timestamp={self.timestamp})>"
