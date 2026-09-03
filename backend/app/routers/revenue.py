"""
Revenue tracking router for e-commerce analytics.

Provides endpoints for:
- POST /track - Track a revenue transaction
- GET /{website_id} - Get revenue statistics
- GET /{website_id}/products - Get top products
- GET /{website_id}/chart - Get revenue over time
"""
import logging
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from decimal import Decimal
from app.database import get_db
from app.schemas.revenue import RevenueTrackRequest, RevenueTrackResponse
from app.models.website import Website
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.ecommerce_service import EcommerceService
from app.services.website_service import WebsiteService
from app.routers.analytics import check_track_rate_limit, use_tracking_context
from app.utils.network import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/revenue", tags=["revenue"])


@router.post(
    "/track",
    response_model=RevenueTrackResponse,
    # use_tracking_context was missing here while every other tracking
    # endpoint had it, so this one wrote with no context declared and its
    # inserts were refused by policy.
    dependencies=[Depends(check_track_rate_limit), Depends(use_tracking_context)],
)
async def track_revenue(
    request: Request,
    revenue_data: RevenueTrackRequest,
    db: Session = Depends(get_db)
):
    """
    Track an e-commerce revenue transaction (legacy endpoint).

    Public-by-tracking-code by design; abuse is bounded by per-IP rate limiting
    (trusted-proxy aware) and per-(website, transaction_id) idempotency in the
    ecommerce_events table, so forged/duplicate purchases can't inflate revenue.
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent", "unknown")

    ecommerce_service = EcommerceService(db)
    success, message, event_id = ecommerce_service.record_ecommerce_event(
        tracking_code=revenue_data.tracking_code,
        event_type="purchase",
        event_name="Purchase",
        ip_address=client_ip,
        user_agent=user_agent,
        transaction_id=revenue_data.transaction_id,
        revenue=Decimal(str(revenue_data.amount)),
        currency=revenue_data.currency,
        product_name=revenue_data.product_name,
        product_id=revenue_data.product_id,
    )

    if not success:
        if "Invalid tracking code" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    logger.info(
        f"Revenue tracked: {revenue_data.currency} {revenue_data.amount} "
        f"(transaction: {revenue_data.transaction_id})"
    )

    return RevenueTrackResponse(
        status="success",
        transaction_id=revenue_data.transaction_id
    )


@router.get("/{website_id}")
async def get_revenue_stats(
    website_id: int,
    range: Optional[str] = "30d",
    currency: Optional[str] = None,  # None = the site's most-used currency
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get revenue statistics for a website.

    Args:
        website_id: Website ID
        range: Time range (7d, 30d, 90d, 365d)
        currency: Currency code (default: the site's most-used)
        current_user: Authenticated user
        db: Database session

    Returns:
        Dict: Revenue statistics including total revenue, transactions, AOV, etc.
    """
    # Verify website ownership
    website_service = WebsiteService(db)
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or access denied"
        )

    # Parse date range
    end = datetime.utcnow()
    if range == "7d":
        start = end - timedelta(days=7)
    elif range == "30d":
        start = end - timedelta(days=30)
    elif range == "90d":
        start = end - timedelta(days=90)
    elif range == "365d":
        start = end - timedelta(days=365)
    else:
        start = end - timedelta(days=30)

    # Get revenue stats
    ecommerce_service = EcommerceService(db)
    stats = ecommerce_service.get_revenue_stats(
        website_id=website_id,
        start_date=start,
        end_date=end,
        currency=currency
    )

    # Get conversion funnel
    funnel = ecommerce_service.get_conversion_funnel(
        website_id=website_id,
        start_date=start,
        end_date=end
    )

    # Combine results
    return {
        **stats,
        "conversion_rate": funnel.get("overall_conversion", 0),
        "start_date": start.isoformat(),
        "end_date": end.isoformat()
    }


@router.get("/{website_id}/products")
async def get_top_products(
    website_id: int,
    range: Optional[str] = "30d",
    limit: Optional[int] = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get top selling products.

    Args:
        website_id: Website ID
        range: Time range (7d, 30d, 90d, 365d)
        limit: Number of products to return
        current_user: Authenticated user
        db: Database session

    Returns:
        Dict: Top products list with revenue and units sold
    """
    # Verify website ownership
    website_service = WebsiteService(db)
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or access denied"
        )

    # Parse date range
    end = datetime.utcnow()
    if range == "7d":
        start = end - timedelta(days=7)
    elif range == "30d":
        start = end - timedelta(days=30)
    elif range == "90d":
        start = end - timedelta(days=90)
    elif range == "365d":
        start = end - timedelta(days=365)
    else:
        start = end - timedelta(days=30)

    # Get top products
    ecommerce_service = EcommerceService(db)
    return ecommerce_service.get_top_products(
        website_id=website_id,
        start_date=start,
        end_date=end,
        limit=limit
    )


@router.get("/{website_id}/chart")
async def get_revenue_chart(
    website_id: int,
    range: Optional[str] = "30d",
    currency: Optional[str] = None,  # None = the site's most-used currency
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get revenue over time (timeseries data for charts).

    Args:
        website_id: Website ID
        range: Time range (7d, 30d, 90d, 365d)
        currency: Currency code (default: the site's most-used)
        current_user: Authenticated user
        db: Database session

    Returns:
        Dict: Revenue timeseries data
    """
    # Verify website ownership
    website_service = WebsiteService(db)
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or access denied"
        )

    # Parse date range
    end = datetime.utcnow()
    if range == "7d":
        start = end - timedelta(days=7)
    elif range == "30d":
        start = end - timedelta(days=30)
    elif range == "90d":
        start = end - timedelta(days=90)
    elif range == "365d":
        start = end - timedelta(days=365)
    else:
        start = end - timedelta(days=30)

    # Get revenue timeseries
    ecommerce_service = EcommerceService(db)
    return ecommerce_service.get_revenue_timeseries(
        website_id=website_id,
        start_date=start,
        end_date=end,
        currency=currency
    )
