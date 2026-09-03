"""
User model for authentication and account management.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base


class User(Base):
    """
    User model for storing user account information.

    Attributes:
        id: Primary key
        email: User's email address (unique, indexed)
        is_verified: Whether the user has verified their email
        created_at: Timestamp when user was created
        updated_at: Timestamp when user was last updated
    """

    __tablename__ = "users"

    # Core fields
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<User(email='{self.email}', verified={self.is_verified})>"
