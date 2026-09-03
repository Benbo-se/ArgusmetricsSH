"""
Dashboard router for rendering HTML pages with Jinja2 templates.

Provides endpoints for:
- GET / - Root redirect to dashboard or login
- GET /login - Login page
- GET /verify - Email verification page
- GET /dashboard - Dashboard index (list websites)
- GET /dashboard/website/{id} - Website analytics dashboard
- GET /dashboard/website/{id}/settings - Website settings
- GET /dashboard/website/{id}/live - Live visitors count (HTMX partial)
- GET /dashboard/website/{id}/live-list - Live visitors list (HTMX partial)
"""
import logging
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.analytics_service import AnalyticsService
from app.services.website_service import WebsiteService
from app.models.user import User
from app.routers.auth import get_current_user
from app.utils.date_helpers import parse_date_range
from app.config import settings

logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# Initialize Jinja2 templates
import os
templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)
# base.html builds canonical/og URLs from the instance's own BASE_URL
templates.env.globals["base_url"] = settings.BASE_URL.rstrip("/")

# Add custom Jinja2 filters
def format_number(value):
    """Format number with thousands separator"""
    try:
        return "{:,}".format(int(value))
    except (ValueError, TypeError):
        return value

def country_flag(country_code):
    """Convert country code to flag emoji"""
    if not country_code or len(country_code) != 2:
        return "🌍"

    # Convert country code to flag emoji
    code_points = [127397 + ord(char) for char in country_code.upper()]
    return ''.join(chr(cp) for cp in code_points)

templates.env.filters['format_number'] = format_number
templates.env.filters['country_flag'] = country_flag


def _format_time_ago(timestamp: str) -> str:
    """Format an ISO timestamp as a human 'time ago' string (e.g. '5s ago')."""
    try:
        ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        seconds_ago = int((datetime.utcnow() - ts.replace(tzinfo=None)).total_seconds())

        if seconds_ago < 60:
            return f"{seconds_ago}s ago"
        elif seconds_ago < 3600:
            return f"{seconds_ago // 60}m ago"
        else:
            return f"{seconds_ago // 3600}h ago"
    except Exception:
        return "just now"


# --- Public dashboard password protection (H8) ---------------------------------
# A signed (HMAC) cookie is issued ONLY after PasswordService.verify_password
# succeeds for the share_token; the data route requires this cookie when the
# website has public_password_enabled.
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# Cookie is valid for 12 hours.
PUBLIC_DASHBOARD_COOKIE_MAX_AGE = 12 * 60 * 60


def _public_dashboard_serializer() -> URLSafeTimedSerializer:
    """Serializer for signing public-dashboard access cookies."""
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt="public-dashboard")


def _public_cookie_name(share_token: str) -> str:
    """Per-dashboard cookie name so one unlock doesn't unlock others."""
    return "pub_dash_access"


def _has_valid_public_cookie(request: Request, share_token: str) -> bool:
    """Return True if the request carries a valid, unexpired signed access cookie
    for this share_token."""
    raw = request.cookies.get(_public_cookie_name(share_token))
    if not raw:
        return False
    try:
        data = _public_dashboard_serializer().loads(
            raw, max_age=PUBLIC_DASHBOARD_COOKIE_MAX_AGE
        )
    except (BadSignature, SignatureExpired):
        return False
    return data == share_token


def get_analytics_service(db: Session = Depends(get_db)) -> AnalyticsService:
    """Dependency to get AnalyticsService instance."""
    return AnalyticsService(db)


