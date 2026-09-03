"""
Website member model for team collaboration.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index, Enum as SQLEnum
from sqlalchemy.sql import func
from app.database import Base
import enum


class MemberRole(str, enum.Enum):
    """
    Roles for website team members.

    - OWNER: Full access, can delete website, manage team, change settings
    - ADMIN: Can view stats, manage goals, configure settings (cannot delete website or remove owner)
    - VIEWER: Read-only access to dashboard (no settings, no team management)
    """
    OWNER = "owner"
    ADMIN = "admin"
    VIEWER = "viewer"


class MemberStatus(str, enum.Enum):
    """
    Status of team member invitation/membership.

    - PENDING: Invitation sent but not accepted
    - ACTIVE: Invitation accepted, member has access
    - REVOKED: Access has been revoked by owner/admin
    """
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"


class WebsiteMember(Base):
    """
    Website member model for team collaboration.

    Attributes:
        id: Primary key
        website_id: Foreign key to websites table
        user_email: Email of team member
        role: Member role (owner, admin, viewer)
        invited_by: Email of user who sent invitation
        invited_at: Timestamp when invitation was sent
        accepted_at: Timestamp when invitation was accepted (nullable)
        status: Current status (pending, active, revoked)
        invite_token: Secure token for accepting invitation
    """

    __tablename__ = "website_members"

    id = Column(Integer, primary_key=True, index=True)
    website_id = Column(Integer, ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True)
    user_email = Column(String(255), nullable=False, index=True)
    role = Column(SQLEnum(MemberRole, values_callable=lambda x: [e.value for e in x], create_type=False), nullable=False, default=MemberRole.VIEWER)
    # SET NULL, not CASCADE: a membership must survive the inviter's account
    # being deleted (cascading here would silently revoke a colleague's access,
    # and a plain restrict made the inviter permanently undeletable).
    invited_by = Column(String(255), ForeignKey("users.email", ondelete="SET NULL"), nullable=True)
    invited_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(SQLEnum(MemberStatus, values_callable=lambda x: [e.value for e in x], create_type=False), nullable=False, default=MemberStatus.PENDING)
    invite_token = Column(String(64), unique=True, nullable=True, index=True)
    # Denormalised from websites.user_email so row-level security can police
    # this table without referencing websites, which would make the two
    # tables' policies reference each other and fail with "infinite recursion
    # detected in policy". Maintained by a trigger. Do not set it by hand.
    owner_email = Column(String(255), nullable=True, index=True)

    __table_args__ = (
        # Ensure one membership per user per website
        Index('idx_website_user_unique', 'website_id', 'user_email', unique=True),
    )

    def __repr__(self) -> str:
        return f"<WebsiteMember(website_id={self.website_id}, email='{self.user_email}', role='{self.role}', status='{self.status}')>"
