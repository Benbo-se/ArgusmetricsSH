"""
FastAPI application entry point for Argusmetrics.
Initializes the app, middleware, routers, and event handlers.
"""
import logging
import time
import secrets
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from sqlalchemy.orm import Session

from app.config import settings
from app.logging_setup import configure_logging, set_request_id
from app.database import check_db_connection, close_db_connection, get_db

# Logging, with a request id on every line. See app/logging_setup.py: the id
# rides on a context variable so the five hundred existing logger calls did
# not have to change.
configure_logging(level=settings.LOG_LEVEL, fmt=settings.LOG_FORMAT)
logger = logging.getLogger(__name__)


# Lifespan context manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handle application lifespan events.

    Startup:
        - Check database connection (the schema is already migrated by the
          entrypoint; nothing here creates tables)
        - Start the background scheduler
        - Log application startup

    Shutdown:
        - Close database connections
        - Log application shutdown
    """
    # Startup
    logger.info(f"Starting {settings.APP_NAME}...")
    logger.info(f"Environment: {'Production' if settings.is_production else 'Development'}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info(f"Base URL: {settings.BASE_URL}")

    # Open registration with verification turned off lets anyone create an
    # account for an address they do not own, including one belonging to
    # somebody who has not signed up yet. Each setting is reasonable alone: a
    # closed instance does not need verification, and a public one requires
    # it. Together they are an open door, so a production process refuses to
    # start rather than serve in that state.
    if (
        settings.is_production
        and settings.ENABLE_REGISTRATION
        and not settings.ENABLE_EMAIL_VERIFICATION
    ):
        raise RuntimeError(
            "ENABLE_REGISTRATION is on while ENABLE_EMAIL_VERIFICATION is off. "
            "Anyone could then register an address they do not own. Turn "
            "verification on (and configure email), or close registration."
        )

    # Check database connection
    if not check_db_connection():
        logger.error("Failed to connect to database")
        raise RuntimeError("Database connection failed")

    logger.info("Database connection established successfully")

    # No create_all here, in any environment. The entrypoint runs
    # `alembic upgrade head` before this process starts, so the schema is
    # already there, and creating tables from the models alongside that only
    # ever hid a missing migration: a new model would appear in development
    # with no migration behind it, everything would work locally, and the
    # table would be absent in production. Migrations are the only way the
    # schema changes.

    # Start background scheduler for cleanup tasks
    from app.scheduled_tasks import get_scheduler
    scheduler = get_scheduler()
    logger.info("Background scheduler initialized")

    logger.info(f"{settings.APP_NAME} started successfully")

    yield  # Application runs here

    # Shutdown
    logger.info(f"Shutting down {settings.APP_NAME}...")

    # Shutdown scheduler
    if scheduler:
        scheduler.shutdown()
        logger.info("Background scheduler shut down")

    await close_db_connection()
    logger.info(f"{settings.APP_NAME} shut down successfully")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="Argusmetrics Analytics Platform - Privacy-first analytics for your websites",
    version="1.0.0",
    docs_url="/api/docs" if settings.DEBUG else None,  # Disable docs in production
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)


# Add CORS middleware.
# Origin is "*" because the public tracking endpoints (/track, /track-event,
# /track-ecommerce) are called from every customer's website. This is safe only
# because credentials are NOT allowed (no cookies cross-origin) and the dashboard
# authenticates via a same-origin httponly cookie, so a wildcard origin cannot be
# used to make credentialed cross-origin reads of authenticated data.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
    allow_origin_regex=None,
)


# Add trusted host middleware for production
if settings.is_production:
    allowed_hosts = [settings.BASE_URL.replace("https://", "").replace("http://", "")]
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=allowed_hosts,
    )


# Security headers (defense-in-depth: clickjacking, MIME sniffing, and a CSP
# that limits script/style sources).
#
# script-src now carries no unsafe-* source at all. Scripts run only from this
# origin or with the request's nonce, so an injected <script> does not
# execute, and neither does an injected string reaching eval.
#
# Getting there took removing both. 'unsafe-inline' went when every inline
# handler became a data attribute read by one delegated listener and every
# inline <script> gained a nonce. 'unsafe-eval' went when the dashboard moved
# to Alpine's CSP build: stock Alpine compiles each x-* attribute with
# new AsyncFunction, which is eval by another name, and that one directive
# re-permitted the whole class of attack the policy exists to stop.
#
# The CSP build evaluates an expression as a single scope lookup, so all 246
# expressions that were doing more than naming a property moved into
# alpine-components.js as getters and methods. Anything reintroducing an
# operator, a literal or a call with arguments into an x-* attribute will
# stop working rather than fail quietly; test_csp.py checks for it.
#
# Output escaping remains the primary defence, tested directly in
# test_output_escaping.py. CSP is the second layer, and now it is a real one.
#
# style-src, unlike script-src, HAS been locked to 'self' with no unsafe-*:
# every literal style="" attribute and <style> block was moved to
# theme.css/component classes, and the 2 Alpine :style bindings that built a
# CSS string (setAttribute-equivalent, CSP-blocked) switched to the
# object-literal form (CSSOM .style.setProperty, never gated by style-src).
@app.middleware("http")
async def security_headers(request: Request, call_next):
    # A fresh nonce per request, which every inline <script> in the templates
    # carries. That is what lets script-src drop 'unsafe-inline': an injected
    # <script> or onerror= handler has no nonce and does not run, even if the
    # escaping that is supposed to stop it ever fails.
    #
    # 'unsafe-eval' stays. Alpine evaluates its x-* attributes with new
    # Function(), so without it every dropdown, tab and modal in the dashboard
    # silently stops working. Removing it means moving ~250 expressions into
    # Alpine.data() components against the CSP build, which is worth doing and
    # is a separate piece of work.
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce

    # Adopted from the incoming header when a proxy already set one, so a
    # trace stays continuous across hops, otherwise minted here.
    request_id = set_request_id(request.headers.get("X-Request-Id"))
    request.state.request_id = request_id

    response = await call_next(request)

    # Returned so a customer can quote it from the page they were looking at,
    # which turns "it broke around two" into one line in the log.
    response.headers["X-Request-Id"] = request_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    return response


# Global exception handlers
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Handle HTTP exceptions with consistent JSON response format.

    Args:
        request: The incoming request
        exc: The HTTP exception

    Returns:
        JSONResponse: Formatted error response
    """
    logger.warning(f"HTTP {exc.status_code} error: {exc.detail} - Path: {request.url.path}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.detail,
            "status_code": exc.status_code,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handle request validation errors with detailed error messages.

    Args:
        request: The incoming request
        exc: The validation exception

    Returns:
        JSONResponse: Formatted validation error response
    """
    # Pydantic v2 puts the raw exception object in each error's `ctx` for
    # model_validator failures — not JSON-serializable, which used to turn
    # every such 422 into a 500 inside this very handler.
    errors = [
        {k: (str(v) if k == "ctx" else v) for k, v in err.items() if k != "input"}
        for err in exc.errors()
    ]
    logger.warning(f"Validation error: {errors} - Path: {request.url.path}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": True,
            "message": "Validation error",
            "details": errors,
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle unexpected exceptions with generic error message.

    Args:
        request: The incoming request
        exc: The exception

    Returns:
        JSONResponse: Formatted error response
    """
    logger.error(f"Unexpected error: {exc} - Path: {request.url.path}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": True,
            "message": "Internal server error" if settings.is_production else str(exc),
        },
    )


