"""
Funnel tracking router for conversion analysis.

Provides endpoints for:
- POST /funnels - Create a new funnel
- GET /funnels - List all funnels for a website
- GET /funnels/{funnel_id}/stats - Get funnel conversion statistics
"""
import logging
from typing import List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.schemas.funnel import (
    CreateFunnelRequest,
    FunnelResponse,
    FunnelStatsResponse
)
from app.models.funnel import Funnel, FunnelEvent
from app.models.website import Website
from app.models.user import User
from app.models.website_member import MemberRole
from app.routers.auth import get_current_user
from app.services.team_service import TeamService

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get conversion statistics for a funnel.

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

    # Verify access to the funnel's website (any role may view stats)
    team_service = TeamService(db)
    if not team_service.check_website_access(current_user.email, funnel.website_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Calculate date range
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    # Get total unique visitors who entered the funnel (step 1)
    total_visitors = db.query(func.count(func.distinct(FunnelEvent.visitor_id))).filter(
        FunnelEvent.funnel_id == funnel_id,
        FunnelEvent.step_number == 1,
        FunnelEvent.timestamp >= start_date
    ).scalar() or 0

    # Get conversion stats for each step
    step_stats = []
    for step in funnel.steps:
        step_number = step['step']
        step_name = step['name']

        # Count unique visitors who reached this step
        visitors_at_step = db.query(func.count(func.distinct(FunnelEvent.visitor_id))).filter(
            FunnelEvent.funnel_id == funnel_id,
            FunnelEvent.step_number == step_number,
            FunnelEvent.timestamp >= start_date
        ).scalar() or 0

        # Calculate conversion rate (percentage of total visitors)
        conversion_rate = (visitors_at_step / total_visitors * 100) if total_visitors > 0 else 0

        step_stats.append({
            "step": step_number,
            "name": step_name,
            "visitors": visitors_at_step,
            "conversion_rate": round(conversion_rate, 2)
        })

    return FunnelStatsResponse(
        funnel_id=funnel.id,
        funnel_name=funnel.name,
        total_visitors=total_visitors,
        steps=step_stats
    )


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
