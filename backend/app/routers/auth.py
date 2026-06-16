"""
Authentication router for user signup, verification, and session management.

Provides endpoints for:
- POST /signup - Register new user with email
- GET /verify - Verify email with magic link token
- GET /logout - Log out and delete session
- GET /me - Get current user info (requires authentication)
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header, Cookie, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.utils.network import get_client_ip


async def _auth_rate_limit(request: Request):
    """Throttle auth endpoints per client IP (anti brute-force / email-bombing)."""
    from app.middleware.rate_limit import rate_limiter
    ip = get_client_ip(request)
    if rate_limiter.is_rate_limited(f"auth:{ip}", limit=10, window_seconds=300):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again in a few minutes.",
        )
from app.services.auth_service import AuthService
from app.schemas.auth import (
    SignupRequest,
    SignupResponse,
    VerifyResponse,
    LogoutResponse,
    ErrorResponse,
)
from app.models.user import User

logger = logging.getLogger(__name__)

# Create router
router = APIRouter()


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    """
    Dependency to get AuthService instance.

    Args:
        db: Database session from FastAPI dependency

    Returns:
        AuthService: Initialized auth service
    """
    return AuthService(db)


def get_current_user(
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None),
    auth_service: AuthService = Depends(get_auth_service)
) -> User:
    """
    Dependency to get current authenticated user.

    Checks for session token in Authorization header or session_token cookie.
    Validates the session and returns the user if authenticated.

    Args:
        authorization: Authorization header (format: "Bearer <token>")
        session_token: Session token from cookie
        auth_service: Auth service instance

    Returns:
        User: Current authenticated user

    Raises:
        HTTPException: If not authenticated or session invalid

    Example:
        @router.get("/protected")
        def protected_route(user: User = Depends(get_current_user)):
            return {"email": user.email}
    """
    # Try to get token from Authorization header first
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
    elif session_token:
        token = session_token

    if not token:
        logger.debug("No authentication token provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate session
    user = auth_service.validate_session(token)

    if not user:
        logger.debug("Invalid or expired session token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug(f"Authenticated user: {user.email}")
    return user


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_auth_rate_limit)],
    responses={
        201: {
            "description": "User created successfully, verification email sent",
            "model": SignupResponse
        },
        400: {
            "description": "Invalid email format",
            "model": ErrorResponse
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse
        }
    }
)
async def signup(
    request: SignupRequest,
    x_e2e_secret: Optional[str] = Header(None, alias="X-E2E-Secret"),
    auth_service: AuthService = Depends(get_auth_service)
) -> SignupResponse:
    """
    Register a new user with email.

    Creates a new user account and sends a magic link to the provided email
    for verification. If the email is already registered and verified, returns
    a generic success message to prevent email enumeration.

    Args:
        request: Signup request containing email
        auth_service: Auth service instance

    Returns:
        SignupResponse: Success message and email

    Raises:
        HTTPException: 400 if email format is invalid
        HTTPException: 500 if server error occurs

    Example:
        POST /auth/signup
        {
            "email": "user@example.com"
        }

        Response:
        {
            "message": "Verification email sent. Please check your inbox.",
            "email": "user@example.com"
        }
    """
    logger.info(f"Signup request received for email: {request.email}, plan: {request.plan}")

    try:
        result = auth_service.signup_user(email=request.email, plan=request.plan, e2e_secret=x_e2e_secret)

        return SignupResponse(
            message=result["message"],
            email=result["email"],
            verify_url=result.get("verify_url")
        )

    except ValueError as e:
        logger.warning(f"Validation error during signup: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    except Exception as e:
        logger.error(f"Unexpected error during signup: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during signup. Please try again."
        )


@router.get(
    "/verify",
    response_model=VerifyResponse,
    dependencies=[Depends(_auth_rate_limit)],
    responses={
        200: {
            "description": "Email verified successfully, session created",
            "model": VerifyResponse
        },
        400: {
            "description": "Invalid or expired token",
            "model": ErrorResponse
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse
        }
    }
)
async def verify_email(
    token: str,
    auth_service: AuthService = Depends(get_auth_service)
) -> VerifyResponse:
    """
    Verify email address using magic link token.

    Validates the magic link token from the verification email, marks the
    user as verified, and creates a new authentication session.

    Args:
        token: Magic link token from verification email (query parameter)
        auth_service: Auth service instance

    Returns:
        VerifyResponse: Success message, email, session token, and expiration

    Raises:
        HTTPException: 400 if token is invalid or expired
        HTTPException: 500 if server error occurs

    Example:
        GET /auth/verify?token=InVzZXJAZXhhbXBsZS5jb20i.ZkF8Xw.1a2b3c4d5e6f

        Response:
        {
            "message": "Email verified successfully",
            "email": "user@example.com",
            "session_token": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
            "expires_at": "2024-01-15T12:00:00Z"
        }
    """
    logger.info("Email verification request received")

    try:
        session = auth_service.verify_email(token)

        return VerifyResponse(
            message="Email verified successfully. You are now logged in.",
            email=session.user_email,
            session_token=session._raw_token,
            expires_at=session.expires_at.isoformat()
        )

    except ValueError as e:
        logger.warning(f"Validation error during verification: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    except Exception as e:
        logger.error(f"Unexpected error during verification: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during verification. Please try again."
        )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    responses={
        200: {
            "description": "Logged out successfully",
            "model": LogoutResponse
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        }
    }
)
async def logout(
    current_user: User = Depends(get_current_user),
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None),
    auth_service: AuthService = Depends(get_auth_service)
) -> LogoutResponse:
    """
    Log out current user by deleting their session.

    Requires authentication. Deletes the session token from the database,
    effectively logging the user out.

    Args:
        current_user: Current authenticated user (from dependency)
        authorization: Authorization header with session token
        session_token: Session token from cookie
        auth_service: Auth service instance

    Returns:
        LogoutResponse: Success message

    Raises:
        HTTPException: 401 if not authenticated

    Example:
        POST /auth/logout
        Authorization: Bearer a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6

        Response:
        {
            "message": "Logged out successfully"
        }
    """
    logger.info(f"Logout request for user: {current_user.email}")

    # Get token from header or cookie
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
    elif session_token:
        token = session_token

    try:
        success = auth_service.logout_user(token)

        if success:
            return LogoutResponse(
                message="Logged out successfully"
            )
        else:
            # This shouldn't happen since we validated the session,
            # but handle it just in case
            return LogoutResponse(
                message="Already logged out"
            )

    except Exception as e:
        logger.error(f"Unexpected error during logout: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during logout. Please try again."
        )


@router.get(
    "/me",
    responses={
        200: {
            "description": "Current user information"
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        }
    }
)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Get current authenticated user information.

    Requires authentication. Returns basic user profile information.

    Args:
        current_user: Current authenticated user (from dependency)

    Returns:
        dict: User information

    Raises:
        HTTPException: 401 if not authenticated

    Example:
        GET /auth/me
        Authorization: Bearer a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6

        Response:
        {
            "id": 1,
            "email": "user@example.com",
            "is_verified": true,
            "created_at": "2024-01-01T12:00:00Z"
        }
    """
    logger.debug(f"User info request for: {current_user.email}")

    return {
        "id": current_user.id,
        "email": current_user.email,
        "is_verified": current_user.is_verified,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


@router.get(
    "/sessions",
    responses={
        200: {
            "description": "List of active sessions"
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        }
    }
)
async def get_user_sessions(
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
) -> dict:
    """
    Get all active sessions for the current user.

    Requires authentication. Returns list of all active sessions
    for the authenticated user.

    Args:
        current_user: Current authenticated user (from dependency)
        auth_service: Auth service instance

    Returns:
        dict: List of active sessions

    Example:
        GET /auth/sessions
        Authorization: Bearer a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6

        Response:
        {
            "sessions": [
                {
                    "token": "a1b2c3d4...",
                    "created_at": "2024-01-01T12:00:00Z",
                    "expires_at": "2024-01-08T12:00:00Z"
                }
            ]
        }
    """
    logger.debug(f"Sessions list request for: {current_user.email}")

    try:
        sessions = auth_service.get_user_sessions(current_user.email)

        return {
            "sessions": [
                {
                    "token": session.token[:20] + "...",  # Only show first 20 chars
                    "created_at": session.created_at.isoformat() if session.created_at else None,
                    "expires_at": session.expires_at.isoformat(),
                }
                for session in sessions
            ]
        }

    except Exception as e:
        logger.error(f"Error getting user sessions: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching sessions."
        )


@router.get("/me/monthly-usage")
async def get_monthly_usage(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """
    Get current month's pageview usage for authenticated user.

    Calculates real-time pageview count from all user's websites
    for the current month. Used for auto-refreshing usage displays.

    Args:
        current_user: Current authenticated user (from dependency)
        db: Database session

    Returns:
        dict: Monthly usage information

    Example:
        GET /auth/me/monthly-usage
        Authorization: Bearer a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6

        Response:
        {
            "monthly_pageviews": 255,
            "pageview_limit": 10000,
            "usage_percentage": 2,
            "plan": "free"
        }
    """
    logger.debug(f"Monthly usage request for: {current_user.email}")

    try:
        from sqlalchemy import text
        from datetime import datetime, timezone

        # Get user's websites via team_members
        website_result = db.execute(text("""
            SELECT DISTINCT w.id
            FROM websites w
            JOIN team_members tm ON w.id = tm.website_id
            WHERE tm.user_email = :email
        """), {"email": current_user.email})

        website_ids = [row[0] for row in website_result.fetchall()]

        # Get start of current month
        now = datetime.now(timezone.utc)
        month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

        # Count pageviews this month
        monthly_pageviews = 0
        if website_ids:
            result = db.execute(text("""
                SELECT COUNT(*)
                FROM pageviews
                WHERE website_id = ANY(:website_ids)
                AND timestamp >= :month_start
            """), {
                "website_ids": website_ids,
                "month_start": month_start
            })
            monthly_pageviews = result.scalar() or 0

        # Determine pageview limit based on plan
        pageview_limit = 10000  # FREE
        if current_user.plan == 'starter':
            pageview_limit = 100000
        elif current_user.plan == 'pro':
            pageview_limit = 500000
        elif current_user.plan == 'business':
            pageview_limit = 1000000

        # Calculate usage percentage
        usage_percentage = 0
        if pageview_limit > 0:
            usage_percentage = min(100, int((monthly_pageviews / pageview_limit) * 100))

        return {
            "monthly_pageviews": monthly_pageviews,
            "pageview_limit": pageview_limit,
            "usage_percentage": usage_percentage,
            "plan": current_user.plan,
            "website_count": len(website_ids)
        }

    except Exception as e:
        logger.error(f"Error getting monthly usage: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching usage data."
        )
