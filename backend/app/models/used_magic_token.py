"""
Tracks consumed magic-link token IDs (jti) so a magic link is single-use.

A magic link mints a session; without this, the same signed link could be
replayed within its validity window to mint unlimited sessions (a leaked link
in browser history / referrer / email forwarding = repeated account access).
"""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.database import Base


class UsedMagicToken(Base):
    """A magic-token jti that has already been redeemed."""

    __tablename__ = "used_magic_tokens"

    id = Column(Integer, primary_key=True)
    jti = Column(String(64), unique=True, index=True, nullable=False)
    used_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<UsedMagicToken(jti='{self.jti}')>"
