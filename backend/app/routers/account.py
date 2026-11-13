"""The account page, which so far is two-factor authentication.

Plain forms that post and render, like the admin page. No script decides
anything here: the secret, the QR code and the recovery codes are in the HTML
the server sends in answer to the one request that created them, and nowhere
else. They are never in a URL, never fetched by script, and the responses that
carry them are marked no-store.

Every change needs proof that it is the account holder asking and not just
their unlocked laptop: the password to turn it on, and the password plus a
current code to turn it off or to replace the recovery codes.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.routers.auth import get_current_user
from app.routers.dashboard import templates
from app.services import two_factor
from app.services.auth_service import _verify_password
from app.utils import totp
from app.utils.security import mask_email

logger = logging.getLogger(__name__)

router = APIRouter()


def _current_session_token(request: Request) -> Optional[str]:
    """The raw token of the session making this request, as get_current_user
    reads it: the Authorization header first, then the cookie."""
    authorization = request.headers.get("authorization")
    if authorization and authorization.startswith("Bearer "):
        return authorization.replace("Bearer ", "")
    return request.cookies.get("session_token")


def _qr_data_uri(uri: str) -> str:
    """The otpauth URI as a QR code, drawn here.

    Generated in this process and inlined as a data: image, so the secret
    goes from the server to the page and nowhere else. The usual shortcut, an
    <img> pointing at somebody's chart API, would hand the secret to a third
    party in a query string. img-src already allows data:, so the policy does
    not change.
    """
    import segno

    return segno.make(uri, error="m").svg_data_uri(scale=5, border=3, dark="#000", light="#fff")


def _render(request: Request, db: Session, user: User, status_code: int = 200, **extra):
    context = {
        "current_user": user,
        "enabled": user.two_factor_enabled,
        "enabled_at": user.totp_enabled_at,
        "codes_left": (
            two_factor.recovery_codes_left(db, user.email)
            if user.two_factor_enabled else 0
        ),
        "codes_total": two_factor.RECOVERY_CODE_COUNT,
        "has_password": bool(user.password_hash),
        **extra,
    }
    response = templates.TemplateResponse(
        request, "dashboard/account.html", context, status_code=status_code
    )
    if "setup_secret" in extra or "recovery_codes" in extra:
        response.headers["Cache-Control"] = "no-store"
    return response


def _render_setup(request: Request, db: Session, user: User, secret: str, **extra):
    uri = totp.provisioning_uri(secret, user.email, settings.APP_NAME)
    return _render(
        request, db, user,
        setup_secret=" ".join(secret[i:i + 4] for i in range(0, len(secret), 4)),
        setup_qr=_qr_data_uri(uri),
        **extra,
    )


def _password_problem(request: Request, user: User, password: str) -> Optional[str]:
    """Why the password does not count as proof, or None when it does.

    Limited per account, because this form is a place to guess a password
    from inside a session that was not opened with it (a stolen cookie).
    """
    from app.middleware.rate_limit import rate_limiter

    if rate_limiter.is_rate_limited(
        f"account-proof:email:{user.email}", limit=10, window_seconds=900
    ):
        return "Too many attempts. Please try again later."
    if not user.password_hash:
        return (
            "This account has no password yet. Set one with \"Forgot password?\" "
            "on the sign-in page first."
        )
    if not _verify_password(password, user.password_hash):
        return "That password is not right."
    return None


def _proof_problem(request: Request, db: Session, user: User, password: str, code: str) -> Optional[str]:
    """Password first, then a current code. None when both hold.

    In that order so that a session without the password cannot spend the
    account's code attempts and lock the owner out of signing in.
    """
    problem = _password_problem(request, user, password)
    if problem:
        return problem
    try:
        kind = two_factor.check_code(db, user, code)
    except two_factor.SecondFactorLocked:
        return f"Too many wrong codes. Wait {two_factor.LOCK_MINUTES} minutes and try again."
    if kind is None:
        return "That code is not valid."
    return None


@router.get("/login/2fa", response_class=HTMLResponse)
async def login_second_factor_page(request: Request, db: Session = Depends(get_db)):
    """Where a correct password lands for an account that needs a code."""
    pending = two_factor.resolve_pending_login(
        db, request.cookies.get(two_factor.PENDING_LOGIN_COOKIE)
    )
    if pending is None:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "auth/login_2fa.html", {
        "current_user": None,
    })


@router.get("/dashboard/account", response_class=HTMLResponse)
async def account_page(
    request: Request,
    recovery: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _render(
        request, db, current_user,
        signed_in_with_recovery_code=(recovery == "used" and current_user.two_factor_enabled),
    )


@router.post("/dashboard/account/2fa/start", response_class=HTMLResponse)
async def two_factor_start(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Make a secret and show it. Nothing about signing in changes yet."""
    try:
        secret = two_factor.begin_enrolment(db, current_user)
    except ValueError:
        return RedirectResponse(url="/dashboard/account", status_code=303)
    return _render_setup(request, db, current_user, secret)


@router.post("/dashboard/account/2fa/enable", response_class=HTMLResponse)
async def two_factor_enable(
    request: Request,
    password: str = Form(...),
    code: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Turn it on, once a code proves the authenticator has the secret."""
    secret = two_factor.pending_secret(current_user)
    if secret is None:
        return RedirectResponse(url="/dashboard/account", status_code=303)

    problem = _password_problem(request, current_user, password)
    if problem:
        return _render_setup(
            request, db, current_user, secret, status_code=400, setup_error=problem
        )

    try:
        codes = two_factor.confirm_enrolment(db, current_user, code)
    except ValueError:
        return RedirectResponse(url="/dashboard/account", status_code=303)
    if codes is None:
        return _render_setup(
            request, db, current_user, secret, status_code=400,
            setup_error=(
                "That code did not match. Check that the clock on your phone "
                "is right and enter the code it shows now."
            ),
        )

    signed_out = two_factor.revoke_sessions(
        db, current_user.email, keep_token=_current_session_token(request)
    )
    logger.info(
        f"Two-factor enabled by {mask_email(current_user.email)}; "
        f"{signed_out} other session(s) revoked"
    )
    return _render(
        request, db, current_user,
        recovery_codes=codes, just_enabled=True, signed_out=signed_out,
    )


@router.post("/dashboard/account/2fa/recovery-codes", response_class=HTMLResponse)
async def two_factor_new_recovery_codes(
    request: Request,
    password: str = Form(...),
    code: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace the recovery codes. The old ones stop working."""
    if not current_user.two_factor_enabled:
        return RedirectResponse(url="/dashboard/account", status_code=303)

    problem = _proof_problem(request, db, current_user, password, code)
    if problem:
        return _render(request, db, current_user, status_code=400, codes_error=problem)

    codes = two_factor.regenerate_recovery_codes(db, current_user)
    return _render(request, db, current_user, recovery_codes=codes)


@router.post("/dashboard/account/2fa/disable", response_class=HTMLResponse)
async def two_factor_disable(
    request: Request,
    password: str = Form(...),
    code: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Turn it off. Needs the password and a code, authenticator or recovery."""
    if not current_user.two_factor_enabled:
        return RedirectResponse(url="/dashboard/account", status_code=303)

    problem = _proof_problem(request, db, current_user, password, code)
    if problem:
        return _render(request, db, current_user, status_code=400, disable_error=problem)

    two_factor.disable(db, current_user.email)
    signed_out = two_factor.revoke_sessions(
        db, current_user.email, keep_token=_current_session_token(request)
    )
    return _render(request, db, current_user, just_disabled=True, signed_out=signed_out)
