"""
Email reports configuration API routes.

Provides endpoints for managing automated email analytics reports.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional

from app.database import get_db
from app.routers.auth import get_current_user
from app.models.user import User
from app.models.website import Website
from app.services.team_service import TeamService
from app.services.email_reports_service import EmailReportsService
from app.models.website_member import MemberRole
import logging

from app.utils.security import mask_email
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/email-reports", tags=["Email Reports"])


# ============================================================================
# Request/Response Models
# ============================================================================

class EmailReportsConfigRequest(BaseModel):
    """Request model for configuring email reports."""
    website_id: int
    enabled: bool
    recipient: Optional[EmailStr] = None
    frequency: Optional[str] = "weekly"  # "weekly" or "monthly"
    day: Optional[int] = 1  # 1-7 for weekly (Mon-Sun), 1-31 for monthly

    class Config:
        json_schema_extra = {
            "example": {
                "website_id": 1,
                "enabled": True,
                "recipient": "reports@example.com",
                "frequency": "weekly",
                "day": 1
            }
        }


class SendTestReportRequest(BaseModel):
    """Request model for sending a test report."""
    website_id: int

    class Config:
        json_schema_extra = {
            "example": {
                "website_id": 1
            }
        }


# ============================================================================
# Email Reports Endpoints
# ============================================================================

@router.post("/configure")
async def configure_email_reports(
    request: EmailReportsConfigRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Configure automated email reports for a website.

    Requires: User must be website OWNER or ADMIN.

    Settings:
    - enabled: Turn reports on/off
    - recipient: Email address to send reports to
    - frequency: "weekly" or "monthly"
    - day: Day to send (1-7 for weekly Mon-Sun, 1-31 for monthly)
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
                detail="You need owner or admin access to configure email reports"
            )

        # Validate settings
        if request.enabled and not request.recipient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Recipient email is required when enabling reports"
            )

        if request.frequency not in ["weekly", "monthly"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Frequency must be 'weekly' or 'monthly'"
            )

        if request.frequency == "weekly" and (request.day < 1 or request.day > 7):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="For weekly reports, day must be 1-7 (Monday-Sunday)"
            )

        if request.frequency == "monthly" and (request.day < 1 or request.day > 31):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="For monthly reports, day must be 1-31"
            )

        # Update website settings
        website.email_reports_enabled = request.enabled
        website.email_reports_recipient = request.recipient
        website.email_reports_frequency = request.frequency if request.enabled else None
        website.email_reports_day = request.day if request.enabled else None

        db.commit()

        logger.info(f"Email reports configured for website {website.id} by {mask_email(current_user.email)}")

        return {
            "success": True,
            "message": f"Email reports {'enabled' if request.enabled else 'disabled'}",
            "config": {
                "enabled": website.email_reports_enabled,
                "recipient": website.email_reports_recipient,
                "frequency": website.email_reports_frequency,
                "day": website.email_reports_day
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error configuring email reports: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to configure email reports"
        )


@router.get("/config/{website_id}")
async def get_email_reports_config(
    website_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get email reports configuration for a website.

    Requires: User must have access to the website.
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
            "config": {
                "enabled": website.email_reports_enabled,
                "recipient": website.email_reports_recipient,
                "frequency": website.email_reports_frequency,
                "day": website.email_reports_day
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting email reports config: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get email reports configuration"
        )


@router.post("/send-test")
async def send_test_report(
    request: SendTestReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Send a test email report immediately.

    Requires: User must be website OWNER or ADMIN.

    This allows users to test their email reports configuration before
    waiting for the scheduled send.
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
                detail="You need owner or admin access to send test reports"
            )

        # Check if email reports are configured
        if not website.email_reports_enabled or not website.email_reports_recipient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email reports must be configured before sending a test"
            )

        # Send report
        reports_service = EmailReportsService(db)
        success = reports_service.send_report(website.id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send test report - check logs for details"
            )

        logger.info(f"Test email report sent for website {website.id} by {mask_email(current_user.email)}")

        return {
            "success": True,
            "message": f"Test report sent to {website.email_reports_recipient}",
            "recipient": website.email_reports_recipient
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending test report: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send test report"
        )


@router.post("/disable/{website_id}")
async def disable_email_reports(
    website_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Disable email reports for a website.

    Requires: User must be website OWNER or ADMIN.

    Quick way to turn off reports without losing configuration.
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
        user_role = team_service.check_website_access(current_user.email, website_id)

        if not user_role or user_role not in [MemberRole.OWNER, MemberRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You need owner or admin access to disable email reports"
            )

        # Disable reports
        website.email_reports_enabled = False
        db.commit()

        logger.info(f"Email reports disabled for website {website_id} by {mask_email(current_user.email)}")

        return {
            "success": True,
            "message": "Email reports disabled",
            "enabled": False
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error disabling email reports: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disable email reports"
        )
