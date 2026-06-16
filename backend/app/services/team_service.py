"""
Team service for managing website team members and permissions.

Handles the business logic for:
- Checking website access and permissions
- Inviting team members
- Managing team member roles
- Accepting invitations
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.website_member import WebsiteMember, MemberRole, MemberStatus
from app.models.website import Website
from app.models.user import User
from app.services.email_service import email_service
from app.config import settings

logger = logging.getLogger(__name__)


class TeamService:
    """
    Service for handling team collaboration operations.

    This service manages team members, permissions, and invitations.
    """

    def __init__(self, db: Session):
        """
        Initialize team service with database session.

        Args:
            db: SQLAlchemy database session for database operations
        """
        self.db = db
        logger.debug("TeamService initialized")

    def check_website_access(self, user_email: str, website_id: int) -> Optional[MemberRole]:
        """
        Check if user has access to a website and return their role.

        Args:
            user_email: User's email address
            website_id: Website ID to check access for

        Returns:
            MemberRole if user has access, None otherwise

        Example:
            role = service.check_website_access("user@example.com", 1)
            if role:
                print(f"User has {role} access")
        """
        try:
            # First check if user is the website owner
            website = self.db.query(Website).filter(
                Website.id == website_id,
                Website.user_email == user_email
            ).first()

            if website:
                logger.debug(f"User {user_email} is OWNER of website {website_id}")
                return MemberRole.OWNER

            # Then check team membership
            member = self.db.query(WebsiteMember).filter(
                WebsiteMember.website_id == website_id,
                WebsiteMember.user_email == user_email,
                WebsiteMember.status == MemberStatus.ACTIVE
            ).first()

            if member:
                logger.debug(f"User {user_email} has {member.role} access to website {website_id}")
                return MemberRole(member.role)

            logger.debug(f"User {user_email} has no access to website {website_id}")
            return None

        except Exception as e:
            logger.error(f"Error checking website access: {e}", exc_info=True)
            return None

    def require_role(self, user_email: str, website_id: int, required_role: MemberRole) -> bool:
        """
        Check if user has at least the required role for a website.

        Role hierarchy: owner > admin > viewer

        Args:
            user_email: User's email address
            website_id: Website ID to check
            required_role: Minimum required role

        Returns:
            bool: True if user has sufficient permissions

        Raises:
            ValueError: If user doesn't have sufficient permissions

        Example:
            if service.require_role("user@example.com", 1, MemberRole.ADMIN):
                # User has admin or owner access
        """
        role = self.check_website_access(user_email, website_id)

        if not role:
            raise ValueError("You don't have access to this website")

        # Define role hierarchy
        role_hierarchy = {
            MemberRole.OWNER: 3,
            MemberRole.ADMIN: 2,
            MemberRole.VIEWER: 1
        }

        user_level = role_hierarchy.get(role, 0)
        required_level = role_hierarchy.get(required_role, 0)

        if user_level < required_level:
            raise ValueError(f"You need {required_role.value} role or higher for this action")

        return True

    def get_team_members(self, website_id: int, user_email: str) -> List[WebsiteMember]:
        """
        Get all team members for a website.

        Args:
            website_id: Website ID
            user_email: Email of user requesting (must have access)

        Returns:
            List[WebsiteMember]: List of team members

        Raises:
            ValueError: If user doesn't have access to website
        """
        # Verify access
        if not self.check_website_access(user_email, website_id):
            raise ValueError("You don't have access to this website")

        try:
            # Ensure owner has a WebsiteMember record (backfill for older websites)
            website = self.db.query(Website).filter(Website.id == website_id).first()
            if website:
                owner_member = self.db.query(WebsiteMember).filter(
                    WebsiteMember.website_id == website_id,
                    WebsiteMember.user_email == website.user_email,
                    WebsiteMember.role == MemberRole.OWNER,
                    WebsiteMember.status == MemberStatus.ACTIVE
                ).first()
                if not owner_member:
                    owner_member = WebsiteMember(
                        website_id=website_id,
                        user_email=website.user_email,
                        role=MemberRole.OWNER,
                        status=MemberStatus.ACTIVE,
                        invited_by=website.user_email,
                    )
                    self.db.add(owner_member)
                    self.db.commit()
                    logger.info(f"Backfilled owner membership for website {website_id}")

            members = self.db.query(WebsiteMember).filter(
                WebsiteMember.website_id == website_id,
                WebsiteMember.status.in_([MemberStatus.ACTIVE, MemberStatus.PENDING])
            ).order_by(
                WebsiteMember.role.desc(),  # Owners first
                WebsiteMember.invited_at.asc()
            ).all()

            logger.info(f"Retrieved {len(members)} team members for website {website_id}")
            return members

        except Exception as e:
            logger.error(f"Error getting team members: {e}", exc_info=True)
            raise

    def invite_member(self, website_id: int, inviter_email: str, invitee_email: str, role: MemberRole) -> Dict:
        """
        Invite a new team member to a website.

        Args:
            website_id: Website ID
            inviter_email: Email of user sending invitation (must be owner or admin)
            invitee_email: Email of person to invite
            role: Role to assign (admin or viewer)

        Returns:
            dict: Created member and invite details

        Raises:
            ValueError: If permissions insufficient or invitation invalid
        """
        # Verify inviter has permission (must be owner or admin)
        self.require_role(inviter_email, website_id, MemberRole.ADMIN)

        # Cannot invite as owner
        if role == MemberRole.OWNER:
            raise ValueError("Cannot invite users as owner. Transfer ownership instead.")

        # Cannot invite yourself
        if invitee_email.lower() == inviter_email.lower():
            raise ValueError("Cannot invite yourself to the team")

        # Check if user is already a member
        existing = self.db.query(WebsiteMember).filter(
            WebsiteMember.website_id == website_id,
            WebsiteMember.user_email == invitee_email,
        ).first()

        if existing:
            if existing.status == MemberStatus.ACTIVE:
                raise ValueError("User is already a team member")
            elif existing.status == MemberStatus.PENDING:
                raise ValueError("User already has a pending invitation")
            # REVOKED — re-invite by resetting the record

        # Get website details
        website = self.db.query(Website).filter(Website.id == website_id).first()
        if not website:
            raise ValueError("Website not found")

        try:
            # Generate secure invite token
            invite_token = secrets.token_urlsafe(32)

            if existing and existing.status == MemberStatus.REVOKED:
                # Re-invite: update the revoked record
                existing.role = role
                existing.invited_by = inviter_email
                existing.status = MemberStatus.PENDING
                existing.invite_token = invite_token
                existing.invited_at = datetime.now(timezone.utc)
                existing.accepted_at = None
                member = existing
            else:
                # Create new member record
                member = WebsiteMember(
                    website_id=website_id,
                    user_email=invitee_email,
                    role=role,
                    invited_by=inviter_email,
                    status=MemberStatus.PENDING,
                    invite_token=invite_token
                )
                self.db.add(member)

            self.db.commit()
            self.db.refresh(member)

            # Build invitation URL
            invite_url = f"{settings.BASE_URL}/accept-invite?token={invite_token}"

            # Send invitation email (don't fail the invite if email fails)
            email_sent = False
            try:
                email_sent = email_service.send_team_invitation(
                    to=invitee_email,
                    website_name=website.name,
                    website_domain=website.domain,
                    role=role.value,
                    invited_by=inviter_email,
                    invite_url=invite_url
                )
                if not email_sent:
                    logger.warning(f"Failed to send invitation email to {invitee_email}")
            except Exception as email_err:
                logger.warning(f"Email sending failed for invitation to {invitee_email}: {email_err}")

            logger.info(f"Team invitation created: {invitee_email} invited to website {website_id} as {role.value}")

            response = {
                "member": member,
                "message": f"Invitation sent to {invitee_email}",
                "email_sent": email_sent,
            }

            # Include invite URL if email failed or in dev/debug mode
            if not email_sent or settings.DEBUG or not email_service.lettermint_configured:
                response["invite_url"] = invite_url

            return response

        except IntegrityError as e:
            self.db.rollback()
            logger.error(f"Database integrity error inviting member: {e}")
            raise ValueError("User is already a member of this website")
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error inviting team member: {e}", exc_info=True)
            raise

    def remove_member(self, website_id: int, remover_email: str, member_email: str) -> bool:
        """
        Remove a team member from a website.

        Args:
            website_id: Website ID
            remover_email: Email of user removing member (must be owner or admin)
            member_email: Email of member to remove

        Returns:
            bool: True if removed successfully

        Raises:
            ValueError: If permissions insufficient or removal invalid
        """
        # Verify remover has permission
        self.require_role(remover_email, website_id, MemberRole.ADMIN)

        # Get member to remove
        member = self.db.query(WebsiteMember).filter(
            WebsiteMember.website_id == website_id,
            WebsiteMember.user_email == member_email,
            WebsiteMember.status != MemberStatus.REVOKED
        ).first()

        if not member:
            raise ValueError("Team member not found")

        # Cannot remove owner
        if member.role == MemberRole.OWNER:
            raise ValueError("Cannot remove owner. Transfer ownership first.")

        # Cannot remove yourself (use leave_team for that)
        if member_email.lower() == remover_email.lower():
            raise ValueError("Cannot remove yourself. Use leave team instead.")

        # Check permissions: admins can only remove viewers
        remover_role = self.check_website_access(remover_email, website_id)
        if remover_role == MemberRole.ADMIN and member.role == MemberRole.ADMIN:
            raise ValueError("Admins cannot remove other admins. Only owners can do that.")

        try:
            # Revoke membership
            member.status = MemberStatus.REVOKED
            self.db.commit()

            logger.info(f"Team member removed: {member_email} from website {website_id}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error removing team member: {e}", exc_info=True)
            raise

    def change_role(self, website_id: int, changer_email: str, member_email: str, new_role: MemberRole) -> WebsiteMember:
        """
        Change a team member's role.

        Args:
            website_id: Website ID
            changer_email: Email of user changing role (must be owner)
            member_email: Email of member to update
            new_role: New role to assign

        Returns:
            WebsiteMember: Updated member

        Raises:
            ValueError: If permissions insufficient or change invalid
        """
        # Only owners can change roles
        self.require_role(changer_email, website_id, MemberRole.OWNER)

        # Get member to update
        member = self.db.query(WebsiteMember).filter(
            WebsiteMember.website_id == website_id,
            WebsiteMember.user_email == member_email,
            WebsiteMember.status == MemberStatus.ACTIVE
        ).first()

        if not member:
            raise ValueError("Team member not found")

        # Cannot change owner's role (use transfer ownership for that)
        if member.role == MemberRole.OWNER:
            raise ValueError("Cannot change owner's role. Use transfer ownership instead.")

        # Cannot change to owner role
        if new_role == MemberRole.OWNER:
            raise ValueError("Cannot assign owner role. Use transfer ownership instead.")

        try:
            member.role = new_role
            self.db.commit()
            self.db.refresh(member)

            logger.info(f"Role changed: {member_email} now has {new_role.value} role on website {website_id}")
            return member

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error changing member role: {e}", exc_info=True)
            raise

    def get_invite_details(self, invite_token: str) -> Dict:
        """
        Get details about a pending invitation.

        Args:
            invite_token: Invitation token

        Returns:
            dict: Invitation details

        Raises:
            ValueError: If invitation not found or expired
        """
        try:
            member = self.db.query(WebsiteMember).filter(
                WebsiteMember.invite_token == invite_token,
                WebsiteMember.status == MemberStatus.PENDING
            ).first()

            if not member:
                raise ValueError("Invitation not found or already accepted")

            # Check if invitation expired (7 days)
            if member.invited_at < datetime.now(timezone.utc) - timedelta(days=7):
                raise ValueError("Invitation has expired. Please request a new one.")

            # Get website details
            website = self.db.query(Website).filter(Website.id == member.website_id).first()
            if not website:
                raise ValueError("Website not found")

            return {
                "website_name": website.name,
                "website_domain": website.domain,
                "role": member.role.value,
                "invited_by": member.invited_by
            }

        except Exception as e:
            logger.error(f"Error getting invite details: {e}", exc_info=True)
            raise

    def accept_invitation(self, invite_token: str, accepter_email: str) -> Dict:
        """
        Accept a team invitation.

        Args:
            invite_token: Invitation token
            accepter_email: Email of user accepting (must match invitation)

        Returns:
            dict: Acceptance details with website_id and role

        Raises:
            ValueError: If invitation invalid or email mismatch
        """
        try:
            member = self.db.query(WebsiteMember).filter(
                WebsiteMember.invite_token == invite_token,
                WebsiteMember.status == MemberStatus.PENDING
            ).first()

            if not member:
                raise ValueError("Invitation not found or already accepted")

            # Check if invitation expired
            if member.invited_at < datetime.now(timezone.utc) - timedelta(days=7):
                raise ValueError("Invitation has expired. Please request a new one.")

            # Verify email matches
            if member.user_email.lower() != accepter_email.lower():
                raise ValueError("This invitation was sent to a different email address")

            # Ensure user exists (create if doesn't)
            user = self.db.query(User).filter(User.email == accepter_email).first()
            if not user:
                # Create user account
                user = User(email=accepter_email, is_verified=True)
                self.db.add(user)
                logger.info(f"Created user account for {accepter_email} via team invitation")

            # Accept invitation
            member.status = MemberStatus.ACTIVE
            member.accepted_at = datetime.now(timezone.utc)
            member.invite_token = None  # Clear token after acceptance

            self.db.commit()
            self.db.refresh(member)

            logger.info(f"Invitation accepted: {accepter_email} joined website {member.website_id} as {member.role.value}")

            return {
                "message": "Invitation accepted successfully",
                "website_id": member.website_id,
                "role": member.role.value
            }

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error accepting invitation: {e}", exc_info=True)
            raise
