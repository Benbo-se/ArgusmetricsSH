"""
Analytics router for pageview tracking and statistics retrieval.

Provides endpoints for:
- POST /track - Record pageview (NO authentication, uses tracking_code)
- GET /stats/{website_id} - Get dashboard statistics (authentication required)
- GET /realtime/{website_id} - Get realtime statistics (authentication required)
"""
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header, Cookie
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.analytics_service import AnalyticsService
from app.services.website_service import WebsiteService
from app.services.token_service import TokenService
from app.services.alert_service import AlertService
from app.schemas.analytics import (
    PageviewTrackRequest,
    PageviewTrackResponse,
    DashboardStatsResponse,
    RealtimeStatsResponse,
    GoalCreate,
    GoalResponse,
    GoalConversionRequest,
    GoalConversionResponse,
    GoalStatsResponse,
    ApiTokenCreate,
    ApiTokenResponse,
    ApiTokenListItem,
    AlertSettingsUpdate,
    AlertSettingsResponse,
    CustomEventsSummary,
    CustomEventDetail,
)
from app.schemas.ecommerce import EcommerceEventRequest, EcommerceEventResponse
from app.services.ecommerce_service import EcommerceService
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.team_service import TeamService
from app.models.website_member import MemberRole

from app.utils.security import mask_email
logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# Known bot user agents to filter out from analytics
KNOWN_BOTS = [
    'googlebot', 'bingbot', 'yandex', 'baiduspider', 'duckduckbot',
    'facebookexternalhit', 'twitterbot', 'linkedinbot', 'slackbot',
    'telegrambot', 'whatsapp', 'discordbot', 'skypeuripreview',
    'crawler', 'spider', 'bot', 'scraper', 'phantom', 'headless',
    'selenium', 'puppeteer', 'playwright', 'curl', 'wget',
    'python-requests', 'java', 'go-http-client', 'axios',
    'ahrefsbot', 'semrushbot', 'mj12bot', 'dotbot', 'rogerbot',
    'screaming frog', 'sitebulb', 'petalbot', 'applebot'
]


def is_bot_user_agent(user_agent: str) -> bool:
    """
    Check if user agent matches known bot patterns.

    Returns True if the user agent contains any known bot identifier.
    """
    if not user_agent:
        return False

    ua_lower = user_agent.lower()
    return any(bot in ua_lower for bot in KNOWN_BOTS)


def get_analytics_service(db: Session = Depends(get_db)) -> AnalyticsService:
    """Dependency to get AnalyticsService instance."""
    return AnalyticsService(db)


def get_website_service(db: Session = Depends(get_db)) -> WebsiteService:
    """Dependency to get WebsiteService instance."""
    return WebsiteService(db)


from app.utils.network import get_client_ip  # trusted-proxy-aware client IP


def get_user_agent(request: Request) -> str:
    """Extract User-Agent from request."""
    return request.headers.get("User-Agent", "Unknown")


def anonymize_ip(ip: str) -> str:
    """
    Truncate an IP address for privacy before exposing it in debug payloads.

    IPv4: keep the first 3 octets and zero the last (/24).
    IPv6: keep the first 3 groups and collapse the rest (::).
    """
    if not ip:
        return "unknown"
    if ":" in ip:
        # IPv6
        groups = ip.split(":")
        return ":".join(groups[:3]) + "::"
    # IPv4
    octets = ip.split(".")
    if len(octets) == 4:
        return ".".join(octets[:3]) + ".0"
    return "unknown"


def summarize_user_agent(user_agent: str) -> str:
    """
    Reduce a raw User-Agent to a coarse browser/device family string so the
    debug stream does not leak the full fingerprintable UA.
    """
    if not user_agent:
        return "unknown"
    try:
        from user_agents import parse
        ua = parse(user_agent)
        device = "mobile" if ua.is_mobile else ("tablet" if ua.is_tablet else "desktop")
        return f"{ua.browser.family} on {ua.os.family} ({device})"
    except Exception:
        return "unknown"


