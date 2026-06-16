"""
AI Quota API router for checking and managing AI usage limits.

Provides endpoints for:
- GET /api/v1/ai/quota - Get current user's AI quota status
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict

from app.database import get_db
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.ai_quota_service import get_quota_info, AI_QUOTA_LIMITS

logger = logging.getLogger(__name__)
router = APIRouter(tags=["AI Quota"])


@router.get(
    "/quota",
    responses={
        200: {
            "description": "AI quota information for current user"
        },
        401: {
            "description": "Not authenticated"
        }
    }
)
async def get_ai_quota_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict:
    """
    Get AI quota status for the current authenticated user.

    Returns information about:
    - Current plan and quota limit
    - Messages used this month
    - Messages remaining
    - Quota reset date
    - Whether user has AI access
    - Whether quota is exceeded

    Args:
        current_user: Current authenticated user (from dependency)
        db: Database session

    Returns:
        dict: AI quota information

    Raises:
        HTTPException: 401 if not authenticated

    Example:
        GET /api/v1/ai/quota
        Authorization: Bearer <token>

        Response:
        {
            "plan": "pro",
            "quota": 1000,
            "used": 47,
            "remaining": 953,
            "reset_date": "2025-11-01T00:00:00Z",
            "has_access": true,
            "is_exceeded": false,
            "plan_limits": {
                "free": 0,
                "starter": 50,
                "pro": 1000,
                "business": 10000
            }
        }
    """
    logger.info(f"AI quota status request from user: {current_user.email}")

    try:
        # Get quota info for user
        quota_info = get_quota_info(current_user)

        # Add plan limits for reference
        quota_info["plan_limits"] = AI_QUOTA_LIMITS

        return quota_info

    except Exception as e:
        logger.error(f"Error getting AI quota status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve AI quota information"
        )


@router.get(
    "/plans",
    responses={
        200: {
            "description": "Available AI quota plans"
        }
    }
)
async def get_ai_plans() -> Dict:
    """
    Get available AI quota plans and their limits.

    Public endpoint that doesn't require authentication.
    Shows AI message quotas for each subscription tier.

    Returns:
        dict: Plan information with AI quotas

    Example:
        GET /api/v1/ai/plans

        Response:
        {
            "plans": {
                "free": {
                    "quota": 0,
                    "price": "Gratis",
                    "description": "Ingen AI-tillgång"
                },
                "starter": {
                    "quota": 50,
                    "price": "79 kr/månad",
                    "description": "50 AI-meddelanden per månad"
                },
                "pro": {
                    "quota": 1000,
                    "price": "199 kr/månad",
                    "description": "1,000 AI-meddelanden per månad"
                },
                "business": {
                    "quota": 10000,
                    "price": "499 kr/månad",
                    "description": "10,000 AI-meddelanden per månad"
                }
            }
        }
    """
    return {
        "plans": {
            "free": {
                "quota": AI_QUOTA_LIMITS["free"],
                "price": "Gratis",
                "description": "Ingen AI-tillgång"
            },
            "starter": {
                "quota": AI_QUOTA_LIMITS["starter"],
                "price": "79 kr/månad",
                "description": "50 AI-meddelanden per månad",
                "pageviews": "100,000 sidvisningar"
            },
            "pro": {
                "quota": AI_QUOTA_LIMITS["pro"],
                "price": "199 kr/månad",
                "description": "1,000 AI-meddelanden per månad",
                "pageviews": "500,000 sidvisningar"
            },
            "business": {
                "quota": AI_QUOTA_LIMITS["business"],
                "price": "499 kr/månad",
                "description": "10,000 AI-meddelanden per månad",
                "pageviews": "2,000,000 sidvisningar"
            }
        }
    }