def get_website_service(db: Session = Depends(get_db)) -> WebsiteService:
    """Dependency to get WebsiteService instance."""
    return WebsiteService(db)


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Get current user without raising exception if not authenticated."""
    try:
        from app.routers.auth import get_current_user as _get_current_user
        from app.services.auth_service import AuthService

        # Try to get token from cookie
        session_token = request.cookies.get("session_token")
        if not session_token:
            return None

        auth_service = AuthService(db)
        user = auth_service.validate_session(session_token)
        return user
    except Exception:
        return None


@router.get("/", response_class=RedirectResponse)
async def root():
    """In production nginx serves the marketing site at /; a bare backend
    instance sends visitors to the login page instead."""
    return RedirectResponse(url="/login", status_code=302)


@router.get("/logout", response_class=RedirectResponse)
async def logout(request: Request, db: Session = Depends(get_db)):
    """Log out user: delete session, clear cookie, redirect to login."""
    from app.services.auth_service import AuthService
    session_token = request.cookies.get("session_token")
    if session_token:
        auth_service = AuthService(db)
        auth_service.logout_user(session_token)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session_token")
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render login page."""
    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "current_user": None
    })


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    """Render signup page with plan selection."""
    return templates.TemplateResponse("auth/signup.html", {
        "request": request,
        "current_user": None
    })


@router.get("/reset", response_class=HTMLResponse)
async def reset_page(request: Request, token: str):
    """Render the set-new-password page (link from the reset email). The token
    is validated when the form posts to /api/v1/auth/set-password."""
    return templates.TemplateResponse("auth/reset.html", {
        "request": request,
        "token": token,
        "current_user": None
    })