async def check_track_rate_limit(request: Request):
    """Rate limit dependency for tracking endpoints (120 req/min per IP)."""
    from app.middleware.rate_limit import rate_limiter
    client_ip = get_client_ip(request)
    if rate_limiter.is_rate_limited(client_ip, limit=120, window_seconds=60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


async def get_current_user_or_token(
    authorization: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
) -> User:
    """
    Authenticate user via Bearer token OR API token.

    Supports two authentication methods:
    1. Authorization: Bearer <session_token>
    2. X-API-Token: <api_token>

    Args:
        authorization: Authorization header value
        x_api_token: X-API-Token header value
        db: Database session

    Returns:
        User: Authenticated user

    Raises:
        HTTPException: If authentication fails
    """
    from app.models.api_token import ApiToken
    from app.models.website import Website
    from app.routers.auth import get_auth_service
    from app.services.token_service import TokenService

    # Try API token first
    if x_api_token:
        token_hash = TokenService.hash_token(x_api_token)
        token_obj = db.query(ApiToken).filter(ApiToken.token == token_hash).first()
        if token_obj:
            # Update last_used_at
            token_obj.last_used_at = datetime.now(timezone.utc)
            db.commit()

            # Get website and user
            website = db.query(Website).filter(Website.id == token_obj.website_id).first()
            if website:
                user = db.query(User).filter(User.email == website.user_email).first()
                if user:
                    # Scope marker: an API token is minted FOR ONE WEBSITE and
                    # must not unlock the owner's other sites. Endpoints check
                    # this via _enforce_token_scope.
                    user._api_token_website_id = token_obj.website_id
                    logger.debug(f"Authenticated via API token (website {token_obj.website_id}): {user.email}")
                    return user

        logger.warning(f"Invalid API token provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token"
        )

    # Fallback: Bearer header OR the dashboard's session cookie. Accepting the
    # cookie keeps these endpoints usable from a logged-in browser (the API
    # docs and any in-page fetch), matching every other authenticated route.
    if not authorization and not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in."
        )

    return get_current_user(authorization, session_token, get_auth_service(db))


def _enforce_token_scope(current_user: User, website_id: int) -> None:
    """When authenticated via a website-scoped API token, refuse access to any
    other website — even ones the token's owner could see with a session."""
    scope = getattr(current_user, "_api_token_website_id", None)
    if scope is not None and scope != website_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")


