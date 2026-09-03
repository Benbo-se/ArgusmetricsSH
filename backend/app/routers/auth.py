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

from app.database import get_db, set_rls_context
from app.utils.network import get_client_ip


async def _auth_rate_limit(request: Request):
    """Throttle auth endpoints per client IP (anti brute-force / email-bombing)."""
    from app.middleware.rate_limit import rate_limiter
    ip = get_client_ip(request)
    if rate_limiter.is_rate_limited(
        f"auth:{ip}",
        limit=settings.AUTH_RATE_LIMIT_ATTEMPTS,
        window_seconds=settings.AUTH_RATE_LIMIT_WINDOW_SECONDS,
    ):
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
    LoginRequest,
    VerifyCodeRequest,
    ResendVerificationRequest,
    RequestResetRequest,
    SetPasswordRequest,
)
from app.models.user import User
from app.config import settings

from app.utils.security import mask_email
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
    auth_service: AuthService = Depends(get_auth_service),
    db: Session = Depends(get_db)
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

    # Declare who this request acts as, so row-level security policies can
    # scope every query to this user. FastAPI caches get_db per request, so
    # this is the same session the route handler will use.
    set_rls_context(db, context="user", user_email=user.email)

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
    logger.info(f"Signup request received for email: {request.email}")

    # Anti-bot gates (zero friction for humans):
    # 1. Honeypot: the off-screen `website` field must stay empty. Bots that
    #    fill every field get a fake success and no account.
    if request.website:
        logger.warning("Signup honeypot triggered - rejecting silently")
        return SignupResponse(
            message="Verification email sent. Please check your inbox.",
            email=request.email,
        )
    # 2. Timing: the template stamps form_ts (epoch ms) at render; a submit
    #    faster than 3s is no human, older than 1h is a replay. API clients
    #    that omit the field entirely are allowed (it's a browser-flow gate).
    if request.form_ts is not None:
        import time
        elapsed = time.time() - (request.form_ts / 1000.0)
        if elapsed < 3 or elapsed > 3600:
            logger.warning(f"Signup timing gate triggered (elapsed={elapsed:.1f}s) - rejecting silently")
            return SignupResponse(
                message="Verification email sent. Please check your inbox.",
                email=request.email,
            )

    try:
        result = auth_service.signup_user(
            email=request.email, password=request.password, e2e_secret=x_e2e_secret
        )

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
    logger.info(f"Logout request for user: {mask_email(current_user.email)}")

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
    logger.debug(f"User info request for: {mask_email(current_user.email)}")

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
    logger.debug(f"Sessions list request for: {mask_email(current_user.email)}")

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




# ── Password auth, code verification, and reset ─────────────────────────────

def _set_session_cookie(response, session) -> None:
    """Attach the session cookie (same flags as the /verify page flow)."""
    response.set_cookie(
        key="session_token",
        value=session._raw_token,
        max_age=settings.SESSION_EXPIRY_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )


def _dual_rate_limit(request: Request, email: str, scope: str,
                     per_email: int, per_ip: int, window_seconds: int) -> None:
    """Rate-limit on BOTH the account and the client IP: per-account alone is
    dodgeable by rotating emails, per-IP alone by rotating accounts."""
    from app.middleware.rate_limit import rate_limiter
    ip = get_client_ip(request)
    limited = (
        rate_limiter.is_rate_limited(f"{scope}:email:{email.lower()}", limit=per_email, window_seconds=window_seconds)
        or rate_limiter.is_rate_limited(f"{scope}:ip:{ip}", limit=per_ip, window_seconds=window_seconds)
    )
    if limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
        )


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
):
    """Password login. Generic error for every failure mode."""
    from fastapi.responses import JSONResponse

    _dual_rate_limit(request, body.email, "login", per_email=10, per_ip=50, window_seconds=900)

    try:
        session = auth_service.login_user(email=body.email, password=body.password)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # A pending team invite takes precedence over the dashboard
    pending_invite = request.cookies.get("pending_invite")
    redirect = f"/accept-invite?token={pending_invite}" if pending_invite else "/dashboard"

    response = JSONResponse({"message": "Logged in", "email": body.email, "redirect": redirect})
    _set_session_cookie(response, session)
    if pending_invite:
        response.delete_cookie("pending_invite")
    return response


@router.post("/verify-code")
async def verify_code(
    body: VerifyCodeRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
):
    """Verify email with the 6-digit code (same completion as the magic link)."""
    from fastapi.responses import JSONResponse

    _dual_rate_limit(request, body.email, "verify-code", per_email=10, per_ip=50, window_seconds=900)

    try:
        session = auth_service.verify_email_code(email=body.email, code=body.code)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # A pending team invite takes precedence over the dashboard
    pending_invite = request.cookies.get("pending_invite")
    redirect = f"/accept-invite?token={pending_invite}" if pending_invite else "/dashboard"

    response = JSONResponse({"message": "Email verified", "redirect": redirect})
    _set_session_cookie(response, session)
    if pending_invite:
        response.delete_cookie("pending_invite")
    return response


@router.post("/resend-verification")
async def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
):
    """Re-send the verification email. Always the same answer (no enumeration)."""
    _dual_rate_limit(request, body.email, "resend", per_email=3, per_ip=20, window_seconds=3600)

    try:
        auth_service.resend_verification(email=body.email)
    except Exception as e:
        # Best-effort: never leak state through errors here
        logger.error(f"Resend verification failed: {e}", exc_info=True)

    return {"message": "If an unverified account exists for this email, a new verification email has been sent."}


@router.post("/request-reset")
async def request_reset(
    body: RequestResetRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
):
    """Request a password-reset link. Always the same answer (no enumeration)."""
    _dual_rate_limit(request, body.email, "reset", per_email=5, per_ip=20, window_seconds=3600)

    reset_url = None
    try:
        reset_url = auth_service.request_password_reset(email=body.email)
    except Exception as e:
        logger.error(f"Password reset request failed: {e}", exc_info=True)

    payload = {"message": "If an account exists for this email, a reset link has been sent."}
    # Dev-mode convenience only (mirrors the signup dev flow); never in prod.
    if reset_url:
        payload["reset_url"] = reset_url
    return payload


@router.post("/set-password")
async def set_password(
    body: SetPasswordRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
):
    """Complete a password reset; revokes all sessions and signs in fresh."""
    from fastapi.responses import JSONResponse

    ip = get_client_ip(request)
    from app.middleware.rate_limit import rate_limiter
    if rate_limiter.is_rate_limited(f"set-password:ip:{ip}", limit=10, window_seconds=900):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Too many attempts. Please try again later.")

    try:
        session = auth_service.set_password_with_token(token=body.token, new_password=body.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    response = JSONResponse({"message": "Password updated", "redirect": "/dashboard"})
    _set_session_cookie(response, session)
    return response


@router.get("/password-rules")
async def password_rules_info():
    """The password rule ids + minimum length, so UIs can render the live
    checklist from the same source the server enforces."""
    from app.utils.password_rules import RULES, MIN_LENGTH
    return {"rules": list(RULES), "min_length": MIN_LENGTH}
