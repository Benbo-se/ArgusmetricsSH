"""Two-factor authentication: TOTP, with single-use recovery codes.

Opt-in per account. The rules, each of which has a test that fails when it is
broken (tests/test_two_factor.py):

  - **An account needs a second factor exactly when totp_enabled_at is set.**
    Starting an enrolment stores a secret and nothing else. Until a code from
    it has been proved, sign-in is unchanged, so closing the tab halfway locks
    nobody out.
  - **A correct password is not a session.** For an enrolled account it earns
    a short-lived signed token that only the code step reads. It is never a
    row in `sessions`, so nothing that validates a session accepts it.
  - **create_session refuses an enrolled account** unless the caller states
    that the second factor was passed. Every way of signing in ends there, so
    a path that forgets the second step fails closed instead of signing in.
  - **A code works once.** The time step of the last accepted code is stored
    and only later steps are accepted, so a code seen over a shoulder or in a
    proxy log is dead even though its thirty seconds are not up.
  - **Guesses are counted per account, in the database.** The limiter the
    other auth endpoints use lives in the process, which multiplies every
    limit by the worker count and forgets on restart. A six-digit code is the
    one place that arithmetic matters.
  - **Recovery codes** are shown once, stored as SHA-256, and each is marked
    used in the same transaction that accepts it.
"""
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.session import Session as SessionModel
from app.models.two_factor_recovery_code import TwoFactorRecoveryCode
from app.models.used_magic_token import UsedMagicToken
from app.models.user import User
from app.utils import secret_box, totp
from app.utils.security import hash_token, mask_email

logger = logging.getLogger(__name__)

#: The label the secret is sealed under (see utils/secret_box.py).
SECRET_PURPOSE = "totp-secret"

#: Wrong codes in a row before the account's code step is closed for a while.
#: Five per quarter of an hour is 480 guesses a day against three live codes
#: in a million, for someone who already has the password.
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15

RECOVERY_CODE_COUNT = 10
#: No 0, 1, I or O: these are typed by hand from a piece of paper.
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
#: Sixteen symbols of five bits each. Eighty bits is what lets the stored hash
#: be a plain SHA-256: there is nothing to brute-force, salted or not.
RECOVERY_CODE_LENGTH = 16

#: How long a correct password stays good for while the code is typed.
PENDING_LOGIN_SECONDS = 300
PENDING_LOGIN_COOKIE = "login_2fa"


class SecondFactorRequired(ValueError):
    """A session was asked for an enrolled account without the second factor.

    A ValueError so that a caller which only knows "ValueError means refuse"
    refuses. The login route catches it by name and starts the code step.
    """

    def __init__(self, user: User):
        super().__init__("This account needs a sign-in code. Please sign in.")
        self.user = user


class SecondFactorLocked(Exception):
    """Too many wrong codes. Nothing is checked until `until`."""

    def __init__(self, until: datetime):
        super().__init__("Too many wrong codes")
        self.until = until


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _locked_row(db: Session, email: str) -> Optional[User]:
    """The user row, locked until this transaction ends and read fresh.

    Counting an attempt, checking the last accepted step and marking a
    recovery code used all have to see each other's writes. With the row
    locked, two requests carrying the same code are checked one after the
    other and the second finds the step already taken.
    """
    return (
        db.query(User)
        .filter(User.email == email)
        .populate_existing()
        .with_for_update()
        .first()
    )


# --- recovery codes ----------------------------------------------------------

def normalise_recovery_code(code: str) -> str:
    """What was typed, reduced to what is hashed: no dashes, spaces or case."""
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def _format_recovery_code(raw: str) -> str:
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def _replace_recovery_codes(db: Session, email: str) -> List[str]:
    """Throw away every code the account has and make a fresh set.

    Returns the codes as they are shown, which is the only time they exist in
    the clear. Does not commit: the caller commits them together with whatever
    made them necessary.
    """
    db.query(TwoFactorRecoveryCode).filter(
        TwoFactorRecoveryCode.user_email == email
    ).delete()
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(
            secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH)
        )
        db.add(TwoFactorRecoveryCode(user_email=email, code_hash=hash_token(raw)))
        codes.append(_format_recovery_code(raw))
    return codes