@router.post("/track", response_model=PageviewTrackResponse, status_code=status.HTTP_200_OK, dependencies=[Depends(check_track_rate_limit)])
async def track_pageview(
    request: Request,
    track_request: PageviewTrackRequest,
    analytics_service: AnalyticsService = Depends(get_analytics_service)
) -> PageviewTrackResponse:
    """Record a pageview from the tracking script (NO authentication required)."""
    # Check Do Not Track header
    dnt = request.headers.get("DNT") or request.headers.get("dnt")
    if dnt == "1":
        logger.debug("DNT header detected, skipping tracking")
        return PageviewTrackResponse(success=True, message="Tracking skipped (DNT)")

    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    # Bot filtering - skip tracking for bots/crawlers
    is_bot = False
    bot_reason = None

    # Method 1: Check against known bot patterns (fast blacklist)
    if is_bot_user_agent(user_agent):
        is_bot = True
        bot_reason = "Known bot pattern"
        logger.debug(f"Bot detected (blacklist): {user_agent[:50]}, skipping tracking")
        if not track_request.debug:
            return PageviewTrackResponse(success=True, message="Tracking skipped (Bot)")

    # Method 2: Use user_agents library for advanced detection
    try:
        from user_agents import parse
        ua = parse(user_agent)
        if ua.is_bot and not is_bot:
            is_bot = True
            bot_reason = f"Bot library detection: {ua.browser.family}"
            logger.debug(f"Bot detected (user_agents): {ua.browser.family}, skipping tracking")
            if not track_request.debug:
                return PageviewTrackResponse(success=True, message="Tracking skipped (Bot)")
    except Exception as e:
        logger.warning(f"Failed to parse User-Agent for bot detection: {e}")

    # Handle debug mode
    if track_request.debug:
        from app.routers.websocket import broadcast_debug_event
        from app.models.website import Website
        from app.database import get_db

        db = next(get_db())
        try:
            # Get website info
            website = db.query(Website).filter(
                Website.tracking_code == track_request.tracking_code
            ).first()

            if not website:
                return PageviewTrackResponse(success=False, message="Invalid tracking code")

            # Prepare debug event data
            debug_data = {
                "event_type": "pageview",
                "path": track_request.path,
                "referrer": track_request.referrer,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": {
                    "ip": anonymize_ip(client_ip),
                    "user_agent": summarize_user_agent(user_agent),
                    "device": "desktop" if track_request.screen_width and track_request.screen_width > 1024 else "mobile",
                    "screen": f"{track_request.screen_width}x{track_request.screen_height}" if track_request.screen_width else "unknown",
                    "utm_source": track_request.utm_source,
                    "utm_medium": track_request.utm_medium,
                    "utm_campaign": track_request.utm_campaign,
                    "properties": track_request.properties
                },
                "validation": {
                    "is_bot": is_bot,
                    "bot_reason": bot_reason,
                    "dnt_enabled": dnt == "1"
                }
            }

            # Broadcast to debug WebSocket
            await broadcast_debug_event(website.id, debug_data)

            logger.info(f"Debug event broadcasted: {track_request.path}")
            return PageviewTrackResponse(success=True, message="Debug event sent (not saved)")
        finally:
            db.close()

    logger.info(f"Tracking pageview: code={track_request.tracking_code}, path={track_request.path}")

    success, message = analytics_service.record_pageview(
        tracking_code=track_request.tracking_code,
        path=track_request.path,
        referrer=track_request.referrer,
        screen_width=track_request.screen_width,
        ip_address=client_ip,
        user_agent=user_agent,
        utm_source=track_request.utm_source,
        utm_medium=track_request.utm_medium,
        utm_campaign=track_request.utm_campaign,
        utm_content=track_request.utm_content,
        utm_term=track_request.utm_term,
        screen_height=track_request.screen_height,
        scroll_depth=track_request.scroll_depth,
        properties=track_request.properties
    )

    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return PageviewTrackResponse(success=True, message=message)


@router.get("/stats/{website_id}", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    website_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
    current_user: User = Depends(get_current_user_or_token),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service)
) -> DashboardStatsResponse:
    """Get dashboard statistics for a website (authentication required)."""
    logger.info(f"Dashboard stats request: website_id={website_id}, user={mask_email(current_user.email)}")
    
    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")
    _enforce_token_scope(current_user, website_id)
    
    # Parse dates or use defaults (last 30 days)
    try:
        if end_date:
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        else:
            end = datetime.utcnow()
        
        if start_date:
            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        else:
            start = end - timedelta(days=30)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format. Use ISO format (YYYY-MM-DD)")
    
    # Get dashboard stats
    try:
        stats = analytics_service.get_dashboard_stats(website_id=website_id, start_date=start, end_date=end)
        return DashboardStatsResponse(**stats)
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve statistics")


@router.get("/realtime/{website_id}", response_model=RealtimeStatsResponse)
async def get_realtime_stats(
    website_id: int,
    authorization: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
    current_user: User = Depends(get_current_user_or_token),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service)
) -> RealtimeStatsResponse:
    """Get realtime analytics for a website (authentication required)."""
    logger.info(f"Realtime stats request: website_id={website_id}, user={mask_email(current_user.email)}")
    
    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")
    _enforce_token_scope(current_user, website_id)
    
    # Get realtime stats
    try:
        stats = analytics_service.get_realtime_stats(website_id=website_id)
        return RealtimeStatsResponse(**stats)
    except Exception as e:
        logger.error(f"Error getting realtime stats: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve realtime statistics")


