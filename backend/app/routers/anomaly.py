"""
Anomaly Detection router for AI-powered traffic analysis.

Provides endpoint for detecting unusual patterns:
- GET /anomalies/{website_id} - Detect anomalies for a website
"""
import logging
from typing import List, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.website import Website
from app.routers.auth import get_current_user
from app.services.anomaly_detection_service import AnomalyDetectionService

from app.utils.security import mask_email
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


@router.get("/{website_id}")
async def detect_anomalies(
    website_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict:
    """
    Detect anomalies in website traffic.

    Uses AI-powered analysis to detect:
    - Traffic spikes
    - Geographic anomalies
    - Bot attacks
    - Referrer spam

    Args:
        website_id: Website ID to analyze
        current_user: Authenticated user
        db: Database session

    Returns:
        dict: Detected anomalies

    Raises:
        HTTPException 404: If website not found
        HTTPException 403: If user doesn't own website
        HTTPException 402: If AI quota exhausted

    Example Response:
        {
            "website_id": 123,
            "anomalies_detected": 2,
            "anomalies": [
                {
                    "type": "traffic_spike",
                    "severity": "high",
                    "current_pageviews": 500,
                    "baseline_avg": 100.5,
                    "spike_ratio": 4.98,
                    "message": "Traffic spike detected: 4x normal volume",
                    "timestamp": "2025-11-01T12:00:00Z"
                },
                {
                    "type": "bot_attack",
                    "severity": "high",
                    "visitor_count": 5,
                    "top_bot_pageviews": 75,
                    "message": "Potential bot attack: 5 visitors with >50 pageviews/hour",
                    "timestamp": "2025-11-01T12:00:00Z"
                }
            ],
            "ai_quota_used": 1,
            "ai_quota_remaining": 49
        }
    """
    logger.info(f"Anomaly detection request: website_id={website_id}, user={mask_email(current_user.email)}")

    # Verify website exists and user owns it (ownership is by email, not user_id)
    website = db.query(Website).filter(
        Website.id == website_id,
        Website.user_email == current_user.email
    ).first()

    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or access denied"
        )

    # Initialize anomaly detection service
    anomaly_service = AnomalyDetectionService(db)

    # Run anomaly detection
    anomalies = anomaly_service.run_all_detections(website_id, current_user)

    return {
        "website_id": website_id,
        "anomalies_detected": len(anomalies),
        "anomalies": anomalies,
    }
