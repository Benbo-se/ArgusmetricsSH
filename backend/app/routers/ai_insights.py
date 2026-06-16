"""
AI Insights Dashboard router for AI-powered analytics insights.

Provides endpoints for:
- GET /ai-insights/{website_id} - Get AI-generated insights for a website

Includes:
- Authentication and website ownership verification
- AI quota management (plan-based access control)
- 1-hour caching to reduce AI costs
- Integration with Anthropic Claude API
"""
import logging
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.website_service import WebsiteService
from app.services.analytics_service import AnalyticsService
from app.services.ai_quota_service import check_ai_quota_available, consume_ai_quota
from app.schemas.ai_insights import (
    AIInsightsResponse,
    TrafficTrendInsight,
    ContentInsight,
    RecommendationInsight,
)
from app.config import settings

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(tags=["ai-insights"])

# Simple in-memory cache for AI insights
# Structure: {cache_key: {"data": AIInsightsResponse, "timestamp": datetime}}
insights_cache: Dict[str, Dict[str, Any]] = {}

# Cache TTL: 1 hour (3600 seconds)
CACHE_TTL_SECONDS = 3600


def get_website_service(db: Session = Depends(get_db)) -> WebsiteService:
    """Dependency to get WebsiteService instance."""
    return WebsiteService(db)


def get_analytics_service(db: Session = Depends(get_db)) -> AnalyticsService:
    """Dependency to get AnalyticsService instance."""
    return AnalyticsService(db)


def generate_cache_key(website_id: int, days: int, date: str) -> str:
    """
    Generate cache key for insights.

    Args:
        website_id: Website ID
        days: Number of days analyzed
        date: Date string (YYYY-MM-DD)

    Returns:
        str: Cache key
    """
    key_string = f"ai_insights_{website_id}_{days}_{date}"
    return hashlib.md5(key_string.encode()).hexdigest()


def get_cached_insights(cache_key: str) -> Optional[AIInsightsResponse]:
    """
    Get cached insights if available and not expired.

    Args:
        cache_key: Cache key

    Returns:
        AIInsightsResponse if cached and valid, None otherwise
    """
    if cache_key not in insights_cache:
        return None

    cached_entry = insights_cache[cache_key]
    cached_time = cached_entry["timestamp"]
    now = datetime.now(timezone.utc)

    # Check if cache is still valid
    if (now - cached_time).total_seconds() < CACHE_TTL_SECONDS:
        logger.info(f"Cache HIT for key: {cache_key}")
        cached_data = cached_entry["data"]
        cached_data.cached = True
        return cached_data
    else:
        # Cache expired, remove it
        logger.info(f"Cache EXPIRED for key: {cache_key}")
        del insights_cache[cache_key]
        return None


def set_cached_insights(cache_key: str, insights: AIInsightsResponse) -> None:
    """
    Store insights in cache.

    Args:
        cache_key: Cache key
        insights: Insights to cache
    """
    insights_cache[cache_key] = {
        "data": insights,
        "timestamp": datetime.now(timezone.utc)
    }
    logger.info(f"Cached insights for key: {cache_key}")


async def generate_ai_insights(
    website_id: int,
    days: int,
    analytics_service: AnalyticsService,
    user_plan: str
) -> AIInsightsResponse:
    """
    Generate AI insights using Anthropic Claude API.

    Args:
        website_id: Website ID
        days: Number of days to analyze
        analytics_service: Analytics service instance
        user_plan: User's subscription plan

    Returns:
        AIInsightsResponse: Generated insights
    """
    logger.info(f"Generating AI insights for website {website_id} (plan: {user_plan})")

    # Get analytics data for the specified period
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)

    try:
        # Fetch dashboard stats
        stats = analytics_service.get_dashboard_stats(
            website_id=website_id,
            start_date=start_date,
            end_date=end_date
        )

        # For FREE tier, return 403 (should not get here due to quota check)
        if user_plan == 'free':
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="AI Insights are not available on the Free plan. Please upgrade to Starter or higher."
            )

        # Generate insights based on plan
        if user_plan == 'starter':
            # STARTER: Basic insights (limited)
            insights = await generate_basic_insights(website_id, stats, days)
        else:
            # PRO/BUSINESS: Full insights with Claude API
            insights = await generate_full_insights(website_id, stats, days)

        return insights

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating AI insights: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate AI insights. Please try again later."
        )


async def generate_basic_insights(
    website_id: int,
    stats: Dict[str, Any],
    days: int
) -> AIInsightsResponse:
    """
    Generate basic insights for STARTER plan (no AI API calls).

    Uses rule-based analysis instead of AI to reduce costs.

    Args:
        website_id: Website ID
        stats: Analytics stats
        days: Number of days analyzed

    Returns:
        AIInsightsResponse: Basic insights
    """
    logger.info(f"Generating BASIC insights for website {website_id}")

    traffic_trends = []
    content_insights = []
    recommendations = []

    # Calculate traffic trend (simple rule-based)
    total_pageviews = stats.get('total_pageviews', 0)
    unique_visitors = stats.get('unique_visitors', 0)

    if total_pageviews > 0:
        # Simple trend analysis
        avg_daily = total_pageviews / days
        trend_direction = "stable"
        percentage_change = 0.0

        if avg_daily > 100:
            trend_direction = "up"
            percentage_change = 15.0  # Mock percentage
        elif avg_daily < 20:
            trend_direction = "down"
            percentage_change = -10.0  # Mock percentage

        traffic_trends.append(TrafficTrendInsight(
            trend=trend_direction,
            percentage_change=percentage_change,
            description=f"Your website had {total_pageviews} pageviews from {unique_visitors} visitors in the last {days} days.",
            time_period=f"last {days} days"
        ))

    # Top pages insight
    top_pages = stats.get('top_pages', [])
    if top_pages and len(top_pages) > 0:
        top_page = top_pages[0]
        content_insights.append(ContentInsight(
            page_path=top_page.get('path', '/'),
            metric="pageviews",
            value=float(top_page.get('count', 0)),
            description=f"Your most popular page with {top_page.get('count', 0)} pageviews"
        ))

    # Basic recommendation
    recommendations.append(RecommendationInsight(
        category="engagement",
        priority="medium",
        title="Monitor your top pages",
        description="Focus on understanding what makes your top pages successful and apply those insights to other content.",
        impact="Can help improve overall site performance"
    ))

    # Generate summary
    summary = f"Your website received {total_pageviews} pageviews from {unique_visitors} unique visitors in the last {days} days."

    return AIInsightsResponse(
        website_id=website_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        traffic_trends=traffic_trends,
        content_insights=content_insights,
        recommendations=recommendations,
        summary=summary,
        cached=False
    )