# ============================================
# GOAL TRACKING ENDPOINTS
# ============================================

@router.post("/goals", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(
    goal_data: GoalCreate,
    website_id: int,
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
) -> GoalResponse:
    """Create a new goal for a website."""
    logger.info(f"Create goal request: website_id={website_id}, name={goal_data.name}")

    from app.services.team_service import require_website_role_or_404
    from app.models.website_member import MemberRole
    require_website_role_or_404(db, current_user.email, website_id, MemberRole.ADMIN)

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")
    _enforce_token_scope(current_user, website_id)

    # Create goal
    goal = analytics_service.create_goal(
        website_id=website_id,
        name=goal_data.name,
        event_name=goal_data.event_name
    )

    if not goal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Goal with this event name already exists"
        )

    return GoalResponse.model_validate(goal)


@router.post("/track-event", response_model=GoalConversionResponse, dependencies=[Depends(check_track_rate_limit)])
async def track_event(
    request: Request,
    event_request: GoalConversionRequest,
    analytics_service: AnalyticsService = Depends(get_analytics_service)
) -> GoalConversionResponse:
    """
    Track an event (supports both Goals and Custom Events).

    - If event has no properties: checks for matching Goal and records goal conversion
    - If event has properties: records as Custom Event with properties
    - Both can coexist: same event can be both a Goal and Custom Event
    """
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    # Check if properties are provided in the request
    properties = getattr(event_request, 'properties', None)

    # Record custom event if properties provided
    if properties:
        success, message = analytics_service.record_custom_event(
            tracking_code=event_request.tracking_code,
            event_name=event_request.event_name,
            properties=properties,
            ip_address=client_ip,
            user_agent=user_agent
        )

        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

        return GoalConversionResponse(success=True, message=message)

    # If no properties, try to record as goal conversion
    success, message = analytics_service.record_goal_conversion(
        tracking_code=event_request.tracking_code,
        event_name=event_request.event_name,
        ip_address=client_ip,
        user_agent=user_agent
    )

    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return GoalConversionResponse(success=True, message=message)


@router.post("/track-ecommerce", response_model=EcommerceEventResponse, status_code=status.HTTP_200_OK, dependencies=[Depends(check_track_rate_limit)])
async def track_ecommerce(
    request: Request,
    event_data: EcommerceEventRequest,
    db: Session = Depends(get_db)
) -> EcommerceEventResponse:
    """Track an e-commerce event (NO authentication required)."""
    user_agent = get_user_agent(request)

    # Bot filtering
    if is_bot_user_agent(user_agent):
        return EcommerceEventResponse(success=True, message="Tracking skipped (Bot)")

    try:
        from user_agents import parse as ua_parse
        ua = ua_parse(user_agent)
        if ua.is_bot:
            return EcommerceEventResponse(success=True, message="Tracking skipped (Bot)")
    except Exception:
        pass

    client_ip = get_client_ip(request)

    ecommerce_service = EcommerceService(db)
    success, message, event_id = ecommerce_service.record_ecommerce_event(
        tracking_code=event_data.tracking_code,
        event_type=event_data.event_type,
        event_name=event_data.event_name or event_data.event_type,
        ip_address=client_ip,
        user_agent=user_agent,
        transaction_id=event_data.transaction_id,
        revenue=event_data.revenue,
        currency=event_data.currency,
        tax=event_data.tax,
        shipping=event_data.shipping,
        product_id=event_data.product_id,
        product_name=event_data.product_name,
        product_category=event_data.product_category,
        product_brand=event_data.product_brand,
        product_variant=event_data.product_variant,
        quantity=event_data.quantity,
        price=event_data.price,
        properties=event_data.properties,
        utm_source=event_data.utm_source,
        utm_medium=event_data.utm_medium,
        utm_campaign=event_data.utm_campaign,
        utm_content=event_data.utm_content,
        utm_term=event_data.utm_term,
    )

    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return EcommerceEventResponse(success=True, message=message, event_id=event_id)


