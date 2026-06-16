"""
Pydantic schemas for analytics endpoints.

Defines request and response models for:
- Pageview tracking
- Dashboard statistics
- Realtime analytics
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, List, Any
from datetime import datetime

# Limits for custom-event / goal-conversion ``properties`` payloads. These cap
# the PII surface area: properties are meant for low-cardinality segmentation
# values, NOT personal data. Keys/values are bounded so a misconfigured tracker
# cannot exfiltrate large blobs of (potentially personal) data into analytics.
MAX_PROPERTY_KEYS = 50
MAX_PROPERTY_STRING_LENGTH = 500


def validate_event_properties(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Cap the size of a custom-event ``properties`` mapping.

    Rejects payloads with too many keys, or with string keys/values longer than
    the allowed limit. Properties MUST NOT contain PII (emails, names, raw user
    input, etc.); these bounds keep the payload to small segmentation values.
    """
    if value is None:
        return None

    if len(value) > MAX_PROPERTY_KEYS:
        raise ValueError(
            f"Too many properties: {len(value)} (max {MAX_PROPERTY_KEYS}). "
            f"Properties are for segmentation values and must not contain PII."
        )

    for key, val in value.items():
        if isinstance(key, str) and len(key) > MAX_PROPERTY_STRING_LENGTH:
            raise ValueError(
                f"Property key too long (max {MAX_PROPERTY_STRING_LENGTH} chars). "
                f"Properties must not contain PII."
            )
        if isinstance(val, str) and len(val) > MAX_PROPERTY_STRING_LENGTH:
            raise ValueError(
                f"Property value for '{key}' too long "
                f"(max {MAX_PROPERTY_STRING_LENGTH} chars). "
                f"Properties must not contain PII."
            )

    return value


class PageviewTrackRequest(BaseModel):
    """
    Request schema for tracking a pageview.

    Sent from the tracking script on the customer's website.
    Does not include visitor identifiers - those are generated
    server-side from IP + User-Agent for privacy.

    Attributes:
        tracking_code: Website tracking code (identifies which site)
        path: Page path being viewed (e.g., "/blog/post-1")
        referrer: Referrer URL (where visitor came from)
        screen_width: Screen width in pixels (for device type detection)
        screen_height: Screen height in pixels (for device type detection)
        scroll_depth: Maximum scroll depth reached (0-100 percentage)
        utm_source: UTM source parameter (e.g., 'google', 'newsletter')
        utm_medium: UTM medium parameter (e.g., 'cpc', 'email')
        utm_campaign: UTM campaign parameter (e.g., 'summer_sale')
        utm_content: UTM content parameter (e.g., 'banner_ad')
        utm_term: UTM term parameter (e.g., 'running_shoes')
        properties: Custom key-value properties for segmentation

    Example:
        {
            "tracking_code": "a1b2c3d4",
            "path": "/blog/post-1",
            "referrer": "https://google.com",
            "screen_width": 1920,
            "screen_height": 1080,
            "scroll_depth": 75,
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "summer_sale"
        }
    """
    tracking_code: str = Field(
        ...,
        description="Website tracking code",
        min_length=8,
        max_length=8,
        example="a1b2c3d4"
    )
    path: str = Field(
        ...,
        description="Page path being viewed",
        max_length=2048,
        example="/blog/post-1"
    )
    referrer: Optional[str] = Field(
        default=None,
        description="Referrer URL (where visitor came from)",
        max_length=2048,
        example="https://google.com"
    )
    screen_width: Optional[int] = Field(
        default=None,
        description="Screen width in pixels for device detection",
        ge=0,
        le=10000,
        example=1920
    )
    screen_height: Optional[int] = Field(
        default=None,
        description="Screen height in pixels for device detection",
        ge=0,
        le=10000,
        example=1080
    )
    scroll_depth: Optional[int] = Field(
        default=None,
        description="Maximum scroll depth reached (0-100 percentage)",
        ge=0,
        le=100,
        example=75
    )
    utm_source: Optional[str] = Field(
        default=None,
        description="UTM source parameter",
        max_length=255,
        example="google"
    )
    utm_medium: Optional[str] = Field(
        default=None,
        description="UTM medium parameter",
        max_length=255,
        example="cpc"
    )
    utm_campaign: Optional[str] = Field(
        default=None,
        description="UTM campaign parameter",
        max_length=255,
        example="summer_sale"
    )
    utm_content: Optional[str] = Field(
        default=None,
        description="UTM content parameter",
        max_length=255,
        example="banner_ad"
    )
    utm_term: Optional[str] = Field(
        default=None,
        description="UTM term parameter",
        max_length=255,
        example="running_shoes"
    )
    properties: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Custom properties as key-value pairs for segmentation. "
            "Must NOT contain PII (no emails, names, or raw user input). "
            f"Max {MAX_PROPERTY_KEYS} keys; keys/values capped at "
            f"{MAX_PROPERTY_STRING_LENGTH} characters."
        ),
        example={"userId": "123", "plan": "pro", "experiment": "A"}
    )
    debug: Optional[bool] = Field(
        default=False,
        description="Debug mode flag - when true, event is NOT recorded in analytics but IS sent to debug WebSocket"
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Ensure path starts with /."""
        if not v.startswith("/"):
            return f"/{v}"
        return v

    @field_validator("properties")
    @classmethod
    def validate_properties(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Cap property count/length so the payload cannot carry PII blobs."""
        return validate_event_properties(v)

    class Config:
        json_schema_extra = {
            "example": {
                "tracking_code": "a1b2c3d4",
                "path": "/blog/post-1",
                "referrer": "https://google.com",
                "screen_width": 1920,
                "screen_height": 1080,
                "scroll_depth": 75,
                "utm_source": "google",
                "utm_medium": "cpc",
                "utm_campaign": "summer_sale",
                "properties": {"userId": "123", "plan": "pro"}
            }
        }


class PageviewTrackResponse(BaseModel):
    """
    Response schema for successful pageview tracking.

    Attributes:
        success: Always true for successful tracking
        message: Success message

    Example:
        {
            "success": true,
            "message": "Pageview recorded"
        }
    """
    success: bool = Field(
        default=True,
        description="Indicates successful tracking"
    )
    message: str = Field(
        default="Pageview recorded",
        description="Success message"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Pageview recorded"
            }
        }