async def generate_full_insights(
    website_id: int,
    stats: Dict[str, Any],
    days: int
) -> AIInsightsResponse:
    """
    Generate full insights using Anthropic Claude API (PRO/BUSINESS plans).

    Args:
        website_id: Website ID
        stats: Analytics stats
        days: Number of days analyzed

    Returns:
        AIInsightsResponse: AI-generated insights
    """
    logger.info(f"Generating FULL AI insights for website {website_id}")

    # Check if Anthropic API is configured
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not configured, falling back to basic insights")
        return await generate_basic_insights(website_id, stats, days)

    try:
        import anthropic

        # Prepare analytics data summary for Claude
        data_summary = f"""
Website Analytics Summary (Last {days} days):
- Total Pageviews: {stats.get('total_pageviews', 0)}
- Unique Visitors: {stats.get('unique_visitors', 0)}
- Bounce Rate: {stats.get('bounce_rate', 0)}%
- Avg Session Duration: {stats.get('avg_session_duration', 0)}s

Top Pages:
{format_top_pages(stats.get('top_pages', []))}

Traffic Sources:
{format_referrers(stats.get('top_referrers', []))}

Devices:
{format_devices(stats.get('devices', []))}

Countries:
{format_countries(stats.get('countries', []))}
"""

        # Call Claude API
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        response = client.messages.create(
            model="claude-3-haiku-20240307",  # Fast and cost-effective
            max_tokens=1000,
            system="""You are an expert web analytics consultant. Analyze the provided analytics data and provide:
1. Traffic trends (growth, decline, or stability)
2. Content insights (top performing pages, issues)
3. Actionable recommendations for improvement

Be concise, data-driven, and actionable. Format your response as JSON with these keys:
- traffic_trend: {trend: "up|down|stable", percentage: number, description: string}
- top_content: {page: string, metric: string, value: number, description: string}
- recommendation: {category: string, priority: "high|medium|low", title: string, description: string, impact: string}
- summary: string (1-2 sentences overall summary)""",
            messages=[
                {
                    "role": "user",
                    "content": f"Analyze this website analytics data:\n\n{data_summary}"
                }
            ]
        )

        # Parse Claude's response
        ai_response = response.content[0].text
        logger.debug(f"Claude response: {ai_response}")

        # Try to parse as JSON, fallback to basic parsing
        try:
            import json
            parsed = json.loads(ai_response)

            traffic_trends = []
            content_insights = []
            recommendations = []

            # Extract traffic trend
            if 'traffic_trend' in parsed:
                tt = parsed['traffic_trend']
                traffic_trends.append(TrafficTrendInsight(
                    trend=tt.get('trend', 'stable'),
                    percentage_change=float(tt.get('percentage', 0)),
                    description=tt.get('description', ''),
                    time_period=f"last {days} days"
                ))

            # Extract content insight
            if 'top_content' in parsed:
                tc = parsed['top_content']
                content_insights.append(ContentInsight(
                    page_path=tc.get('page', '/'),
                    metric=tc.get('metric', 'pageviews'),
                    value=float(tc.get('value', 0)),
                    description=tc.get('description', '')
                ))

            # Extract recommendation
            if 'recommendation' in parsed:
                rec = parsed['recommendation']
                recommendations.append(RecommendationInsight(
                    category=rec.get('category', 'general'),
                    priority=rec.get('priority', 'medium'),
                    title=rec.get('title', ''),
                    description=rec.get('description', ''),
                    impact=rec.get('impact', '')
                ))

            summary = parsed.get('summary', ai_response[:200])

        except json.JSONDecodeError:
            # If Claude didn't return JSON, create basic structure from text
            logger.warning("Claude didn't return JSON, using fallback parsing")
            traffic_trends = []
            content_insights = []
            recommendations = []
            summary = ai_response[:200]  # First 200 chars as summary

        return AIInsightsResponse(
            website_id=website_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            traffic_trends=traffic_trends,
            content_insights=content_insights,
            recommendations=recommendations,
            summary=summary,
            cached=False
        )

    except ImportError:
        logger.error("anthropic package not installed")
        return await generate_basic_insights(website_id, stats, days)
    except Exception as e:
        logger.error(f"Error calling Anthropic API: {e}", exc_info=True)
        # Fallback to basic insights
        return await generate_basic_insights(website_id, stats, days)


def format_top_pages(pages: list) -> str:
    """Format top pages for AI prompt."""
    if not pages:
        return "No data"
    return "\n".join([f"  - {p.get('path', 'N/A')}: {p.get('count', 0)} views" for p in pages[:5]])


def format_referrers(referrers: list) -> str:
    """Format referrers for AI prompt."""
    if not referrers:
        return "No data"
    return "\n".join([f"  - {r.get('referrer', 'Direct')}: {r.get('count', 0)} visits" for r in referrers[:5]])


def format_devices(devices: list) -> str:
    """Format devices for AI prompt."""
    if not devices:
        return "No data"
    return "\n".join([f"  - {d.get('device', 'Unknown')}: {d.get('count', 0)} ({d.get('percentage', 0)}%)" for d in devices])