@router.get("/goals/{website_id}", response_model=GoalStatsResponse)
async def get_goal_stats(
    website_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service)
) -> GoalStatsResponse:
    """Get goal statistics for a website."""
    logger.info(f"Goal stats request: website_id={website_id}")

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")
    _enforce_token_scope(current_user, website_id)

    # Parse dates or use defaults (last 30 days)
    try:
        if end_date:
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        else:
            end = datetime.utcnow()

        if start_date:
            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        else:
            start = end - timedelta(days=30)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format")

    # Get goal stats
    stats = analytics_service.get_goal_stats(website_id, start, end)
    return GoalStatsResponse(**stats)


@router.put("/goals/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: int,
    goal_data: GoalCreate,
    website_id: int,
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
) -> GoalResponse:
    """Update an existing goal."""
    from app.models.goal import Goal

    logger.info(f"Update goal request: goal_id={goal_id}, website_id={website_id}")

    from app.services.team_service import require_website_role_or_404
    from app.models.website_member import MemberRole
    require_website_role_or_404(db, current_user.email, website_id, MemberRole.ADMIN)

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")
    _enforce_token_scope(current_user, website_id)

    # Get the goal
    goal = db.query(Goal).filter(
        Goal.id == goal_id,
        Goal.website_id == website_id
    ).first()

    if not goal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")

    # Check if new event_name conflicts with another goal
    if goal_data.event_name != goal.event_name:
        existing = db.query(Goal).filter(
            Goal.website_id == website_id,
            Goal.event_name == goal_data.event_name,
            Goal.id != goal_id
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Another goal with this event name already exists"
            )

    # Update the goal
    goal.name = goal_data.name
    goal.event_name = goal_data.event_name

    db.commit()
    db.refresh(goal)

    return GoalResponse.model_validate(goal)


@router.delete("/goals/{goal_id}")
async def delete_goal(
    goal_id: int,
    website_id: int,
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
):
    """Delete a goal."""
    from app.services.team_service import require_website_role_or_404
    from app.models.website_member import MemberRole
    require_website_role_or_404(db, current_user.email, website_id, MemberRole.ADMIN)
    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")
    _enforce_token_scope(current_user, website_id)

    success = analytics_service.delete_goal(goal_id, website_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")

    return {"success": True, "message": "Goal deleted"}


# ============================================
# DATA EXPORT ENDPOINTS
# ============================================

@router.get("/export/{website_id}/csv")
async def export_csv(
    website_id: int,
    authorization: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user_or_token),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
):
    """Export analytics data as CSV."""
    from fastapi.responses import StreamingResponse
    from app.models.pageview import Pageview
    import io
    import csv

    logger.info(f"CSV export request: website_id={website_id}")

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")
    _enforce_token_scope(current_user, website_id)

    # Parse dates
    try:
        if end_date:
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        else:
            end = datetime.utcnow()

        if start_date:
            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        else:
            start = end - timedelta(days=30)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format")

    # Get pageviews
    from sqlalchemy import and_
    pageviews = db.query(Pageview).filter(
        and_(
            Pageview.website_id == website_id,
            Pageview.timestamp >= start,
            Pageview.timestamp <= end
        )
    ).order_by(Pageview.timestamp.desc()).limit(10000).all()

    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Timestamp', 'Path', 'Referrer', 'Country', 'Device', 'Browser', 'Visitor Hash'])

    for pv in pageviews:
        writer.writerow([
            pv.timestamp.isoformat(),
            pv.path,
            pv.referrer or '',
            pv.country or '',
            pv.device_type or '',
            pv.browser or '',
            pv.visitor_hash[:16] + '...'  # Truncate for privacy
        ])

    output.seek(0)
    filename = f"analytics_{website_id}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode('utf-8')),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/export/{website_id}/json")