class TopPageItem(BaseModel):
    """
    Schema for a top page item.

    Attributes:
        path: Page path
        views: Number of pageviews
    """
    path: str = Field(..., description="Page path")
    views: int = Field(..., description="Number of pageviews")


class TopCountryItem(BaseModel):
    """
    Schema for a top country item.

    Attributes:
        country: Country code (e.g., 'SE', 'NO', 'DK')
        views: Number of pageviews
    """
    country: str = Field(..., description="Country code")
    views: int = Field(..., description="Number of pageviews")


class TopReferrerItem(BaseModel):
    """
    Schema for a top referrer item.

    Attributes:
        referrer: Referrer URL
        views: Number of pageviews
    """
    referrer: str = Field(..., description="Referrer URL")
    views: int = Field(..., description="Number of pageviews")


class UtmCampaignItem(BaseModel):
    """
    Schema for a UTM campaign item.

    Attributes:
        utm_source: UTM source (e.g., 'google', 'newsletter')
        utm_medium: UTM medium (e.g., 'cpc', 'email')
        utm_campaign: UTM campaign name (e.g., 'summer_sale')
        views: Number of pageviews
    """
    utm_source: Optional[str] = Field(None, description="UTM source")
    utm_medium: Optional[str] = Field(None, description="UTM medium")
    utm_campaign: Optional[str] = Field(None, description="UTM campaign")
    views: int = Field(..., description="Number of pageviews")


class TimeseriesDataPoint(BaseModel):
    """
    Schema for a timeseries data point.

    Attributes:
        date: Date in ISO format
        views: Number of pageviews on that date
    """
    date: str = Field(..., description="Date in ISO format")
    views: int = Field(..., description="Number of pageviews")


class ComparisonData(BaseModel):
    """
    Schema for comparison data with previous period.

    Attributes:
        pageviews_change: Percentage change in pageviews
        visitors_change: Percentage change in unique visitors
        avg_views_change: Percentage change in average views per visitor
        prev_pageviews: Previous period pageviews count
        prev_visitors: Previous period unique visitors count
    """
    pageviews_change: Optional[float] = Field(
        None,
        description="Percentage change in pageviews"
    )
    visitors_change: Optional[float] = Field(
        None,
        description="Percentage change in unique visitors"
    )
    avg_views_change: Optional[float] = Field(
        None,
        description="Percentage change in average views per visitor"
    )
    prev_pageviews: int = Field(
        default=0,
        description="Previous period pageviews count"
    )
    prev_visitors: int = Field(
        default=0,
        description="Previous period unique visitors count"
    )