# Health check endpoint
# How long each scheduled job may go without a success before something is
# wrong. Generous compared to the schedule, because one missed run is a
# restart and three is a problem.
# When this process started, so a job that has never run is only judged once
# it has had the chance. Without it a fresh deployment reports degraded until
# the first nightly job fires, which is crying wolf on every single deploy and
# is the fastest way to teach people to ignore the endpoint.
_STARTED_AT = time.monotonic()

JOB_MAX_AGE_SECONDS = {
    "daily_cleanup": 36 * 3600,     # runs 02:00 daily
    "email_reports": 36 * 3600,     # runs 07:00 daily
    "traffic_alerts": 3 * 3600,     # runs hourly at :05
}


def _job_health(db) -> Dict[str, Any]:
    """When each scheduled job last succeeded, and whether that is too long ago.

    Takes the request's session rather than opening its own, like every other
    route. Read without a row-level security context on purpose: job_runs
    holds nothing tenant-specific and this endpoint has no user.

    It reports rather than raises. A health endpoint that fails because of its
    own bookkeeping is worse than one that says less.
    """
    from datetime import datetime, timezone

    from sqlalchemy import text

    out: Dict[str, Any] = {}
    try:
        rows = {
            r.job_name: r
            for r in db.execute(
                text(
                    "SELECT job_name, last_success_at, last_error,"
                    "       consecutive_failures, last_duration_ms FROM job_runs"
                )
            )
        }
    except Exception as exc:
        logger.warning(f"Could not read job health: {exc}")
        return {}

    now = datetime.now(timezone.utc)
    for name, max_age in JOB_MAX_AGE_SECONDS.items():
        row = rows.get(name)
        age = None
        if row is not None and row.last_success_at is not None:
            age = int((now - row.last_success_at).total_seconds())

        uptime = time.monotonic() - _STARTED_AT
        if age is not None:
            overdue = age > max_age
        else:
            # Never succeeded. Only a problem once this process has been up
            # long enough that it should have.
            overdue = uptime > max_age

        out[name] = {
            "seconds_since_success": age,
            "overdue": overdue,
            "max_age_seconds": max_age,
            "consecutive_failures": row.consecutive_failures if row else 0,
            "last_error": row.last_error if row else None,
            "last_duration_ms": row.last_duration_ms if row else None,
        }
    return out