async def export_json(
    website_id: int,
    authorization: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user_or_token),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
):
    """Export analytics data as JSON."""
    from fastapi.responses import JSONResponse
    from app.models.pageview import Pageview
    from sqlalchemy import and_

    logger.info(f"JSON export request: website_id={website_id}")

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")
    _enforce_token_scope(current_user, website_id)

    # Parse dates
    try:
        if end_date:
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        else:
            end = datetime.utcnow()

        if start_date:
            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        else:
            start = end - timedelta(days=30)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format")

    # Get pageviews
    pageviews = db.query(Pageview).filter(
        and_(
            Pageview.website_id == website_id,
            Pageview.timestamp >= start,
            Pageview.timestamp <= end
        )
    ).order_by(Pageview.timestamp.desc()).limit(10000).all()

    # Convert to dict
    data = {
        "website_id": website_id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "total_pageviews": len(pageviews),
        "pageviews": [
            {
                "timestamp": pv.timestamp.isoformat(),
                "path": pv.path,
                "referrer": pv.referrer,
                "country": pv.country,
                "device": pv.device_type,
                "browser": pv.browser
            }
            for pv in pageviews
        ]
    }

    return JSONResponse(content=data)


# ============================================
# API TOKEN ENDPOINTS
# ============================================

def get_token_service(db: Session = Depends(get_db)) -> TokenService:
    """Dependency to get TokenService instance."""
    return TokenService(db)


@router.post("/tokens", response_model=ApiTokenResponse, status_code=status.HTTP_201_CREATED)
async def create_api_token(
    token_data: ApiTokenCreate,
    website_id: int,
    current_user: User = Depends(get_current_user),
    token_service: TokenService = Depends(get_token_service),
    db: Session = Depends(get_db)
) -> ApiTokenResponse:
    """Create a new API token for a website. Requires OWNER role (tokens mint credentials)."""
    logger.info(f"Create API token request: website_id={website_id}, name={token_data.name}")

    # API tokens authenticate as the website owner, so only the owner may mint them
    team_service = TeamService(db)
    role = team_service.check_website_access(current_user.email, website_id)
    if not role or role != MemberRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You need owner access to create API tokens"
        )

    # Create token
    result = token_service.create_token(website_id, token_data.name)
    if not result:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create token")

    api_token, raw_token = result

    # Return with token value (only shown once)
    response = ApiTokenResponse.model_validate(api_token)
    response.token = raw_token
    return response


@router.get("/tokens/{website_id}", response_model=list[ApiTokenListItem])
async def list_api_tokens(
    website_id: int,
    current_user: User = Depends(get_current_user),
    token_service: TokenService = Depends(get_token_service),
    db: Session = Depends(get_db)
) -> list[ApiTokenListItem]:
    """List all API tokens for a website. Any active member may list tokens."""
    # Verify website access (any active member/role)
    team_service = TeamService(db)
    role = team_service.check_website_access(current_user.email, website_id)
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")

    tokens = token_service.get_website_tokens(website_id)
    return [ApiTokenListItem.model_validate(t) for t in tokens]