class DashboardStatsResponse(BaseModel):
    """
    Response schema for dashboard statistics.

    Contains all analytics data for the dashboard view:
    - Overview metrics (total pageviews, unique visitors)
    - Top pages, countries, referrers
    - Device breakdown
    - Timeseries data for graphs

    Attributes:
        total_pageviews: Total number of pageviews in period
        unique_visitors: Number of unique visitors in period
        top_pages: List of top viewed pages
        top_countries: List of top countries by pageviews
        devices: Device type breakdown (desktop, mobile, tablet)
        top_referrers: List of top referrer sources
        timeseries: Pageview data over time for graphing

    Example:
        {
            "total_pageviews": 12345,
            "unique_visitors": 8234,
            "top_pages": [
                {"path": "/", "views": 2345},
                {"path": "/blog", "views": 1234}
            ],
            "top_countries": [
                {"country": "SE", "views": 4567},
                {"country": "NO", "views": 2345}
            ],
            "devices": {
                "desktop": 6500,
                "mobile": 4500,
                "tablet": 1345
            },
            "top_referrers": [
                {"referrer": "https://google.com", "views": 3456}
            ],
            "timeseries": [
                {"date": "2024-01-01", "views": 120},
                {"date": "2024-01-02", "views": 145}
            ]
        }
    """
    total_pageviews: int = Field(
        ...,
        description="Total number of pageviews in period",
        ge=0
    )
    unique_visitors: int = Field(
        ...,
        description="Number of unique visitors in period",
        ge=0
    )
    top_pages: List[TopPageItem] = Field(
        default_factory=list,
        description="List of top viewed pages"
    )
    top_countries: List[TopCountryItem] = Field(
        default_factory=list,
        description="List of top countries by pageviews"
    )
    devices: Dict[str, int] = Field(
        default_factory=dict,
        description="Device type breakdown"
    )
    top_browsers: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of top browsers by pageviews"
    )
    top_referrers: List[TopReferrerItem] = Field(
        default_factory=list,
        description="List of top referrer sources"
    )
    utm_campaigns: List[UtmCampaignItem] = Field(
        default_factory=list,
        description="List of top UTM campaigns"
    )
    timeseries: List[TimeseriesDataPoint] = Field(
        default_factory=list,
        description="Pageview data over time for graphing"
    )
    comparison: Optional[ComparisonData] = Field(
        None,
        description="Comparison data with previous period (if requested)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "total_pageviews": 12345,
                "unique_visitors": 8234,
                "top_pages": [
                    {"path": "/", "views": 2345},
                    {"path": "/blog", "views": 1234}
                ],
                "top_countries": [
                    {"country": "SE", "views": 4567},
                    {"country": "NO", "views": 2345}
                ],
                "devices": {
                    "desktop": 6500,
                    "mobile": 4500,
                    "tablet": 1345
                },
                "top_referrers": [
                    {"referrer": "https://google.com", "views": 3456}
                ],
                "timeseries": [
                    {"date": "2024-01-01", "views": 120},
                    {"date": "2024-01-02", "views": 145}
                ]
            }
        }


class LiveVisitor(BaseModel):
    """
    Schema for a live visitor.

    Attributes:
        country: Country code
        path: Current page path
        timestamp: When they viewed the page
    """
    country: Optional[str] = Field(None, description="Country code")
    path: str = Field(..., description="Current page path")
    timestamp: str = Field(..., description="ISO timestamp")


class RealtimeStatsResponse(BaseModel):
    """
    Response schema for realtime analytics.

    Shows current visitors and recent activity.

    Attributes:
        current_visitors: Number of visitors online now (last 5 minutes)
        recent_pageviews: Pageviews in last hour
        live_visitors: List of recent visitor activity

    Example:
        {
            "current_visitors": 12,
            "recent_pageviews": 145,
            "live_visitors": [
                {"country": "SE", "path": "/blog", "timestamp": "2024-01-01T12:00:00Z"}
            ]
        }
    """
    current_visitors: int = Field(
        ...,
        description="Number of visitors online now (last 5 minutes)",
        ge=0
    )
    recent_pageviews: int = Field(
        ...,
        description="Pageviews in last hour",
        ge=0
    )
    live_visitors: List[LiveVisitor] = Field(
        default_factory=list,
        description="List of recent visitor activity",
        max_length=50
    )

    class Config:
        json_schema_extra = {
            "example": {
                "current_visitors": 12,
                "recent_pageviews": 145,
                "live_visitors": [
                    {"country": "SE", "path": "/blog", "timestamp": "2024-01-01T12:00:00Z"},
                    {"country": "NO", "path": "/pricing", "timestamp": "2024-01-01T11:59:55Z"}
                ]
            }
        }