@router.get("/verify", response_class=HTMLResponse)
async def verify_page(
    request: Request,
    token: Optional[str] = None,
    email: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Render email verification page.

    With ?token= (magic link): verify immediately. Without a token: render
    the 6-digit code entry form (?email= prefills the address)."""
    from app.services.auth_service import AuthService

    auth_service = AuthService(db)

    if not token:
        return templates.TemplateResponse("auth/verify.html", {
            "request": request,
            "mode": "code_entry",
            "email": email or "",
            "current_user": None
        })

    try:
        session = auth_service.verify_email(token)

        # Check for pending invite cookie — redirect to accept-invite if present
        pending_invite = request.cookies.get("pending_invite")
        if pending_invite:
            response = RedirectResponse(
                url=f"/accept-invite?token={pending_invite}",
                status_code=302
            )
            response.set_cookie(
                key="session_token",
                value=session._raw_token,
                max_age=7 * 24 * 60 * 60,
                httponly=True,
                secure=settings.is_production,
                samesite="lax"
            )
            response.delete_cookie("pending_invite")
            return response

        # Set session cookie (use raw token, not the hash stored in DB)
        response = templates.TemplateResponse("auth/verify.html", {
            "request": request,
            "success": True,
            "current_user": None
        })
        response.set_cookie(
            key="session_token",
            value=session._raw_token,
            max_age=7 * 24 * 60 * 60,  # 7 days
            httponly=True,
            secure=settings.is_production,
            samesite="lax"
        )
        return response

    except ValueError as e:
        return templates.TemplateResponse("auth/verify.html", {
            "request": request,
            "success": False,
            "error_message": str(e),
            "current_user": None
        })


@router.get("/accept-invite", response_class=HTMLResponse)
async def accept_invite_page(
    request: Request,
    token: str,
    db: Session = Depends(get_db)
):
    """Handle team invitation acceptance flow."""
    from app.services.team_service import TeamService

    team_service = TeamService(db)
    user = get_current_user_optional(request, db)

    # Validate the invite token
    try:
        details = team_service.get_invite_details(token)
    except ValueError as e:
        return templates.TemplateResponse("auth/accept_invite.html", {
            "request": request,
            "current_user": user,
            "error": str(e),
        })

    # Get the invitee email from the pending member record
    from app.models.website_member import WebsiteMember, MemberStatus
    member = db.query(WebsiteMember).filter(
        WebsiteMember.invite_token == token,
        WebsiteMember.status == MemberStatus.PENDING
    ).first()

    if not member:
        return templates.TemplateResponse("auth/accept_invite.html", {
            "request": request,
            "current_user": user,
            "error": "Invitation not found or already accepted.",
        })

    invitee_email = member.user_email

    if user:
        # User is logged in
        if user.email.lower() == invitee_email.lower():
            # Email matches — auto-accept
            try:
                result = team_service.accept_invitation(token, user.email)
                return templates.TemplateResponse("auth/accept_invite.html", {
                    "request": request,
                    "current_user": user,
                    "accepted": True,
                    "website_name": details["website_name"],
                    "website_id": result["website_id"],
                    "role": details["role"],
                })
            except ValueError as e:
                return templates.TemplateResponse("auth/accept_invite.html", {
                    "request": request,
                    "current_user": user,
                    "error": str(e),
                })
        else:
            # Wrong email
            return templates.TemplateResponse("auth/accept_invite.html", {
                "request": request,
                "current_user": user,
                "wrong_email": True,
                "invitee_email": invitee_email,
                "current_email": user.email,
                "token": token,
            })
    else:
        # Not logged in — show invite details + login prompt
        # Set pending_invite cookie so /verify redirects back here
        response = templates.TemplateResponse("auth/accept_invite.html", {
            "request": request,
            "current_user": None,
            "needs_login": True,
            "website_name": details["website_name"],
            "website_domain": details["website_domain"],
            "role": details["role"],
            "invited_by": details["invited_by"],
            "invitee_email": invitee_email,
        })
        response.set_cookie(
            key="pending_invite",
            value=token,
            max_age=7 * 24 * 60 * 60,  # 7 days
            httponly=True,
            secure=settings.is_production,
            samesite="lax"
        )
        return response


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_index(
    request: Request,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
):
    """Render dashboard index page with list of websites."""
    logger.info(f"Dashboard index request from user: {current_user.email}")

    # Get all websites for the user
    websites = website_service.get_user_websites(current_user.email)

    # Calculate actual monthly pageviews
    website_ids = [w.id for w in websites] if websites else []
    monthly_pageviews = website_service.get_monthly_pageviews(website_ids)

    return templates.TemplateResponse("dashboard/index.html", {
        "request": request,
        "current_user": current_user,
        "websites": websites,
        "monthly_pageviews": monthly_pageviews
    })


@router.get("/dashboard/cross-domain", response_class=HTMLResponse)
async def cross_domain_dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service)
):
    """Render cross-domain analytics dashboard showing aggregated stats across all websites."""
    logger.info(f"Cross-domain dashboard request from user: {current_user.email}")

    # Get all websites for the user
    websites = website_service.get_user_websites(current_user.email)

    # Prepare website data for frontend
    website_ids = [str(website.id) for website in websites]
    websites_dict = {
        str(website.id): {
            "name": website.name,
            "domain": website.domain
        }
        for website in websites
    }

    return templates.TemplateResponse("dashboard/cross_domain.html", {
        "request": request,
        "current_user": current_user,
        "websites": websites_dict,
        "website_ids": website_ids
    })


@router.get("/dashboard/website/{website_id}", response_class=HTMLResponse)
async def website_dashboard(
    request: Request,
    website_id: int,
    range: Optional[str] = "7d",
    compare: Optional[bool] = False,
    country: Optional[str] = None,
    device: Optional[str] = None,
    browser: Optional[str] = None,
    page: Optional[str] = None,
    referrer: Optional[str] = None,
    properties: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service)
):
    """Render website analytics dashboard."""
    import json

    logger.info(
        f"Website dashboard request: website_id={website_id}, user={current_user.email}, "
        f"compare={compare}, filters: country={country}, device={device}, "
        f"browser={browser}, page={page}, referrer={referrer}, properties={properties}"
    )

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or access denied"
        )

    # Parse date range
    start, end = parse_date_range(range)

    # Parse properties filter (JSON string to dict)
    filter_properties = None
    if properties:
        try:
            filter_properties = json.loads(properties)
        except json.JSONDecodeError:
            logger.warning(f"Invalid properties JSON: {properties}")

    # Get dashboard stats with filters
    try:
        stats = analytics_service.get_dashboard_stats(
            website_id=website_id,
            start_date=start,
            end_date=end,
            compare=compare,
            filter_country=country,
            filter_device=device,
            filter_browser=browser,
            filter_page=page,
            filter_referrer=referrer,
            filter_properties=filter_properties
        )

        # Get live visitors count
        realtime_stats = analytics_service.get_realtime_stats(website_id=website_id)
        live_visitors = realtime_stats.get('current_visitors', 0)

        # Get 404 errors
        errors_404 = analytics_service.get_404_errors(
            website_id=website_id,
            start_date=start,
            end_date=end,
            limit=20
        )

        # Get custom events summary
        custom_events = analytics_service.get_custom_events_summary(
            website_id=website_id,
            start_date=start,
            end_date=end
        )

        # Get file downloads
        file_downloads = analytics_service.get_file_downloads(
            website_id=website_id,
            start_date=start,
            end_date=end
        )

    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}", exc_info=True)
        # Return empty stats on error
        stats = {
            'total_pageviews': 0,
            'unique_visitors': 0,
            'top_pages': [],
            'top_countries': [],
            'devices': {},
            'top_referrers': [],
            'timeseries': [],
            'top_browsers': []
        }
        live_visitors = 0
        errors_404 = []
        custom_events = {'events': [], 'total_events': 0}
        file_downloads = []

    # Build active filters dictionary
    active_filters = {}
    if country:
        active_filters['country'] = country
    if device:
        active_filters['device'] = device
    if browser:
        active_filters['browser'] = browser
    if page:
        active_filters['page'] = page
    if referrer:
        active_filters['referrer'] = referrer
    if filter_properties:
        active_filters['properties'] = filter_properties

    # Add file_downloads to stats dictionary
    stats['file_downloads'] = file_downloads

    return templates.TemplateResponse("dashboard/website.html", {
        "request": request,
        "current_user": current_user,
        "website": website,
        "stats": stats,
        "live_visitors": live_visitors,
        "errors_404": errors_404,
        "custom_events": custom_events,
        "selected_range": range,
        "compare_enabled": compare,
        "active_filters": active_filters
    })


@router.get("/dashboard/website/{website_id}/stats", response_class=HTMLResponse)
async def website_stats_partial(
    request: Request,
    website_id: int,
    range: Optional[str] = "7d",
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service)
):
    """Get stats cards partial for auto-refresh."""
    from datetime import timezone

    website = website_service.get_website_by_id(website_id, current_user.email)

    # Parse date range
    start, end = parse_date_range(range)

    # Get stats
    stats = analytics_service.get_dashboard_stats(
        website_id=website_id,
        start_date=start,
        end_date=end
    )
    realtime_stats = analytics_service.get_realtime_stats(website_id=website_id)

    return templates.TemplateResponse("dashboard/_stats_cards.html", {
        "request": request,
        "stats": stats,
        "realtime_stats": realtime_stats
    })


@router.get("/dashboard/website/{website_id}/stats-basic", response_class=HTMLResponse)
async def website_stats_basic_partial(
    request: Request,
    website_id: int,
    range: Optional[str] = "7d",
    compare: Optional[bool] = False,
    country: Optional[str] = None,
    device: Optional[str] = None,
    browser: Optional[str] = None,
    page: Optional[str] = None,
    referrer: Optional[str] = None,
    properties: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service)
):
    """Get basic stats (first 3 cards) for auto-refresh."""
    from datetime import timezone
    import json

    website = website_service.get_website_by_id(website_id, current_user.email)

    # Parse date range
    start, end = parse_date_range(range)

    # Parse properties filter (JSON string to dict)
    filter_properties = None
    if properties:
        try:
            filter_properties = json.loads(properties)
        except json.JSONDecodeError:
            logger.warning(f"Invalid properties JSON: {properties}")

    # Get stats with filters
    stats = analytics_service.get_dashboard_stats(
        website_id=website_id,
        start_date=start,
        end_date=end,
        compare=compare,
        filter_country=country,
        filter_device=device,
        filter_browser=browser,
        filter_page=page,
        filter_referrer=referrer,
        filter_properties=filter_properties
    )

    return templates.TemplateResponse("dashboard/_stats_basic.html", {
        "request": request,
        "stats": stats
    })


@router.get("/dashboard/website/{website_id}/live", response_class=HTMLResponse)
async def website_live_partial(
    request: Request,
    website_id: int,
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service)
):
    """Get live visitors count for auto-refresh."""
    website = website_service.get_website_by_id(website_id, current_user.email)

    realtime_stats = analytics_service.get_realtime_stats(website_id=website_id)
    live_visitors = realtime_stats.get('current_visitors', 0)

    return templates.TemplateResponse("dashboard/_live.html", {
        "request": request,
        "live_visitors": live_visitors
    })


@router.get("/dashboard/website/{website_id}/settings", response_class=HTMLResponse)
async def website_settings(
    request: Request,
    website_id: int,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service)
):
    """Render website settings page."""
    logger.info(f"Website settings request: website_id={website_id}, user={current_user.email}")

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or access denied"
        )

    # H16: do not expose the session token to JS. Templates authenticate API
    # calls via the httponly session_token cookie (SameSite=Lax mitigates CSRF).
    return templates.TemplateResponse("dashboard/settings.html", {
        "request": request,
        "current_user": current_user,
        "website": website,
        "base_url": settings.BASE_URL,
        "user_email": current_user.email
    })


@router.get("/dashboard/website/{website_id}/team", response_class=HTMLResponse)
async def website_team(
    request: Request,
    website_id: int,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service)
):
    """Render team management page."""
    logger.info(f"Team management request: website_id={website_id}, user={current_user.email}")

    # Verify website access (ownership or team member)
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or access denied"
        )

    # H16: do not expose the session token to JS. Templates authenticate API
    # calls via the httponly session_token cookie (SameSite=Lax mitigates CSRF).
    return templates.TemplateResponse("dashboard/team.html", {
        "request": request,
        "current_user": current_user,
        "website": website,
        "user_email": current_user.email
    })


@router.get("/dashboard/website/{website_id}/live-list", response_class=HTMLResponse)
async def live_visitors_list(
    request: Request,
    website_id: int,
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service)
):
    """HTMX partial: Return live visitors list HTML.

    Rendered via a Jinja2 template (autoescaping ON) so visitor-controlled
    `path` and `country` cannot inject markup (fixes stored XSS H9 / L19).
    """
    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        return HTMLResponse('<p class="text-center py-8 text-gray-500">No data</p>')

    try:
        realtime_stats = analytics_service.get_realtime_stats(website_id=website_id)
        live_visitors = realtime_stats.get('live_visitors', [])

        # Build a safe context list; the template autoescapes path/country and
        # applies the country_flag filter. Time-ago is formatted here.
        visitors = []
        for visitor in live_visitors[:10]:  # Show max 10
            visitors.append({
                "country": visitor.get('country', 'Unknown'),
                "path": visitor.get('path', '/'),
                "time_ago": _format_time_ago(visitor.get('timestamp', '')),
            })

        return templates.TemplateResponse("dashboard/_live_list.html", {
            "request": request,
            "visitors": visitors,
        })

    except Exception as e:
        logger.error(f"Error getting live visitors list: {e}", exc_info=True)
        return HTMLResponse('<p class="text-center py-8 text-gray-500">Error loading visitors</p>')


@router.get("/dashboard/website/{website_id}/goals", response_class=HTMLResponse)

async def website_goals(
    request: Request,
    website_id: int,
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service)
):
    """Render website goals management page."""
    logger.info(f"Website goals request: website_id={website_id}, user={current_user.email}")

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or access denied"
        )

    # Get all goals for this website
    goals = analytics_service.get_goals_list(website_id)

    # Convert goals to dict for JSON serialization
    goals_data = [
        {
            "id": goal.id,
            "name": goal.name,
            "event_name": goal.event_name,
            "created_at": goal.created_at.isoformat() if goal.created_at else None
        }
        for goal in goals
    ]

    # H16: do not expose the session token to JS. Templates authenticate API
    # calls via the httponly session_token cookie (SameSite=Lax mitigates CSRF).
    return templates.TemplateResponse("dashboard/goals.html", {
        "request": request,
        "current_user": current_user,
        "website": website,
        "goals": goals_data
    })


@router.get("/dashboard/website/{website_id}/funnels", response_class=HTMLResponse)
async def website_funnels(
    request: Request,
    website_id: int,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
):
    """Render website funnels management page."""
    logger.info(f"Website funnels request: website_id={website_id}, user={current_user.email}")

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or access denied"
        )

    # Get all funnels for this website
    funnels = website_service.get_funnels(website_id)

    # Convert funnels to dict for JSON serialization
    funnels_data = [
        {
            "id": funnel.id,
            "name": funnel.name,
            "steps": funnel.steps,
            "created_at": funnel.created_at.isoformat() if funnel.created_at else None
        }
        for funnel in funnels
    ]

    # H16: do not expose the session token to JS. Templates authenticate API
    # calls via the httponly session_token cookie (SameSite=Lax mitigates CSRF).
    return templates.TemplateResponse("dashboard/funnels.html", {
        "request": request,
        "current_user": current_user,
        "website": website,
        "funnels": funnels_data
    })


@router.get("/dashboard/website/{website_id}/events/{event_name}", response_class=HTMLResponse)
async def website_event_details(
    request: Request,
    website_id: int,
    event_name: str,
    range: Optional[str] = "7d",
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service)
):
    """Render custom event details page."""
    logger.info(f"Event details request: website_id={website_id}, event={event_name}, user={current_user.email}")

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or access denied"
        )

    # Parse date range
    start, end = parse_date_range(range)

    # Get event details
    event_details = analytics_service.get_event_details(
        website_id=website_id,
        event_name=event_name,
        start_date=start,
        end_date=end
    )

    return templates.TemplateResponse("dashboard/events.html", {
        "request": request,
        "current_user": current_user,
        "website": website,
        "event_details": event_details,
        "selected_range": range
    })


@router.get("/dashboard/website/{website_id}/debug", response_class=HTMLResponse)
async def website_debug_console(
    request: Request,
    website_id: int,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service)
):
    """Render live debug mode console."""
    logger.info(f"Debug console request: website_id={website_id}, user={current_user.email}")

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or access denied"
        )

    return templates.TemplateResponse("debug/console.html", {
        "request": request,
        "current_user": current_user,
        "website": website
    })


@router.get("/public/{share_token}", response_class=HTMLResponse)
async def public_dashboard(
    request: Request,
    share_token: str,
    range: Optional[str] = "7d",
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
):
    """
    Render public dashboard (no authentication required).

    Anyone with the share_token can view the analytics dashboard.
    No login or authentication is needed for this endpoint.
    """
    logger.info(f"Public dashboard request for token: {share_token[:8]}...")

    try:
        # Look up website by public_share_token
        website_service = WebsiteService(db)
        website = website_service.get_public_website(share_token)

        if not website:
            logger.warning(f"Public dashboard not found or disabled for token: {share_token[:8]}...")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Public dashboard not found or has been disabled"
            )

        # H8: enforce public dashboard password. If the owner enabled password
        # protection, require a valid signed access cookie (issued only after a
        # correct password POST) before returning any analytics data.
        if website.public_password_enabled and website.public_password_hash:
            if not _has_valid_public_cookie(request, share_token):
                logger.info(f"Public dashboard {website.id} requires password; prompting")
                return templates.TemplateResponse(
                    "dashboard/_public_password.html",
                    {
                        "request": request,
                        "share_token": share_token,
                        "website_name": website.name,
                        "selected_range": range,
                    },
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

        logger.info(f"Public dashboard accessed: {website.name} ({website.domain})")

        # Parse date range
        start, end = parse_date_range(range)

        # Get dashboard stats (no filters for public view)
        stats = analytics_service.get_dashboard_stats(
            website_id=website.id,
            start_date=start,
            end_date=end,
            compare=True
        )

        # Get live visitors count
        realtime_stats = analytics_service.get_realtime_stats(website_id=website.id)
        live_visitors = realtime_stats.get('current_visitors', 0)

        # Get 404 errors
        errors_404 = analytics_service.get_404_errors(
            website_id=website.id,
            start_date=start,
            end_date=end,
            limit=20
        )

        # Get custom events summary
        custom_events = analytics_service.get_custom_events_summary(
            website_id=website.id,
            start_date=start,
            end_date=end
        )

        return templates.TemplateResponse("dashboard/public.html", {
            "request": request,
            "website": website,
            "stats": stats,
            "live_visitors": live_visitors,
            "errors_404": errors_404,
            "custom_events": custom_events,
            "selected_range": range,
            "is_public_view": True
        })

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Error rendering public dashboard: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while loading the dashboard"
        )


@router.post("/public/{share_token}", response_class=HTMLResponse)
async def public_dashboard_verify(
    request: Request,
    share_token: str,
    password: str = Form(...),
    range: Optional[str] = "7d",
    db: Session = Depends(get_db)
):
    """
    H8: verify a public dashboard password and, on success, issue a signed
    (HMAC) access cookie, then redirect to the dashboard. Mirrors the check in
    dashboard_password.verify_dashboard_password (PasswordService.verify_password).
    """
    from app.services.password_service import PasswordService

    website_service = WebsiteService(db)
    website = website_service.get_public_website(share_token)
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Public dashboard not found or has been disabled"
        )

    redirect_url = f"/public/{share_token}"
    if range:
        redirect_url += f"?range={range}"

    # No password configured -> nothing to verify, just go to the dashboard.
    if not website.public_password_enabled or not website.public_password_hash:
        return RedirectResponse(url=redirect_url, status_code=303)

    # Verify the submitted password against the stored hash.
    is_valid = PasswordService.verify_password(password, website.public_password_hash)
    if not is_valid:
        logger.info(f"Incorrect public dashboard password for website {website.id}")
        return templates.TemplateResponse(
            "dashboard/_public_password.html",
            {
                "request": request,
                "share_token": share_token,
                "website_name": website.name,
                "selected_range": range,
                "error": "Incorrect password. Please try again.",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    # Correct password -> issue signed access cookie and redirect (303 so the
    # browser re-requests with GET and sends the new cookie).
    signed = _public_dashboard_serializer().dumps(share_token)
    response = RedirectResponse(url=redirect_url, status_code=303)
    response.set_cookie(
        key=_public_cookie_name(share_token),
        value=signed,
        max_age=PUBLIC_DASHBOARD_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )
    return response


@router.get("/dashboard/website/{website_id}/revenue", response_class=HTMLResponse)
async def website_revenue_dashboard(
    request: Request,
    website_id: int,
    range: Optional[str] = "30d",
    currency: Optional[str] = "USD",
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
):
    """Render revenue analytics dashboard."""
    logger.info(f"Revenue dashboard request: website_id={website_id}, user={current_user.email}")

    # Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or access denied"
        )

    # Parse date range
    start, end = parse_date_range(range)

    # Get revenue data
    try:
        from app.services.ecommerce_service import EcommerceService
        ecommerce_service = EcommerceService(db)

        # Get revenue stats
        revenue_stats = ecommerce_service.get_revenue_stats(
            website_id=website_id,
            start_date=start,
            end_date=end,
            currency=currency
        )

        # Get conversion funnel for conversion rate
        funnel = ecommerce_service.get_conversion_funnel(
            website_id=website_id,
            start_date=start,
            end_date=end
        )
        revenue_stats['conversion_rate'] = funnel.get('overall_conversion', 0)

        # Get top products
        top_products = ecommerce_service.get_top_products(
            website_id=website_id,
            start_date=start,
            end_date=end,
            limit=10
        )

        # Get revenue timeseries for chart
        revenue_chart = ecommerce_service.get_revenue_timeseries(
            website_id=website_id,
            start_date=start,
            end_date=end,
            currency=currency
        )

    except Exception as e:
        logger.error(f"Error getting revenue data: {e}", exc_info=True)
        # Return empty data on error
        revenue_stats = {
            'total_revenue': 0,
            'total_transactions': 0,
            'average_order_value': 0,
            'total_tax': 0,
            'total_shipping': 0,
            'unique_customers': 0,
            'currency': currency,
            'conversion_rate': 0
        }
        top_products = {'products': [], 'total_products': 0}
        revenue_chart = {'data': [], 'total_revenue': 0, 'total_transactions': 0}

    return templates.TemplateResponse("dashboard/revenue.html", {
        "request": request,
        "current_user": current_user,
        "website": website,
        "revenue_stats": revenue_stats,
        "top_products": top_products,
        "revenue_chart": revenue_chart,
        "selected_range": range,
        "selected_currency": currency
    })


@router.get("/dashboard/website/{website_id}/export-csv")
async def export_csv(
    website_id: int,
    range: str = "7d",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Export analytics data as CSV file.
    
    User flow:
    1. User clicks "Export CSV" button on dashboard
    2. CSV file downloads with format: argusmetrics-{website_name}-{date}.csv
    3. Contains: Date, Pageviews, Visitors, Bounce Rate, Top Pages, etc.
    """
    from fastapi.responses import StreamingResponse
    import csv
    from io import StringIO
    from datetime import datetime, timedelta, timezone
    
    # Get website
    website_service = WebsiteService(db)
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    
    # Calculate date range
    start, end = parse_date_range(range)

    # Get analytics data
    analytics_service = AnalyticsService(db)
    stats = analytics_service.get_dashboard_stats(
        website_id=website.id,
        start_date=start,
        end_date=end,
        compare=False
    )
    
    # Create CSV in memory
    output = StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Argusmetrics - Analytics Export'])
    writer.writerow(['Website:', website.name])
    writer.writerow(['Domain:', website.domain])
    writer.writerow(['Date Range:', f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"])
    writer.writerow(['Exported:', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')])
    writer.writerow([])
    
    # Summary stats
    writer.writerow(['SUMMARY'])
    writer.writerow(['Total Pageviews', stats.get('total_pageviews', 0)])
    writer.writerow(['Unique Visitors', stats.get('unique_visitors', 0)])
    writer.writerow(['Bounce Rate', f"{stats.get('bounce_rate', 0):.1f}%"])
    writer.writerow(['Avg. Visit Duration', f"{stats.get('avg_duration', 0):.0f}s"])
    writer.writerow([])
    
    # Pageviews over time
    writer.writerow(['PAGEVIEWS OVER TIME'])
    writer.writerow(['Date', 'Pageviews'])
    for item in stats.get('timeseries', []):
        writer.writerow([item['date'], item['views']])
    writer.writerow([])
    
    # Top pages
    writer.writerow(['TOP PAGES'])
    writer.writerow(['Page', 'Views', 'Percentage'])
    for page in stats.get('top_pages', [])[:20]:
        pct = (page['views'] / stats.get('total_pageviews', 1)) * 100 if stats.get('total_pageviews', 0) > 0 else 0
        writer.writerow([page['path'], page['views'], f"{pct:.1f}%"])
    writer.writerow([])
    
    # Referrers
    writer.writerow(['TOP REFERRERS'])
    writer.writerow(['Referrer', 'Visitors', 'Percentage'])
    for ref in stats.get('referrers', [])[:20]:
        pct = (ref['visitors'] / stats.get('unique_visitors', 1)) * 100 if stats.get('unique_visitors', 0) > 0 else 0
        writer.writerow([ref['referrer'] or 'Direct', ref['visitors'], f"{pct:.1f}%"])
    writer.writerow([])
    
    # Countries
    writer.writerow(['TOP COUNTRIES'])
    writer.writerow(['Country', 'Visitors', 'Percentage'])
    for country in stats.get('countries', [])[:20]:
        pct = (country['visitors'] / stats.get('unique_visitors', 1)) * 100 if stats.get('unique_visitors', 0) > 0 else 0
        writer.writerow([country['country'], country['visitors'], f"{pct:.1f}%"])
    writer.writerow([])
    
    # Devices
    writer.writerow(['DEVICES'])
    writer.writerow(['Device', 'Count'])
    for device, count in stats.get('devices', {}).items():
        writer.writerow([device.capitalize(), count])
    writer.writerow([])
    
    # Browsers
    writer.writerow(['TOP BROWSERS'])
    writer.writerow(['Browser', 'Visitors'])
    for browser in stats.get('browsers', [])[:20]:
        writer.writerow([browser['browser'], browser['visitors']])
    
    # Prepare response
    output.seek(0)
    filename = f"argusmetrics-{website.domain.replace('.', '-')}-{datetime.now().strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )
