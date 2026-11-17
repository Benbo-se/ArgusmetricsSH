"""The MCP endpoint: an AI assistant asking this instance for its statistics.

- POST /api/mcp  one JSON-RPC message in, one JSON answer out

MCP (Model Context Protocol) is how an assistant such as Claude calls tools on
a server somebody else runs. This is that server, for one purpose: reading a
website's statistics. Everything an assistant can reach is in this file.

Four decisions, each with its reason.

**It is a skin over the REST API, not a second way in.** A request
authenticates with a website's API token through the same function the REST
API uses (get_current_user_or_token), which also declares the row-level
security context. Every tool then calls the REST handler for its numbers, with
the arguments spelled out. So the access rule is written once: a website the
token cannot read at /api/v1/analytics/stats/{id} it cannot read here, and a
rule tightened there is tightened here without anyone remembering to.

**Read-only.** No tool creates, changes or deletes anything, and the list of
tools is short enough to check by eye. test_mcp.py holds the list and fails
when a tool is added without a decision.

**Only API tokens.** A session cookie or a session bearer is not accepted,
although the function underneath would take either. A session sees every
website its user can; a token sees one, and a credential pasted into an
assistant's configuration should be the narrow kind.

**The protocol is the official SDK's, not ours.** MCP has two eras on the
wire (the initialize handshake up to 2025-11-25, and the handshake-free
2026-07-28), and the `mcp` package serves both from one handler. It runs
stateless and answers in plain JSON: no sessions to keep, no stream held open,
nothing a second worker or a reverse proxy has to know about. The SDK's own
authorization layer is not used, because it is an OAuth resource server and
there is no authorization server here to point it at.

Off unless MCP_ENABLED is set. See the comment on the setting for why.
"""
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import AsyncIterator, Dict, List, Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.routers import analytics
from app.schemas.analytics import (
    DashboardStatsResponse,
    DimensionItem,
    GoalStatsResponse,
    RealtimeStatsResponse,
    TimeseriesDataPoint,
    TopCountryItem,
    TopPageItem,
    TopReferrerItem,
    UtmCampaignItem,
)
from app.services.analytics_service import AnalyticsService
from app.services.website_service import WebsiteService
from app.utils.date_helpers import site_timezone
from app.utils.network import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter()

#: Requests per minute from one address, counted before the token is looked
#: at, so guessing tokens is throttled as hard as using one. The same budget
#: as the tracking endpoints. An assistant answering one question makes a
#: handful of calls.
RATE_LIMIT_PER_MINUTE = 120

#: The ceiling nginx puts on every request body, held here as well so that it
#: does not depend on what is in front. A tool call is a few hundred bytes.
MAX_BODY_BYTES = 1024 * 1024

SERVER_INSTRUCTIONS = (
    "Read-only web analytics from an Argusmetrics instance. The API token in "
    "use belongs to one website: call list_sites to see which, and leave "
    "website_id out to mean that website. Dates are YYYY-MM-DD and are days in "
    "the website's own time zone. Without dates a report covers the last 30 "
    "days. Counts are pageviews unless a field says visitors."
)


# --- Who is calling --------------------------------------------------------


@dataclass(frozen=True)
class McpCaller:
    """The authenticated side of one MCP request."""

    #: The token's owner, carrying the scope marker the REST handlers check.
    user: User
    #: The request's session, with the row-level security context declared.
    db: Session
    #: The one website the token was minted for.
    website_id: int


# Set by the route for the length of one request and read by the tools. A
# context variable rather than an argument, because the SDK calls the tools
# and has no notion of this application's caller. There is no default: a tool
# reached without a caller must fail, not run as nobody.
_caller: ContextVar[McpCaller] = ContextVar("mcp_caller")


def _presented_token(request: Request) -> Optional[str]:
    """The API token a client sent, from either header it may use.

    `Authorization: Bearer` is what MCP clients know how to send. X-API-Token
    is this API's own header, accepted so a token works here the way it is
    documented to work everywhere else.
    """
    authorization = request.headers.get("Authorization", "")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return request.headers.get("X-API-Token") or None


async def authenticate_mcp_token(
    request: Request, db: Session = Depends(get_db)
) -> McpCaller:
    """Refuse, throttle, then authenticate, in that order.

    One function rather than three dependencies, because the order is the
    point and a dependency list does not promise one: a disabled endpoint must
    not answer differently for a good token than for a bad one, and the
    limiter must count the guesses that fail.
    """
    if not settings.MCP_ENABLED:
        # 404, not 403: an instance that has not turned this on has no such
        # endpoint, and says so the way any unknown path does.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    from app.middleware.rate_limit import rate_limiter

    if rate_limiter.is_rate_limited(
        f"mcp:ip:{get_client_ip(request)}",
        limit=RATE_LIMIT_PER_MINUTE,
        window_seconds=60,
    ):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    token = _presented_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="An API token is required: Authorization: Bearer <token>",
        )

    # Called directly rather than through Depends, so every argument is passed.
    # authorization and session_token are None on purpose: with a token given
    # the function never reaches its session branch, and it must not be handed
    # the means to.
    user = await analytics.get_current_user_or_token(
        authorization=None, x_api_token=token, session_token=None, db=db
    )

    website_id = getattr(user, "_api_token_website_id", None)
    if website_id is None:
        # Cannot happen while the call above is given a token. It is here so
        # that a change to that function fails closed rather than letting an
        # unscoped identity through.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token"
        )

    return McpCaller(user=user, db=db, website_id=website_id)


# --- The tools -------------------------------------------------------------
#
# Each one is the REST handler for the same numbers, called as a function.
# What a tool returns is cut from that handler's response model, so it can
# never hold a field the REST API would not have returned.


class SiteInfo(BaseModel):
    id: int = Field(..., description="Use as website_id in the other tools")
    name: str
    domain: str
    timezone: str = Field(..., description="IANA zone the website counts its days in")


class SiteList(BaseModel):
    sites: List[SiteInfo]


class Overview(BaseModel):
    total_pageviews: int
    unique_visitors: int
    timeseries: List[TimeseriesDataPoint] = Field(
        default_factory=list, description="Pageviews per day, or per hour"
    )


class TopPages(BaseModel):
    pages: List[TopPageItem]


class Sources(BaseModel):
    referrers: List[TopReferrerItem]
    utm_campaigns: List[UtmCampaignItem]


class Countries(BaseModel):
    countries: List[TopCountryItem]


class Devices(BaseModel):
    devices: Dict[str, int] = Field(..., description="Pageviews per device type")
    browsers: List[Dict[str, object]]
    operating_systems: List[DimensionItem]


def _current_caller() -> McpCaller:
    try:
        return _caller.get()
    except LookupError:
        # A tool running outside an authenticated request. Refuse rather than
        # guess whose data was meant.
        raise ToolError("Not authenticated")


async def _from_rest(call):
    """Await a REST handler and hand its refusal to the model as a tool error.

    The handlers refuse with HTTPException. To an assistant that is a turn in
    the conversation, "Website not found or access denied" or "Invalid date
    format", which it can read and correct, so it travels as a tool error and
    not as a protocol failure.
    """
    try:
        return await call
    except HTTPException as exc:
        raise ToolError(str(exc.detail))


async def _stats(
    website_id: Optional[int],
    start_date: Optional[str],
    end_date: Optional[str],
    interval: Optional[str] = None,
) -> DashboardStatsResponse:
    """GET /api/v1/analytics/stats/{website_id}, as that handler answers it."""
    caller = _current_caller()
    return await _from_rest(
        analytics.get_dashboard_stats(
            website_id=caller.website_id if website_id is None else website_id,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
            authorization=None,
            x_api_token=None,
            current_user=caller.user,
            analytics_service=AnalyticsService(caller.db),
            website_service=WebsiteService(caller.db),
        )
    )


async def list_sites() -> SiteList:
    """List the websites this API token can read. A token belongs to one
    website, so this is normally a single entry: its id, name, domain and
    time zone."""
    caller = _current_caller()
    website = WebsiteService(caller.db).get_website_by_id(
        caller.website_id, caller.user.email
    )
    if website is None:
        return SiteList(sites=[])
    return SiteList(
        sites=[
            SiteInfo(
                id=website.id,
                name=website.name,
                domain=website.domain,
                timezone=site_timezone(website),
            )
        ]
    )


async def get_overview(
    website_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    interval: Literal["day", "hour"] = "day",
) -> Overview:
    """Total pageviews and unique visitors for a period, with the pageviews
    per day (or per hour, for ranges of up to 31 days). Dates are YYYY-MM-DD in
    the website's time zone; without them the period is the last 30 days."""
    stats = await _stats(website_id, start_date, end_date, interval)
    return Overview(
        total_pageviews=stats.total_pageviews,
        unique_visitors=stats.unique_visitors,
        timeseries=stats.timeseries,
    )


async def get_top_pages(
    website_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> TopPages:
    """The most viewed pages in a period, by pageviews. Dates are YYYY-MM-DD
    in the website's time zone; without them the period is the last 30 days."""
    stats = await _stats(website_id, start_date, end_date)
    return TopPages(pages=stats.top_pages)


async def get_sources(
    website_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Sources:
    """Where visitors came from in a period: the top referrers and the top UTM
    campaigns, by pageviews. Dates are YYYY-MM-DD in the website's time zone;
    without them the period is the last 30 days."""
    stats = await _stats(website_id, start_date, end_date)
    return Sources(referrers=stats.top_referrers, utm_campaigns=stats.utm_campaigns)


async def get_countries(
    website_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Countries:
    """The countries visitors came from in a period, by pageviews, as
    two-letter country codes. Dates are YYYY-MM-DD in the website's time zone;
    without them the period is the last 30 days."""
    stats = await _stats(website_id, start_date, end_date)
    return Countries(countries=stats.top_countries)


async def get_devices(
    website_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Devices:
    """What visitors used in a period: device types, browsers and operating
    systems, by pageviews. Dates are YYYY-MM-DD in the website's time zone;
    without them the period is the last 30 days."""
    stats = await _stats(website_id, start_date, end_date)
    return Devices(
        devices=stats.devices,
        browsers=stats.top_browsers,
        operating_systems=stats.dimensions.get("os", []),
    )


async def get_goals(
    website_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> GoalStatsResponse:
    """The website's goals with their conversions and conversion rate in a
    period, and the number of visitors the rate is measured against. Dates are
    YYYY-MM-DD in the website's time zone; without them the period is the last
    30 days."""
    caller = _current_caller()
    return await _from_rest(
        analytics.get_goal_stats(
            website_id=caller.website_id if website_id is None else website_id,
            start_date=start_date,
            end_date=end_date,
            current_user=caller.user,
            analytics_service=AnalyticsService(caller.db),
            website_service=WebsiteService(caller.db),
        )
    )


async def get_realtime(website_id: Optional[int] = None) -> RealtimeStatsResponse:
    """What is happening now: visitors in the last five minutes, pageviews in
    the last hour, and the most recent pageviews with path and country."""
    caller = _current_caller()
    return await _from_rest(
        analytics.get_realtime_stats(
            website_id=caller.website_id if website_id is None else website_id,
            authorization=None,
            x_api_token=None,
            current_user=caller.user,
            analytics_service=AnalyticsService(caller.db),
            website_service=WebsiteService(caller.db),
        )
    )


#: Every tool there is. All of them read. Adding one that does not is a
#: decision about what a pasted token may do, and test_mcp.py asks for it.
TOOLS = (
    list_sites,
    get_overview,
    get_top_pages,
    get_sources,
    get_countries,
    get_devices,
    get_goals,
    get_realtime,
)

# What a client is told about each tool: it changes nothing, and it reaches
# nothing beyond this instance. Hints, as the protocol calls them, but a
# client that asks before running a tool that writes can skip asking here.
_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def build_server() -> MCPServer:
    """A server with the tools registered. Cheap, and built per run."""
    server = MCPServer(
        "Argusmetrics",
        instructions=SERVER_INSTRUCTIONS,
        version="1.0.0",
        # No change notifications: nothing here changes at a client's request,
        # and a listen stream is a response that never ends, which stateless
        # JSON answers have no place for.
        subscriptions=False,
        log_level=settings.LOG_LEVEL.upper(),
    )
    for tool in TOOLS:
        server.add_tool(tool, annotations=_READ_ONLY)
    return server


# --- Serving it ------------------------------------------------------------


def _transport_security() -> TransportSecuritySettings:
    """Which Host and Origin headers the transport answers to.

    The Host is the one in BASE_URL, the same value TrustedHostMiddleware
    holds in production. The Origin is this instance's own, so a page on some
    other site cannot drive the endpoint from a visitor's browser even with a
    token in hand. An assistant calls from a server and sends no Origin.
    """
    base = urlparse(settings.BASE_URL)
    hosts = [base.netloc, f"{base.hostname}:*"]
    if not settings.is_production:
        # Development is reached as localhost or by address, on whatever port
        # was mapped. Production is reached by its name only.
        hosts += ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[f"{base.scheme}://{base.netloc}"],
    )


# The running session manager, or None. Held in a list of one so the route
# reads whatever the current run put there.
_manager: List[Optional[StreamableHTTPSessionManager]] = [None]


@asynccontextmanager
async def mcp_runtime() -> AsyncIterator[None]:
    """Run the SDK's session manager for as long as the application runs.

    Entered from the application's lifespan. The SDK is explicit that the
    host application must do this, because a mounted sub-application's own
    lifespan never runs, and that a manager cannot be entered twice: so each
    run builds its own server and manager.

    stateless_http and json_response together mean a request is answered
    whole, in one JSON body, by whichever worker received it.
    """
    server = build_server()
    # The documented way to get a session manager: building the app creates
    # it. The app itself is not mounted, the route below calls the manager.
    server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        max_request_body_size=MAX_BODY_BYTES,
        transport_security=_transport_security(),
    )
    manager = server.session_manager
    async with manager.run():
        _manager[0] = manager
        try:
            yield
        finally:
            _manager[0] = None


@router.post("/api/mcp", include_in_schema=False)
async def mcp_endpoint(
    request: Request, caller: McpCaller = Depends(authenticate_mcp_token)
) -> Response:
    """Hand one authenticated request to the SDK and return its answer.

    A route with a dependency, like every other, rather than a mounted
    sub-application: the token is checked by this application's own code
    before the protocol layer sees a byte, and the session is the request's.

    POST only. The protocol also defines a GET, which opens a stream for
    messages the server sends unprompted, and a DELETE, which ends a session.
    This server sends nothing unprompted and keeps no session, and the
    protocol's answer for a server like that is 405, which is what a route
    without those methods gives. Handing a GET to the SDK instead would open
    a stream that never ends, and hold this request's database session open
    for as long as the client cared to wait.
    """
    manager = _manager[0]
    if manager is None:
        # Enabled in configuration but never started, which means the
        # lifespan did not run it. Say so instead of failing inside the SDK.
        logger.error("MCP request received but the session manager is not running")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP is not running",
        )

    # The SDK is an ASGI application and would write the response itself. A
    # POST is answered in one JSON body, so the body is collected and
    # returned the ordinary way, which keeps it inside this application's
    # middleware.
    answer_status = [status.HTTP_500_INTERNAL_SERVER_ERROR]
    answer_headers: Dict[str, str] = {}
    answer_body = bytearray()

    async def collect(message) -> None:
        if message["type"] == "http.response.start":
            answer_status[0] = message["status"]
            for name, value in message.get("headers", []):
                answer_headers[name.decode("latin-1")] = value.decode("latin-1")
        elif message["type"] == "http.response.body":
            answer_body.extend(message.get("body", b""))

    marker = _caller.set(caller)
    try:
        await manager.handle_request(request.scope, request.receive, collect)
    finally:
        _caller.reset(marker)

    # Recomputed by Response from the body it is given.
    answer_headers.pop("content-length", None)
    return Response(
        content=bytes(answer_body),
        status_code=answer_status[0],
        headers=answer_headers,
    )