# Goal Tracking Schemas

class GoalCreate(BaseModel):
    """
    Schema for creating a new goal.

    Attributes:
        name: Human-readable goal name (e.g., "Newsletter Signup")
        event_name: Event identifier for tracking (e.g., "newsletter_signup")
    """
    name: str = Field(
        ...,
        description="Human-readable goal name",
        min_length=1,
        max_length=255,
        example="Newsletter Signup"
    )
    event_name: str = Field(
        ...,
        description="Event identifier used in tracking code",
        min_length=1,
        max_length=255,
        pattern="^[a-z0-9_]+$",
        example="newsletter_signup"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Newsletter Signup",
                "event_name": "newsletter_signup"
            }
        }


class GoalResponse(BaseModel):
    """
    Schema for goal response.

    Attributes:
        id: Goal ID
        website_id: Website ID
        name: Goal name
        event_name: Event identifier
        created_at: When goal was created
    """
    id: int
    website_id: int
    name: str
    event_name: str
    created_at: datetime

    class Config:
        from_attributes = True


class GoalConversionRequest(BaseModel):
    """
    Schema for tracking a goal conversion event or custom event with properties.

    Attributes:
        tracking_code: Website tracking code
        event_name: Event identifier to track
        properties: Optional key-value properties for the event
    """
    tracking_code: str = Field(
        ...,
        description="Website tracking code",
        min_length=8,
        max_length=8,
        example="a1b2c3d4"
    )
    event_name: str = Field(
        ...,
        description="Event identifier to track",
        min_length=1,
        max_length=500,
        example="newsletter_signup"
    )
    properties: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional key-value properties for the event. "
            "Must NOT contain PII (no emails, names, or raw user input). "
            f"Max {MAX_PROPERTY_KEYS} keys; keys/values capped at "
            f"{MAX_PROPERTY_STRING_LENGTH} characters."
        ),
        example={"url": "https://example.com", "text": "Click here", "from_page": "/home"}
    )

    @field_validator("properties")
    @classmethod
    def validate_properties(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Cap property count/length so the payload cannot carry PII blobs."""
        return validate_event_properties(v)

    class Config:
        json_schema_extra = {
            "example": {
                "tracking_code": "a1b2c3d4",
                "event_name": "newsletter_signup",
                "properties": {"source": "homepage", "variant": "blue"}
            }
        }


class GoalConversionResponse(BaseModel):
    """
    Response schema for goal conversion tracking.

    Attributes:
        success: Whether conversion was recorded
        message: Success/error message
    """
    success: bool = Field(default=True)
    message: str = Field(default="Conversion recorded")


class GoalStatsItem(BaseModel):
    """
    Schema for individual goal stats.

    Attributes:
        goal_id: Goal ID
        name: Goal name
        event_name: Event identifier
        conversions: Total conversions
        conversion_rate: Conversion rate as percentage
    """
    goal_id: int
    name: str
    event_name: str
    conversions: int
    conversion_rate: float = Field(description="Conversion rate as percentage (0-100)")


class GoalStatsResponse(BaseModel):
    """
    Response schema for goal statistics.

    Attributes:
        goals: List of goal stats
        total_visitors: Total unique visitors in period
    """
    goals: List[GoalStatsItem] = Field(default_factory=list)
    total_visitors: int


# API Token Schemas

class ApiTokenCreate(BaseModel):
    """
    Schema for creating a new API token.

    Attributes:
        name: Human-readable token name (e.g., "Production Server")
    """
    name: str = Field(
        ...,
        description="Human-readable token name",
        min_length=1,
        max_length=255,
        example="Production Server"
    )


class ApiTokenResponse(BaseModel):
    """
    Schema for API token response.

    Attributes:
        id: Token ID
        name: Token name
        token: The actual token (only shown once on creation)
        created_at: When token was created
    """
    id: int
    name: str
    token: Optional[str] = Field(None, description="Only shown once on creation")
    created_at: datetime

    class Config:
        from_attributes = True


class ApiTokenListItem(BaseModel):
    """
    Schema for API token list item (without token value).

    Attributes:
        id: Token ID
        name: Token name
        created_at: When token was created
        last_used_at: When token was last used
    """
    id: int
    name: str
    created_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Alert Settings Schemas

class AlertSettingsUpdate(BaseModel):
    """
    Schema for updating alert settings.

    Attributes:
        spike_threshold: Traffic spike threshold multiplier (1.5 = 150%)
        email_enabled: Whether to send email alerts
    """
    spike_threshold: float = Field(
        default=2.0,
        ge=1.5,
        le=5.0,
        description="Traffic spike threshold (1.5 = 150%, 2.0 = 200%)"
    )
    email_enabled: bool = Field(default=True)


class AlertSettingsResponse(BaseModel):
    """
    Schema for alert settings response.

    Attributes:
        website_id: Website ID
        spike_threshold: Traffic spike threshold
        email_enabled: Whether email alerts are enabled
        alert_email: Email address for alerts
    """
    website_id: int
    spike_threshold: float
    email_enabled: bool
    alert_email: str

    class Config:
        from_attributes = True


# Custom Events Schemas

class CustomEventCreate(BaseModel):
    """
    Schema for tracking a custom event with properties.

    Attributes:
        tracking_code: Website tracking code
        event_name: Name of the event (e.g., 'button_click', 'video_play')
        properties: Optional key-value properties (e.g., {button: 'CTA', color: 'blue'})
    """
    tracking_code: str = Field(
        ...,
        description="Website tracking code",
        min_length=8,
        max_length=8,
        example="a1b2c3d4"
    )
    event_name: str = Field(
        ...,
        description="Event name to track",
        min_length=1,
        max_length=255,
        example="button_click"
    )
    properties: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional custom properties as key-value pairs. "
            "Must NOT contain PII (no emails, names, or raw user input). "
            f"Max {MAX_PROPERTY_KEYS} keys; keys/values capped at "
            f"{MAX_PROPERTY_STRING_LENGTH} characters."
        ),
        example={"button": "signup", "variant": "blue", "page": "home"}
    )

    @field_validator("properties")
    @classmethod
    def validate_properties(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Cap property count/length so the payload cannot carry PII blobs."""
        return validate_event_properties(v)

    class Config:
        json_schema_extra = {
            "example": {
                "tracking_code": "a1b2c3d4",
                "event_name": "button_click",
                "properties": {
                    "button": "signup",
                    "variant": "blue",
                    "page": "home"
                }
            }
        }


class CustomEventResponse(BaseModel):
    """
    Schema for custom event response.

    Attributes:
        id: Event ID
        website_id: Website ID
        event_name: Event name
        properties: Event properties
        path: Page path where event occurred
        referrer: Referrer URL
        country: Country code
        device_type: Device type
        browser: Browser name
        timestamp: When event occurred
    """
    id: int
    website_id: int
    event_name: str
    properties: Optional[Dict[str, Any]] = None
    path: Optional[str] = None
    referrer: Optional[str] = None
    country: Optional[str] = None
    device_type: Optional[str] = None
    browser: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True


class CustomEventSummaryItem(BaseModel):
    """
    Schema for custom event summary item.

    Attributes:
        event_name: Event name
        count: Total number of times event was triggered
        unique_users: Number of unique visitors who triggered event
        avg_per_user: Average times per user
        top_properties: Most common property keys
    """
    event_name: str
    count: int
    unique_users: int
    avg_per_user: float
    top_properties: List[str] = Field(
        default_factory=list,
        description="Top 3 most common property keys"
    )


class CustomEventsSummary(BaseModel):
    """
    Schema for custom events summary (dashboard view).

    Attributes:
        events: List of event summaries
        total_events: Total number of events tracked in period
    """
    events: List[CustomEventSummaryItem] = Field(default_factory=list)
    total_events: int


class PropertyBreakdownItem(BaseModel):
    """
    Schema for property breakdown.

    Attributes:
        property_key: Property key name
        property_value: Property value
        count: Number of times this value appeared
    """
    property_key: str
    property_value: str
    count: int


class CustomEventDetail(BaseModel):
    """
    Schema for custom event detail view.

    Attributes:
        event_name: Event name
        total_count: Total occurrences
        unique_users: Unique users who triggered event
        events: List of individual event instances
        property_breakdown: Breakdown by property values
    """
    event_name: str
    total_count: int
    unique_users: int
    events: List[CustomEventResponse] = Field(default_factory=list)
    property_breakdown: List[PropertyBreakdownItem] = Field(default_factory=list)
