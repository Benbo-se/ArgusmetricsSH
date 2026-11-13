"""
Recovery codes for two-factor authentication.

Each row is one single-use code, stored only as a SHA-256. The codes are the
way in for someone who has lost the device that generates their sign-in codes,
so a copy of this table must not be a list of working ones.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class TwoFactorRecoveryCode(Base):
    """One recovery code. used_at is set the moment it is accepted."""

    __tablename__ = "two_factor_recovery_codes"

    id = Column(Integer, primary_key=True)
    user_email = Column(
        String(255), ForeignKey("users.email", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    code_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<TwoFactorRecoveryCode(user_email='{self.user_email}', "
            f"used={self.used_at is not None})>"
        )