def recovery_codes_left(db: Session, email: str) -> int:
    return (
        db.query(TwoFactorRecoveryCode)
        .filter(
            TwoFactorRecoveryCode.user_email == email,
            TwoFactorRecoveryCode.used_at.is_(None),
        )
        .count()
    )


# --- enrolment ---------------------------------------------------------------

def begin_enrolment(db: Session, user: User) -> str:
    """Store a new secret for an account that has not proved it yet.

    Returns the secret for display. Starting again replaces the previous
    unproved secret, which is harmless: nothing asks for a code until
    confirm_enrolment has seen one.
    """
    row = _locked_row(db, user.email)
    if row is None or row.two_factor_enabled:
        db.rollback()
        raise ValueError("Two-factor authentication is already on for this account.")
    secret = totp.generate_secret()
    row.totp_secret_enc = secret_box.seal(secret, SECRET_PURPOSE)
    db.commit()
    return secret


def pending_secret(user: User) -> Optional[str]:
    """The secret of an enrolment that was started and not finished."""
    if user.two_factor_enabled:
        return None
    return secret_box.unseal(user.totp_secret_enc, SECRET_PURPOSE)


def confirm_enrolment(db: Session, user: User, code: str) -> Optional[List[str]]:
    """Turn two-factor authentication on, if the code proves the secret.

    Returns the recovery codes, or None when the code is wrong, in which case
    nothing has changed and the account still signs in with its password
    alone.
    """
    row = _locked_row(db, user.email)
    if row is None or row.two_factor_enabled:
        db.rollback()
        raise ValueError("Two-factor authentication is already on for this account.")

    secret = secret_box.unseal(row.totp_secret_enc, SECRET_PURPOSE)
    step = totp.matching_step(secret, code) if secret else None
    if step is None:
        db.rollback()
        return None

    row.totp_enabled_at = _now()
    # The code that proved the secret is spent like any other.
    row.totp_last_step = step
    row.totp_failed_attempts = 0
    row.totp_locked_until = None
    codes = _replace_recovery_codes(db, row.email)
    db.commit()
    logger.info(f"Two-factor authentication enabled for {mask_email(row.email)}")
    return codes


def disable(db: Session, email: str) -> bool:
    """Turn it off and forget everything about it. True if it was on.

    Also clears an unfinished enrolment and a lock, so this is what the
    operator command calls whatever state the account is in.
    """
    row = _locked_row(db, email)
    if row is None:
        db.rollback()
        return False
    was_enabled = row.two_factor_enabled
    row.totp_secret_enc = None
    row.totp_enabled_at = None
    row.totp_last_step = None
    row.totp_failed_attempts = 0
    row.totp_locked_until = None
    db.query(TwoFactorRecoveryCode).filter(
        TwoFactorRecoveryCode.user_email == email
    ).delete()
    db.commit()
    if was_enabled:
        logger.info(f"Two-factor authentication disabled for {mask_email(email)}")
    return was_enabled


def regenerate_recovery_codes(db: Session, user: User) -> List[str]:
    """A fresh set of recovery codes. Every earlier one stops working."""
    row = _locked_row(db, user.email)
    if row is None or not row.two_factor_enabled:
        db.rollback()
        raise ValueError("Two-factor authentication is not on for this account.")
    codes = _replace_recovery_codes(db, row.email)
    db.commit()
    logger.info(f"Recovery codes regenerated for {mask_email(row.email)}")
    return codes


def revoke_sessions(db: Session, email: str, keep_token: Optional[str] = None) -> int:
    """Sign the account out everywhere, except the session doing the asking.

    Turning two-factor authentication on is a statement that the password is
    no longer enough, and a session opened with only the password is exactly
    that. Turning it off is a change someone else on the account should not
    sleep through. `keep_token` is the raw token of the current session.
    """
    query = db.query(SessionModel).filter(SessionModel.user_email == email)
    if keep_token:
        query = query.filter(SessionModel.token != hash_token(keep_token))
    removed = query.delete()
    db.commit()
    return removed


# --- checking a code ---------------------------------------------------------