def format_countries(countries: list) -> str:
    """Format countries for AI prompt."""
    if not countries:
        return "No data"
    return "\n".join([f"  - {c.get('country', 'Unknown')}: {c.get('count', 0)} visitors" for c in countries[:5]])


@router.get("/ai-insights/{website_id}", response_model=AIInsightsResponse)
async def get_ai_insights(
    website_id: int,
    days: int = Query(default=7, ge=1, le=90, description="Number of days to analyze"),
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    db: Session = Depends(get_db)
) -> AIInsightsResponse:
    """
    Get AI-generated insights for a website.

    This endpoint provides AI-powered analytics insights including:
    - Traffic trends and patterns
    - Content performance analysis
    - Actionable recommendations

    **Authentication:** Required (Bearer token or session cookie)

    **Plan Requirements:**
    - FREE: Not available (403 Forbidden)
    - STARTER: Basic insights (rule-based, cached heavily)
    - PRO: Full AI insights (3 refreshes/day via quota)
    - BUSINESS: Unlimited AI insights

    **Caching:** Results are cached for 1 hour to reduce costs

    **Rate Limiting:** Controlled by AI quota system

    Args:
        website_id: ID of the website to analyze
        days: Number of days to analyze (1-90, default 7)
        current_user: Authenticated user (from dependency)
        website_service: Website service instance
        analytics_service: Analytics service instance
        db: Database session

    Returns:
        AIInsightsResponse: AI-generated insights

    Raises:
        401: Not authenticated
        403: No AI quota or Free plan (no AI access)
        404: Website not found or no access
        429: AI quota exceeded
        500: AI service error

    Example:
        GET /api/v1/ai-insights/1?days=7
        Authorization: Bearer <token>

        Response:
        {
            "website_id": 1,
            "generated_at": "2025-11-01T12:00:00Z",
            "traffic_trends": [...],
            "content_insights": [...],
            "recommendations": [...],
            "summary": "Your traffic is growing steadily...",
            "cached": false
        }
    """
    logger.info(f"AI insights request: website_id={website_id}, days={days}, user={current_user.email}, plan={current_user.plan}")

    # 1. Verify website ownership
    website = website_service.get_website_by_id(website_id, current_user.email)
    if not website:
        logger.warning(f"Website {website_id} not found or access denied for user {current_user.email}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or access denied"
        )

    # 2. Check cache first (before quota check)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    cache_key = generate_cache_key(website_id, days, today)
    cached_insights = get_cached_insights(cache_key)

    if cached_insights:
        logger.info(f"Returning cached insights for website {website_id}")
        return cached_insights

    # 3. Check AI quota
    if not check_ai_quota_available(current_user, amount=1):
        logger.warning(f"AI quota exceeded for user {current_user.email} (plan: {current_user.plan})")

        # Return appropriate error based on plan
        if current_user.plan == 'free':
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="AI Insights are not available on the Free plan. Please upgrade to Starter or higher to unlock AI features."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"AI quota exceeded for this month. Your {current_user.plan.title()} plan allows limited AI requests. Try again next month or upgrade to Business for unlimited access."
            )

    # 4. Generate insights
    insights = await generate_ai_insights(
        website_id=website_id,
        days=days,
        analytics_service=analytics_service,
        user_plan=current_user.plan
    )

    # 5. Consume quota (only after successful generation)
    consume_success = consume_ai_quota(current_user, amount=1)
    if consume_success:
        db.commit()
        logger.info(f"AI quota consumed for user {current_user.email}: {current_user.ai_chatbot_used_this_month}/{current_user.ai_chatbot_quota}")
    else:
        logger.warning(f"Failed to consume AI quota for user {current_user.email}")

    # 6. Cache the results
    set_cached_insights(cache_key, insights)

    # 7. Return insights
    return insights
