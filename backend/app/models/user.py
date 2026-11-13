"""
User model for authentication and account management.
"""
from sqlalchemy import BigInteger, Column, Integer, String, Boolean, DateTime, Text
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
    id = Column(Integer, primary_key=True)
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
    pending_code_attempts = Column(Integer, default=0, server_default="0", nullable=False)

    # Set on every login. Sessions cannot stand in for this: logging out
    # deletes the row, so a session only records a login while it is open.
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # Two-factor authentication (services/two_factor.py). The secret is
    # encrypted, and it only counts once totp_enabled_at is set: a secret
    # with no totp_enabled_at is an enrolment somebody started and has not
    # proved yet, and sign-in ignores it. totp_last_step is the last time
    # step a code was accepted for, so a code cannot be used twice.
    totp_secret_enc = Column(Text, nullable=True)
    totp_enabled_at = Column(DateTime(timezone=True), nullable=True)
    totp_last_step = Column(BigInteger, nullable=True)
    totp_failed_attempts = Column(Integer, default=0, server_default="0", nullable=False)
    totp_locked_until = Column(DateTime(timezone=True), nullable=True)

    @property
    def two_factor_enabled(self) -> bool:
        """Whether signing in to this account needs a second factor.

        Decided by totp_enabled_at alone. Also asking for a secret would mean
        that a row which lost its secret signs in with the password only,
        which is the wrong direction to fail in.
        """
        return self.totp_enabled_at is not None

    def __repr__(self) -> str:
        return f"<User(email='{self.email}', verified={self.is_verified})>"
