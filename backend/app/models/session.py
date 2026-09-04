"""
Session model for managing user authentication sessions.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from app.database import Base


class Session(Base):
    """
    Session model for storing user authentication sessions.

    Attributes:
        id: Primary key
        token: Session token (indexed for fast lookup)
        user_email: Foreign key to user's email
        expires_at: Timestamp when session expires
        created_at: Timestamp when session was created
    """

    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True)
    token = Column(String(255), unique=True, index=True, nullable=False)
    user_email = Column(String(255), ForeignKey("users.email", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Session(user_email='{self.user_email}', expires_at={self.expires_at})>"
