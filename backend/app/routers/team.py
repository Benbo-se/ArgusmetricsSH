"""
Team management API routes for multi-user collaboration.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.routers.auth import get_current_user
from app.models.user import User
from app.models.website import Website
from app.models.website_member import WebsiteMember, MemberRole, MemberStatus
from app.services.team_service import TeamService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/team", tags=["team"])


# ============================================================================
# Request/Response Models
# ============================================================================

class InviteMemberRequest(BaseModel):
    """Request model for inviting a team member."""
    website_id: int
    email: EmailStr
    role: MemberRole

    class Config:
        json_schema_extra = {
            "example": {
                "website_id": 1,
                "email": "teammate@example.com",
                "role": "viewer"
            }
        }


class RemoveMemberRequest(BaseModel):
    """Request model for removing a team member."""
    website_id: int
    email: EmailStr

    class Config:
        json_schema_extra = {
            "example": {
                "website_id": 1,
                "email": "teammate@example.com"
            }
        }


class ChangeRoleRequest(BaseModel):
    """Request model for changing a member's role."""
    website_id: int
    email: EmailStr
    new_role: MemberRole

    class Config:
        json_schema_extra = {
            "example": {
                "website_id": 1,
                "email": "teammate@example.com",
                "new_role": "admin"
            }
        }


class AcceptInvitationRequest(BaseModel):
    """Request model for accepting an invitation."""
    invite_token: str

    class Config:
        json_schema_extra = {
            "example": {
                "invite_token": "abc123xyz789"
            }
        }


class TeamMemberResponse(BaseModel):
    """Response model for team member."""
    id: int
    user_email: str
    role: str
    status: str
    invited_by: str
    invited_at: datetime
    accepted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================================
# Team Management Endpoints
# ============================================================================

@router.get("/websites", response_model=List[dict])
async def get_user_websites(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all websites the current user has access to.

    Returns list of websites with the user's role for each.
    """
    try:
        team_service = TeamService(db)

        # Get all memberships for the user
        memberships = db.query(WebsiteMember).filter(
            WebsiteMember.user_email == current_user.email,
            WebsiteMember.status == MemberStatus.ACTIVE
        ).all()

        websites = []
        for member in memberships:
            website = db.query(Website).filter(Website.id == member.website_id).first()
            if website:
                websites.append({
                    "website_id": website.id,
                    "name": website.name,
                    "domain": website.domain,
                    "role": member.role.value,
                    "is_owner": member.role == MemberRole.OWNER,
                    "can_manage_team": member.role in [MemberRole.OWNER, MemberRole.ADMIN]
                })

        return websites

    except Exception as e:
        logger.error(f"Error getting user websites: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve websites"
        )


@router.get("/websites/{website_id}/members", response_model=List[TeamMemberResponse])
async def get_team_members(
    website_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all team members for a website.

    Requires: User must have access to the website.
    """
    try:
        team_service = TeamService(db)

        # Verify user has access
        if not team_service.check_website_access(current_user.email, website_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this website"
            )

        members = team_service.get_team_members(website_id, current_user.email)
        return members

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting team members: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve team members"
        )


@router.post("/invite")
async def invite_team_member(
    request: InviteMemberRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Invite a new team member to a website.

    Requires: User must be OWNER or ADMIN.

    Returns invitation details including invite URL if email is not configured.
    """
    # Free plan cannot invite team members
    if not current_user.plan or current_user.plan.lower() == 'free':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Team collaboration requires a paid plan. Upgrade to Starter or above to invite team members."
        )

    try:
        team_service = TeamService(db)
        result = team_service.invite_member(
            website_id=request.website_id,
            inviter_email=current_user.email,
            invitee_email=request.email,
            role=request.role
        )

        return {
            "success": True,
            "message": result["message"],
            "member": {
                "user_email": result["member"].user_email,
                "role": result["member"].role.value,
                "status": result["member"].status.value,
                "invited_at": result["member"].invited_at.isoformat()
            },
            **({"invite_url": result["invite_url"]} if "invite_url" in result else {})
        }

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error inviting team member: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send invitation"
        )


@router.delete("/remove")
async def remove_team_member(
    request: RemoveMemberRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Remove a team member from a website.

    Requires: User must be OWNER or ADMIN.
    - Admins can only remove viewers
    - Only owners can remove admins
    - Cannot remove the owner
    """
    try:
        team_service = TeamService(db)
        team_service.remove_member(
            website_id=request.website_id,
            remover_email=current_user.email,
            member_email=request.email
        )

        return {
            "success": True,
            "message": f"Team member {request.email} removed successfully"
        }

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error removing team member: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove team member"
        )


@router.put("/role")
async def change_member_role(
    request: ChangeRoleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Change a team member's role.

    Requires: User must be OWNER.
    Cannot change owner role (use transfer ownership instead).
    """
    try:
        team_service = TeamService(db)
        updated_member = team_service.change_role(
            website_id=request.website_id,
            changer_email=current_user.email,
            member_email=request.email,
            new_role=request.new_role
        )

        return {
            "success": True,
            "message": f"Role updated to {request.new_role.value}",
            "member": {
                "user_email": updated_member.user_email,
                "role": updated_member.role.value
            }
        }

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error changing member role: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change member role"
        )


@router.get("/invite/{invite_token}")
async def get_invitation_details(
    invite_token: str,
    db: Session = Depends(get_db)
):
    """
    Get details about a pending invitation.

    Public endpoint - no authentication required.
    Used when a user clicks an invitation link.
    """
    try:
        team_service = TeamService(db)
        details = team_service.get_invite_details(invite_token)

        return {
            "success": True,
            **details
        }

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting invitation details: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve invitation"
        )


@router.post("/accept")
async def accept_invitation(
    request: AcceptInvitationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Accept a team invitation.

    User must be authenticated and the invitation must be for their email.
    """
    try:
        team_service = TeamService(db)
        result = team_service.accept_invitation(
            invite_token=request.invite_token,
            accepter_email=current_user.email
        )

        return {
            "success": True,
            **result
        }

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error accepting invitation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to accept invitation"
        )


@router.get("/pending")
async def get_pending_invitations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all pending invitations for the current user.
    """
    try:
        from app.models.website import Website

        # Get all pending invitations for this user
        pending = db.query(WebsiteMember, Website).join(
            Website, WebsiteMember.website_id == Website.id
        ).filter(
            WebsiteMember.user_email == current_user.email,
            WebsiteMember.status == MemberStatus.PENDING
        ).all()

        invitations = []
        for member, website in pending:
            invitations.append({
                "website_id": website.id,
                "website_name": website.name,
                "website_domain": website.domain,
                "role": member.role.value,
                "invited_by": member.invited_by,
                "invited_at": member.invited_at.isoformat(),
                "invite_token": member.invite_token
            })

        return {
            "success": True,
            "invitations": invitations
        }

    except Exception as e:
        logger.error(f"Error getting pending invitations: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve pending invitations"
        )
