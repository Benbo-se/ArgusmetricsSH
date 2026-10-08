"""
Funnel tracking router for conversion analysis.

Provides endpoints for:
- POST /funnels - Create a new funnel
- GET /funnels - List all funnels for a website
- GET /funnels/{funnel_id}/stats - Get funnel conversion statistics
"""
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.funnel import (
    CreateFunnelRequest,
    FunnelResponse,
    FunnelStatsResponse
)
from app.models.funnel import Funnel
from app.models.website import Website
from app.models.user import User
from app.models.website_member import MemberRole
from app.routers.auth import get_current_user
from app.routers.analytics import get_current_user_or_token, _enforce_token_scope
from app.services.team_service import TeamService
from app.services.funnel_stats import funnel_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/funnels", tags=["funnels"])


@router.post("", response_model=FunnelResponse)
async def create_funnel(
    funnel_data: CreateFunnelRequest,
    website_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new conversion funnel for a website.

    Args:
        funnel_data: Funnel configuration with steps
        website_id: Website ID to create funnel for
        current_user: Authenticated user
        db: Database session

    Returns:
        FunnelResponse: Created funnel details

    Raises:
        HTTPException 404: If website not found
        HTTPException 403: If user doesn't own website
    """
    # Verify access and require admin or owner to create funnels
    team_service = TeamService(db)
    role = team_service.check_website_access(current_user.email, website_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found"
        )
    if role not in [MemberRole.OWNER, MemberRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You need admin or owner access to create funnels"
        )

    website = db.query(Website).filter(Website.id == website_id).first()

    # Convert steps to JSON format
    steps_json = [
        {"step": step.step, "name": step.name, "path": step.path}
        for step in funnel_data.steps
    ]

    # Create funnel
    funnel = Funnel(
        website_id=website_id,
        name=funnel_data.name,
        steps=steps_json,
        is_active=True
    )

    db.add(funnel)
    db.commit()
    db.refresh(funnel)

    logger.info(f"Funnel created: {funnel.name} (id={funnel.id}) for website {website.domain}")

    return funnel


@router.get("", response_model=List[FunnelResponse])
async def list_funnels(
    website_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all funnels for a website.

    Args:
        website_id: Website ID to list funnels for
        current_user: Authenticated user
        db: Database session

    Returns:
        List[FunnelResponse]: List of funnels

    Raises:
        HTTPException 404: If website not found
        HTTPException 403: If user doesn't own website
    """
    # Verify access (any role may view funnels)
    team_service = TeamService(db)
    role = team_service.check_website_access(current_user.email, website_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found"
        )

    # Get all active funnels
    funnels = db.query(Funnel).filter(
        Funnel.website_id == website_id,
        Funnel.is_active == True
    ).all()

    return funnels


@router.get("/{funnel_id}/stats", response_model=FunnelStatsResponse)
async def get_funnel_stats(
    funnel_id: int,
    days: int = 30,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_db)
):
    """
    Get conversion statistics for a funnel.

    Readable with an API token as well as a session (#112). The route carries
    no website id, so the token's scope can only be checked once the funnel
    is loaded; a funnel on another website answers 404, the same as one that
    does not exist, so a token cannot be used to find out which ids exist.

    Args:
        funnel_id: Funnel ID
        days: Number of days to analyze (default 30)
        current_user: Authenticated user
        db: Database session

    Returns:
        FunnelStatsResponse: Funnel conversion statistics

    Raises:
        HTTPException 404: If funnel not found
        HTTPException 403: If user doesn't own funnel's website
    """
    # Get funnel and verify ownership
    funnel = db.query(Funnel).filter(Funnel.id == funnel_id).first()

    if not funnel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Funnel not found"
        )

    _enforce_token_scope(current_user, funnel.website_id)

    # Verify access to the funnel's website (any role may view stats)
    team_service = TeamService(db)
    if not team_service.check_website_access(current_user.email, funnel.website_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    return FunnelStatsResponse(**funnel_stats(db, funnel, days))


@router.delete("/{funnel_id}")
async def delete_funnel(
    funnel_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a funnel.

    Args:
        funnel_id: Funnel ID to delete
        current_user: Authenticated user
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException 404: If funnel not found
        HTTPException 403: If user doesn't own funnel's website
    """
    # Get funnel and verify ownership
    funnel = db.query(Funnel).filter(Funnel.id == funnel_id).first()

    if not funnel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Funnel not found"
        )

    # Verify access and require admin or owner to delete funnels
    team_service = TeamService(db)
    role = team_service.check_website_access(current_user.email, funnel.website_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    if role not in [MemberRole.OWNER, MemberRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You need admin or owner access to delete funnels"
        )

    website = db.query(Website).filter(Website.id == funnel.website_id).first()

    # Soft delete by setting is_active to False
    funnel.is_active = False
    db.commit()

    logger.info(f"Funnel deleted: {funnel.name} (id={funnel.id}) for website {website.domain}")

    return {"message": "Funnel deleted successfully"}