def check_code(db: Session, user: User, code: str) -> Optional[str]:
    """Check a code for an enrolled account: "totp", "recovery", or None.

    Six digits is tried as an authenticator code, anything else as a recovery
    code. A code that is accepted is spent before this returns: the time step
    is recorded, or the recovery code is marked used.

    Raises SecondFactorLocked while the account is closed after too many wrong
    codes. A correct code is not looked at during that time either, otherwise
    the lock would only slow down the guesses that were wrong anyway.
    """
    row = _locked_row(db, user.email)
    if row is None or not row.two_factor_enabled:
        db.rollback()
        return None

    now = _now()
    locked_until = _aware(row.totp_locked_until)
    if locked_until and locked_until > now:
        db.rollback()
        raise SecondFactorLocked(locked_until)

    kind = None
    candidate = (code or "").strip()

    if len(candidate) == totp.DIGITS and candidate.isascii() and candidate.isdigit():
        secret = secret_box.unseal(row.totp_secret_enc, SECRET_PURPOSE)
        if secret:
            step = totp.matching_step(secret, candidate, after_step=row.totp_last_step)
            if step is not None:
                row.totp_last_step = step
                kind = "totp"
    else:
        normalised = normalise_recovery_code(candidate)
        if len(normalised) == RECOVERY_CODE_LENGTH:
            match = (
                db.query(TwoFactorRecoveryCode)
                .filter(
                    TwoFactorRecoveryCode.user_email == row.email,
                    TwoFactorRecoveryCode.code_hash == hash_token(normalised),
                    TwoFactorRecoveryCode.used_at.is_(None),
                )
                .first()
            )
            if match is not None:
                match.used_at = now
                kind = "recovery"

    if kind is None:
        row.totp_failed_attempts = (row.totp_failed_attempts or 0) + 1
        if row.totp_failed_attempts >= MAX_FAILED_ATTEMPTS:
            row.totp_locked_until = now + timedelta(minutes=LOCK_MINUTES)
            row.totp_failed_attempts = 0
            logger.warning(
                f"Two-factor code step locked for {mask_email(row.email)} "
                f"after {MAX_FAILED_ATTEMPTS} wrong codes"
            )
        db.commit()
        return None

    row.totp_failed_attempts = 0
    row.totp_locked_until = None
    db.commit()
    if kind == "recovery":
        logger.warning(f"Recovery code used for {mask_email(row.email)}")
    return kind


# --- between the password and the code ---------------------------------------

def _pending_serializer() -> URLSafeTimedSerializer:
    # Its own salt, so this token and the magic links cannot stand in for
    # each other even though the same key signs both.
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt="login-second-factor")


def _password_state(user: User) -> str:
    """A fingerprint of the password this token was earned with.

    Baked into the token so that changing the password, which is what someone
    does on learning it leaked, also ends any sign-in waiting at the code step.
    """
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"login-second-factor:{user.password_hash or ''}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]


def issue_pending_login(user: User) -> str:
    """What a correct password earns an enrolled account: not a session.

    A signed statement that this account's password was just given. It is
    stored nowhere on the server and matches no row in `sessions`, so every
    route that asks for a session treats it as no session at all.
    """
    return _pending_serializer().dumps(
        {"e": user.email, "p": _password_state(user), "j": secrets.token_urlsafe(16)}
    )


def resolve_pending_login(db: Session, token: Optional[str]) -> Optional[Tuple[User, str]]:
    """The account a pending sign-in is for and its id, or None.

    None for anything that should send the person back to the password: no
    token, a bad or expired one, one already used, an account that no longer
    has two-factor authentication, or a password changed since.
    """
    if not token:
        return None
    try:
        payload = _pending_serializer().loads(token, max_age=PENDING_LOGIN_SECONDS)
    except BadSignature:  # SignatureExpired is a BadSignature
        return None
    if not isinstance(payload, dict):
        return None
    email, state, jti = payload.get("e"), payload.get("p"), payload.get("j")
    if not email or not state or not jti:
        return None

    user = db.query(User).filter(User.email == email).first()
    if user is None or not user.is_verified or not user.two_factor_enabled:
        return None
    if not hmac.compare_digest(str(state), _password_state(user)):
        return None
    used = db.query(UsedMagicToken).filter(UsedMagicToken.jti == _pending_jti(jti)).first()
    if used is not None:
        return None
    return user, jti


def _pending_jti(jti: str) -> str:
    return f"2fa:{jti}"[:64]


def consume_pending_login(db: Session, jti: str) -> bool:
    """Spend a pending sign-in. False if it was already spent."""
    db.add(UsedMagicToken(jti=_pending_jti(jti)))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    return True
