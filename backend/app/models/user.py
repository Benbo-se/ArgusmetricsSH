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

    # Password login (bcrypt). Nullable: accounts from the magic-link-only era
    # set one via the reset flow.
    password_hash = Column(String(255), nullable=True)

    # Email verification via 6-digit code (complement to the magic link; the
    # code is typed on the /verify page). Stored hashed, limited attempts.
    pending_code_hash = Column(String(64), nullable=True)
    pending_code_expires_at = Column(DateTime(timezone=True), nullable=True)
    pending_code_attempts = Column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<User(email='{self.email}', verified={self.is_verified})>"
