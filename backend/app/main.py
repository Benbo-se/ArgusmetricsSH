"""
FastAPI application entry point for Argusmetrics.
Initializes the app, middleware, routers, and event handlers.
"""
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import check_db_connection, close_db_connection

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
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
# script-src keeps BOTH 'unsafe-inline' and 'unsafe-eval' because the
# dashboard runs stock Alpine.js, which evaluates its x-* attributes as
# strings — without 'unsafe-eval' every dropdown, filter, tab and modal in
# the app silently stops working (Alpine logs a CSP error per expression and
# renders every x-show element as visible).
#
# So CSP provides no script-injection protection here; the actual XSS defense
# is output escaping — template autoescape plus JSON <script> islands for
# visitor-controlled analytics data (never |tojson inside an attribute).
# TODO (UX phase): move to Alpine's CSP build (@alpinejs/csp, expressions as
# Alpine.data() components) or plain JS, then drop both unsafe-* sources.
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

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}' 'unsafe-eval'; "
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
@app.get("/health", tags=["Health"])
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for monitoring and load balancers.

    Returns:
        dict: Health status information
    """
    db_healthy = check_db_connection()

    return {
        "status": "healthy" if db_healthy else "unhealthy",
        "app_name": settings.APP_NAME,
        "version": "1.0.0",
        "database": "connected" if db_healthy else "disconnected",
        "debug": settings.DEBUG,
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
