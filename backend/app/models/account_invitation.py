"""An invitation to an account of one's own (services/account_invites.py).

The migration says why these exist and why only a hash of the token is kept.
"""
from sqlalchemy import Column, DateTime, Index, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class AccountInvitation(Base):
    """One address the operator has let in.

    Attributes:
        email: Who it is for. The account is created for this address and no
            other, whoever opens the link
        token_hash: SHA-256 of the token in the link, hex
        invited_by: The operator who sent it
        expires_at: After this the link no longer works
        accepted_at: Set when it is used; it cannot be used again
    """

    __tablename__ = "account_invitations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    invited_by = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_account_invitations_email", "email"),)

    def __repr__(self) -> str:
        return f"<AccountInvitation {self.id}>"