@app.get("/health", tags=["Health"])
async def health_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Health check endpoint for monitoring and load balancers.

    Returns:
        dict: Health status information
    """
    db_healthy = check_db_connection()
    jobs = _job_health(db)

    # A stalled job makes the instance degraded rather than down: the site is
    # serving and tracking is recording, but something that should be
    # happening is not. An uptime check watching only "healthy" would never
    # have noticed the traffic-alert job doing nothing for weeks, which is the
    # case this exists for.
    stalled = [name for name, j in jobs.items() if j["overdue"]]

    if not db_healthy:
        status = "unhealthy"
    elif stalled:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "app_name": settings.APP_NAME,
        "version": "1.0.0",
        "database": "connected" if db_healthy else "disconnected",
        "debug": settings.DEBUG,
        "jobs": jobs,
        "stalled_jobs": stalled,
    }


# Robots.txt endpoint
@app.get("/robots.txt", tags=["SEO"])
async def robots_txt():
    """
    Serve robots.txt for search engine crawlers.
    Blocks private sections and points to sitemap.
    """
    from fastapi.responses import PlainTextResponse

    content = f"""Sitemap: {settings.BASE_URL}/sitemap.xml

User-agent: *
Disallow: /dashboard
Disallow: /dashboard/*
Disallow: /api/
Disallow: /verify
Disallow: /ws
"""
    return PlainTextResponse(content=content)


# Sitemap.xml endpoint
@app.get("/sitemap.xml", tags=["SEO"])
async def sitemap_xml():
    """
    Serve sitemap.xml for search engines.
    Includes all public pages.
    """
    from fastapi.responses import Response
    from datetime import datetime

    base_url = settings.BASE_URL
    today = datetime.utcnow().strftime("%Y-%m-%d")

    # Only the app's own public pages; the marketing site ships its own
    # sitemap (site/sitemap.xml), which nginx serves ahead of this one.
    urls = [
        {"loc": f"{base_url}/", "priority": "1.0", "changefreq": "daily"},
        {"loc": f"{base_url}/login", "priority": "0.9", "changefreq": "monthly"},
    ]

    # Build XML
    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    for url in urls:
        xml_content += '  <url>\n'
        xml_content += f'    <loc>{url["loc"]}</loc>\n'
        xml_content += f'    <lastmod>{today}</lastmod>\n'
        xml_content += f'    <changefreq>{url["changefreq"]}</changefreq>\n'
        xml_content += f'    <priority>{url["priority"]}</priority>\n'
        xml_content += '  </url>\n'

    xml_content += '</urlset>'

    return Response(content=xml_content, media_type="application/xml")


# Import and include routers
from app.routers import auth, websites, analytics, dashboard, websocket, dashboard_password, email_reports, revenue, funnels, anomaly

app.include_router(
    auth.router,
    prefix=f"{settings.API_V1_PREFIX}/auth",
    tags=["Authentication"],
)

app.include_router(
    websites.router,
    prefix=f"{settings.API_V1_PREFIX}/websites",
    tags=["Websites"],
)

app.include_router(
    analytics.router,
    prefix=f"{settings.API_V1_PREFIX}/analytics",
    tags=["Analytics"],
)

# Include revenue router
app.include_router(
    revenue.router,
    prefix=f"{settings.API_V1_PREFIX}",
    tags=["Revenue"],
)

# Include funnels router
app.include_router(
    funnels.router,
    prefix=f"{settings.API_V1_PREFIX}",
    tags=["Funnels"],
)

# Include anomaly detection router
app.include_router(
    anomaly.router,
    prefix=f"{settings.API_V1_PREFIX}",
    tags=["Anomaly Detection"],
)

# Include Dashboard Password router
app.include_router(
    dashboard_password.router,
    tags=["Dashboard Password"],
)

# Include Email Reports router
app.include_router(
    email_reports.router,
    tags=["Email Reports"],
)

# Include WebSocket router
app.include_router(
    websocket.router,
    tags=["WebSocket"],
)

# Include dashboard router (HTML pages)
app.include_router(
    dashboard.router,
    tags=["Dashboard"],
)

# Favicon route (browsers look for /favicon.ico first)
from fastapi.responses import FileResponse

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve favicon.ico from static directory."""
    import os
    favicon_path = os.path.join(os.path.dirname(__file__), "static", "favicon.ico")
    return FileResponse(favicon_path, media_type="image/x-icon")

# Mount static files (tracking script and dashboard assets)
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    logger.info(f"Static files mounted at /static from {static_dir}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
