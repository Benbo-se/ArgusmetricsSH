"""
Dashboard password protection API routes.

Provides endpoints for managing password protection on public dashboards.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Header, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.routers.auth import get_current_user
from app.models.user import User
from app.models.website import Website
from app.services.password_service import PasswordService
from app.services.team_service import TeamService
from app.models.website_member import MemberRole
from app.middleware.rate_limit import rate_limiter
import logging

from app.utils.security import mask_email
from app.services.website_lookup import resolve_share_token
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/dashboard-password", tags=["Dashboard Password"])


# ============================================================================
# Request/Response Models
# ============================================================================

class SetPasswordRequest(BaseModel):
    """Request model for setting dashboard password."""
    website_id: int
    password: str

    class Config:
        json_schema_extra = {
            "example": {
                "website_id": 1,
                "password": "my_secure_password_123"
            }
        }


class RemovePasswordRequest(BaseModel):
    """Request model for removing dashboard password."""
    website_id: int

    class Config:
        json_schema_extra = {
            "example": {
                "website_id": 1
            }
        }


class VerifyPasswordRequest(BaseModel):
    """Request model for verifying dashboard password."""
    password: str

    class Config:
        json_schema_extra = {
            "example": {
                "password": "my_secure_password_123"
            }
        }


# ============================================================================
# Password Management Endpoints
# ============================================================================

@router.post("/set")
async def set_dashboard_password(
    request: SetPasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Set or update password protection for a public dashboard.

    Requires: User must be website OWNER or ADMIN.

    The password will be hashed before storage. Once set, visitors to the
    public dashboard will be required to enter this password.
    """
    try:
        # Get website
        website = db.query(Website).filter(Website.id == request.website_id).first()
        if not website:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Website not found"
            )

        # Check permissions - user must be owner or admin
        team_service = TeamService(db)
        user_role = team_service.check_website_access(current_user.email, request.website_id)

        if not user_role or user_role not in [MemberRole.OWNER, MemberRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You need owner or admin access to manage password protection"
            )

        # Validate password strength
        is_strong, error_msg = PasswordService.is_strong_password(request.password)
        if not is_strong:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

        # Hash password and save
        hashed_password = PasswordService.hash_password(request.password)
        website.public_password_hash = hashed_password
        website.public_password_enabled = True

        db.commit()

        logger.info(f"Password protection enabled for website {website.id} by {mask_email(current_user.email)}")

        return {
            "success": True,
            "message": "Password protection enabled for public dashboard",
            "website_id": website.id,
            "password_protected": True
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error setting dashboard password: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set dashboard password"
        )


@router.post("/remove")
async def remove_dashboard_password(
    request: RemovePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Remove password protection from a public dashboard.

    Requires: User must be website OWNER or ADMIN.

    After removal, the public dashboard will be accessible without a password
    (if public sharing is enabled).
    """
    try:
        # Get website
        website = db.query(Website).filter(Website.id == request.website_id).first()
        if not website:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Website not found"
            )

        # Check permissions
        team_service = TeamService(db)
        user_role = team_service.check_website_access(current_user.email, request.website_id)

        if not user_role or user_role not in [MemberRole.OWNER, MemberRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You need owner or admin access to manage password protection"
            )

        # Remove password protection
        website.public_password_hash = None
        website.public_password_enabled = False

        db.commit()

        logger.info(f"Password protection removed from website {website.id} by {mask_email(current_user.email)}")

        return {
            "success": True,
            "message": "Password protection removed from public dashboard",
            "website_id": website.id,
            "password_protected": False
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error removing dashboard password: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove dashboard password"
        )


@router.post("/verify/{share_token}")
async def verify_dashboard_password(
    share_token: str,
    request: VerifyPasswordRequest,
    http_request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Verify password for accessing a password-protected public dashboard.

    Public endpoint - no authentication required.
    Rate limited to 5 attempts per IP per share_token per 15 minutes.

    Returns a verification token if password is correct, which can be used
    to access the dashboard.
    """
    # Brute-force protection: 5 attempts per IP+share_token per 15 minutes.
    # get_client_ip honors forwarded headers ONLY from TRUSTED_PROXIES — the
    # old inline header parsing here let attackers rotate X-Forwarded-For to
    # reset the limiter on every request.
    from app.utils.network import get_client_ip
    client_ip = get_client_ip(http_request) if http_request else "unknown"

    rate_key = f"pwd:{client_ip}:{share_token}"
    if rate_limiter.is_rate_limited(rate_key, limit=5, window_seconds=900):
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Try again in 15 minutes."
        )

    try:
        # Find website by public share token
        # Anonymous viewer: resolved through a SECURITY DEFINER function that
        # returns only the fields a public dashboard needs, so this path never
        # has read access to websites. See app/services/website_lookup.py.
        website = resolve_share_token(db, share_token)

        if not website:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Public dashboard not found"
            )

        # Check if password protection is enabled
        if not website.public_password_enabled or not website.public_password_hash:
            # No password required
            return {
                "success": True,
                "message": "No password required",
                "password_required": False
            }

        # Verify password
        is_valid = PasswordService.verify_password(
            request.password,
            website.public_password_hash
        )

        if not is_valid:
            logger.info(f"Incorrect password for dashboard {website.id}")
            return {
                "success": False,
                "message": "Incorrect password",
                "password_required": True,
                "verified": False
            }

        logger.info(f"Correct password provided for dashboard {website.id}")

        return {
            "success": True,
            "message": "Password verified",
            "password_required": True,
            "verified": True
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying dashboard password: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify password"
        )


@router.get("/status/{website_id}")
async def get_password_status(
    website_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get password protection status for a website.

    Requires: User must have access to the website.

    Returns whether password protection is enabled and other related settings.
    """
    try:
        # Get website
        website = db.query(Website).filter(Website.id == website_id).first()
        if not website:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Website not found"
            )

        # Check permissions
        team_service = TeamService(db)
        if not team_service.check_website_access(current_user.email, website_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this website"
            )

        return {
            "success": True,
            "website_id": website.id,
            "password_protected": website.public_password_enabled,
            "is_public": website.is_public,
            "public_share_token": website.public_share_token if website.is_public else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting password status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get password status"
        )


@router.get("/check/{share_token}")
async def check_password_required(
    share_token: str,
    db: Session = Depends(get_db)
):
    """
    Check if a public dashboard requires a password.

    Public endpoint - no authentication required.

    Used by the frontend to determine if a password prompt should be shown.
    """
    try:
        # Find website by public share token
        # Anonymous viewer: resolved through a SECURITY DEFINER function that
        # returns only the fields a public dashboard needs, so this path never
        # has read access to websites. See app/services/website_lookup.py.
        website = resolve_share_token(db, share_token)

        if not website:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Public dashboard not found"
            )

        return {
            "success": True,
            "password_required": website.public_password_enabled,
            "website_name": website.name,
            "website_domain": website.domain
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking password requirement: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check password requirement"
        )