@router.delete("/tokens/{token_id}")
async def delete_api_token(
    token_id: int,
    website_id: int,
    current_user: User = Depends(get_current_user),
    token_service: TokenService = Depends(get_token_service),
    db: Session = Depends(get_db)
):
    """Delete an API token. Requires OWNER role (tokens mint credentials)."""
    # API tokens authenticate as the website owner, so only the owner may revoke them
    team_service = TeamService(db)
    role = team_service.check_website_access(current_user.email, website_id)
    if not role or role != MemberRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You need owner access to delete API tokens"
        )

    success = token_service.delete_token(token_id, website_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

    return {"success": True, "message": "Token deleted"}


# ============================================
# ALERT SETTINGS ENDPOINTS
# ============================================

def get_alert_service(db: Session = Depends(get_db)) -> AlertService:
    """Dependency to get AlertService instance."""
    return AlertService(db)


@router.get("/alerts/{website_id}", response_model=AlertSettingsResponse)
async def get_alert_settings(
    website_id: int,
    current_user: User = Depends(get_current_user),
    alert_service: AlertService = Depends(get_alert_service),
    website_service: WebsiteService = Depends(get_website_service)
) -> AlertSettingsResponse:
    """Get alert settings for a website."""
    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")
    _enforce_token_scope(current_user, website_id)

    settings = alert_service.get_or_create_settings(website_id, current_user.email)
    return AlertSettingsResponse.model_validate(settings)


@router.put("/alerts/{website_id}", response_model=AlertSettingsResponse)
async def update_alert_settings(
    website_id: int,
    settings_data: AlertSettingsUpdate,
    current_user: User = Depends(get_current_user),
    alert_service: AlertService = Depends(get_alert_service),
    db: Session = Depends(get_db)
) -> AlertSettingsResponse:
    """Update alert settings for a website. Requires admin or owner role."""
    # Mutating action: require admin or owner (viewers must not change settings)
    team_service = TeamService(db)
    role = team_service.check_website_access(current_user.email, website_id)
    if not role or role not in [MemberRole.OWNER, MemberRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You need admin or owner access to update alert settings"
        )

    settings = alert_service.update_settings(
        website_id,
        settings_data.spike_threshold,
        settings_data.email_enabled
    )

    if not settings:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Settings not found")

    return AlertSettingsResponse.model_validate(settings)


# ============================================
# CUSTOM EVENTS ENDPOINTS
# ============================================

@router.get("/custom-events/{website_id}", response_model=CustomEventsSummary)
async def get_custom_events_summary(
    website_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service)
) -> CustomEventsSummary:
    """Get custom events summary for a website."""
    logger.info(f"Custom events summary request: website_id={website_id}")

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")
    _enforce_token_scope(current_user, website_id)

    # Parse dates or use defaults (last 30 days)
    try:
        if end_date:
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        else:
            end = datetime.utcnow()

        if start_date:
            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        else:
            start = end - timedelta(days=30)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format")

    # Get custom events summary
    summary = analytics_service.get_custom_events_summary(website_id, start, end)
    return CustomEventsSummary(**summary)


@router.get("/custom-events/{website_id}/{event_name}", response_model=CustomEventDetail)
async def get_event_details(
    website_id: int,
    event_name: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service)
) -> CustomEventDetail:
    """Get detailed information for a specific custom event."""
    logger.info(f"Event details request: website_id={website_id}, event={event_name}")

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")
    _enforce_token_scope(current_user, website_id)

    # Parse dates or use defaults (last 30 days)
    try:
        if end_date:
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        else:
            end = datetime.utcnow()

        if start_date:
            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        else:
            start = end - timedelta(days=30)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format")

    # Get event details
    details = analytics_service.get_event_details(website_id, event_name, start, end)
    return CustomEventDetail(**details)


# ============================================
# CUSTOM PROPERTIES ENDPOINTS
# ============================================

@router.get("/properties/{website_id}")
async def get_available_properties(
    website_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service)
):
    """Get all available custom property keys and values for filtering."""
    logger.info(f"Available properties request: website_id={website_id}")

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found or access denied")
    _enforce_token_scope(current_user, website_id)

    # Parse dates or use defaults (last 30 days)
    try:
        if end_date:
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        else:
            end = datetime.utcnow()

        if start_date:
            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        else:
            start = end - timedelta(days=30)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format")

    # Get available properties
    properties = analytics_service.get_available_properties(website_id, start, end)
    return properties
