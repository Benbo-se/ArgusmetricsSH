"""
Authentication service for user signup, verification, and session management.

Handles the business logic for:
- User registration with magic link email verification
- Email verification and session creation
- Session validation and management
- User logout
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from itsdangerous import SignatureExpired, BadSignature

from app.models.user import User
from app.models.session import Session as SessionModel
from app.utils.security import (
    generate_magic_token,
    verify_magic_token,
    generate_session_token,
    validate_email,
    hash_token,
)
from app.services.email_service import email_service
from app.utils.password_rules import password_ok, failed_rules
from app.config import settings

logger = logging.getLogger(__name__)

# Compared against when no user matches at login, so unknown-email and
# wrong-password cost the same bcrypt time (anti timing-enumeration).
import bcrypt as _bcrypt
HASH_COST = 12
_DECOY_HASH = _bcrypt.hashpw(b"decoy-password-never-matches", _bcrypt.gensalt(rounds=HASH_COST))


def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt(rounds=HASH_COST)).decode("utf-8")


def _verify_password(password: str, password_hash: Optional[str]) -> bool:
    """Constant-cost verify: always runs bcrypt, against the decoy if needed."""
    target = password_hash.encode("utf-8") if password_hash else _DECOY_HASH
    try:
        matched = _bcrypt.checkpw(password.encode("utf-8"), target)
    except ValueError:
        return False
    return matched and password_hash is not None


def _hash_code(code: str) -> str:
    """HMAC-style hash for the 6-digit verification code (peppered)."""
    import hashlib
    return hashlib.sha256(f"{settings.SECRET_KEY}:{code}".encode("utf-8")).hexdigest()


def _generate_code() -> str:
    import secrets
    return f"{secrets.randbelow(1_000_000):06d}"


def _mask_email(email: Optional[str]) -> str:
    """Redact an email for logging, keeping only the domain (PII-safe)."""
    if not email or "@" not in email:
        return "<redacted>"
    return "<redacted>@" + email.split("@", 1)[1]


class AuthService:
    """
    Service for handling authentication operations.

    This service manages the complete authentication flow:
    1. User signs up with email
    2. Magic link is sent to email
    3. User clicks link to verify email
    4. Session is created for authenticated user
    5. Session is validated on subsequent requests

    Attributes:
        db: SQLAlchemy database session
    """

    def __init__(self, db: Session):
        """
        Initialize authentication service with database session.

        Args:
            db: SQLAlchemy database session for database operations
        """
        self.db = db
        logger.debug("AuthService initialized")

    @staticmethod
    def _e2e_secret_ok(presented_secret: Optional[str], email: str) -> bool:
        """
        True only when this is a legitimate E2E test call: a non-production env,
        a configured secret, the caller actually PRESENTS that secret, and a
        @test.argusmetrics.io address. Gating on config presence alone (the old
        behavior) let anyone trigger the bypass if the secret was ever set.
        """
        import secrets as _secrets
        if settings.is_production or not settings.E2E_TEST_SECRET:
            return False
        if not email.endswith("@test.argusmetrics.io"):
            return False
        if not presented_secret:
            return False
        return _secrets.compare_digest(presented_secret, settings.E2E_TEST_SECRET)

    def signup_user(self, email: str, password: Optional[str] = None, e2e_secret: Optional[str] = None) -> Dict[str, str]:
        """
        Register a new user and send verification email.

        Creates a new user account (or updates existing unverified account)
        and sends a magic link to the user's email for verification.

        Args:
            email: User's email address

        Returns:
            dict: Contains message and email
                {
                    "message": "Verification email sent...",
                    "email": "user@example.com"
                }

        Raises:
            ValueError: If email format is invalid
            Exception: If database operation fails

        Example:
            service = AuthService(db)
            result = service.signup_user("user@example.com")
            print(result["message"])
        """
        # Validate email format
        if not validate_email(email):
            logger.warning(f"Invalid email format attempted: {_mask_email(email)}")
            raise ValueError("Invalid email format")

        logger.info(f"Processing signup for email: {_mask_email(email)}")

        # Validate the password BEFORE looking the account up, so a shape
        # error is identical for existing and non-existing emails (no
        # enumeration oracle through validation branching).
        if not password:
            raise ValueError("Password is required")
        if not password_ok(password, email):
            raise ValueError(
                "Password does not meet the requirements: " + ", ".join(failed_rules(password, email))
            )

        try:
            # Check if user already exists
            existing_user = self.db.query(User).filter(User.email == email).first()

            if existing_user:
                if existing_user.is_verified:
                    # Existing verified account: NEVER mint a login link here
                    # (a login-capable URL for an arbitrary account, exposed in
                    # dev mode, is account takeover). Notify the address and
                    # return the same generic message as a fresh signup.
                    logger.info(f"Signup for already-registered account: {_mask_email(email)}")
                    if not self._e2e_secret_ok(e2e_secret, email):
                        email_service.send_email(
                            to=email,
                            subject=f"You already have a {settings.APP_NAME} account",
                            html_content=(
                                f"<p>Someone (probably you) tried to create a {settings.APP_NAME} "
                                f"account with this address, but it is already registered.</p>"
                                f"<p><a href=\"{settings.BASE_URL}/login\">Sign in</a> — or use "
                                f"\"Forgot password?\" on the login page if you can't get in.</p>"
                                f"<p>If this wasn't you, you can safely ignore this email.</p>"
                            ),
                            text_content=(
                                f"Someone (probably you) tried to create a {settings.APP_NAME} account "
                                f"with this address, but it is already registered.\n\n"
                                f"Sign in at {settings.BASE_URL}/login — or use \"Forgot password?\" "
                                f"if you can't get in.\n\nIf this wasn't you, ignore this email."
                            ),
                        )
                    return {
                        "message": "Verification email sent. Please check your inbox and click the link to verify your account.",
                        "email": email,
                    }
                else:
                    logger.info(f"User exists but not verified, resending verification: {_mask_email(email)}")
                    # Unverified account, someone signs up again: adopt the NEW
                    # password. The address owner proves ownership by clicking
                    # the link; keeping the ORIGINAL password would let whoever
                    # signed up first (possibly an attacker squatting the
                    # address) retain the credentials after the real owner
                    # verifies — a pre-registration account takeover.
                    existing_user.password_hash = _hash_password(password)
                    self.db.commit()
            else:
                # ENABLE_EMAIL_VERIFICATION off means an account is usable
                # immediately. That is the only way to sign in on an instance
                # with no email configured, which would otherwise create
                # accounts that can never be verified and never log in.
                #
                # Safe only because such an instance is closed: nobody but the
                # operator can reach signup. Turning registration on without
                # verification lets a stranger claim any address, so the two
                # settings are checked together below.
                verified_on_creation = not settings.ENABLE_EMAIL_VERIFICATION

                new_user = User(
                    email=email,
                    is_verified=verified_on_creation,
                    password_hash=_hash_password(password),
                )
                self.db.add(new_user)
                self.db.commit()
                self.db.refresh(new_user)
                logger.info(f"New user created: {_mask_email(email)}")

                if verified_on_creation:
                    logger.info(
                        "Email verification is disabled: account is usable now"
                    )
                    return {
                        "message": "Account created. You can sign in now.",
                        "email": email,
                        "verification_required": False,
                    }

            # Generate magic link token (expires in 15 minutes)
            magic_token = generate_magic_token(
                email=email,
                secret=settings.SECRET_KEY,
                expires_in=900  # 15 minutes
            )

            # Build verification URL
            # In production, this should be the frontend URL
            verify_url = f"{settings.BASE_URL}/verify?token={magic_token}"

            # 6-digit code: same completion as the link, typed on /verify.
            # Stored hashed with limited attempts; resend rotates it.
            code = self._set_pending_code(email)

            # E2E bypass requires a *presented* secret (non-prod only)
            is_e2e_test = self._e2e_secret_ok(e2e_secret, email)

            if not is_e2e_test:
                # Send verification email
                email_sent = email_service.send_verification_email(
                    to=email,
                    verify_url=verify_url,
                    code=code
                )

                if not email_sent:
                    logger.error(f"Failed to send verification email to: {_mask_email(email)}")

            logger.info(f"Signup successful for: {_mask_email(email)}")

            response = {
                "message": "Verification email sent. Please check your inbox and click the link to verify your account.",
                "email": email
            }
            # Fail closed: only expose the link in non-prod dev mode or to a
            # verified E2E caller. Never expose it just because email is unconfigured.
            if is_e2e_test or (settings.DEBUG and not settings.is_production):
                response["verify_url"] = verify_url
                if not is_e2e_test:
                    response["message"] = "⚠️ DEV MODE: email not sent — use the verification link below."
                logger.warning("DEV/E2E: returning verify_url in API response")

            return response

        except IntegrityError as e:
            self.db.rollback()
            logger.error(f"Database integrity error during signup for {_mask_email(email)}: {e}")
            # This shouldn't happen due to our check above, but handle it anyway
            raise ValueError("Email already registered")

        except Exception as e:
            self.db.rollback()
            logger.error(f"Unexpected error during signup for {_mask_email(email)}: {e}", exc_info=True)
            raise

    def verify_email(self, token: str) -> SessionModel:
        """
        Verify email using magic link token and create session.

        Validates the magic link token, marks the user as verified,
        and creates a new authenticated session.

        Args:
            token: Magic link token from verification email

        Returns:
            SessionModel: Newly created session for the verified user

        Raises:
            ValueError: If token is invalid or expired
            Exception: If database operation fails

        Example:
            service = AuthService(db)
            session = service.verify_email(token)
            print(f"Session created: {session.token}")
        """
        logger.info("Processing email verification")

        try:
            # Verify and decode the magic token
            payload = verify_magic_token(
                token=token,
                secret=settings.SECRET_KEY,
                max_age=settings.MAGIC_TOKEN_EXPIRY_SECONDS,
            )
            email = payload["email"]
            magic_jti = payload.get("jti")

            logger.info("Magic token verified")

        except SignatureExpired:
            logger.warning("Expired token used for verification")
            raise ValueError("Verification link has expired. Please request a new one.")

        except BadSignature:
            logger.warning("Invalid token signature for verification")
            raise ValueError("Invalid verification link. Please request a new one.")

        except Exception as e:
            logger.error(f"Error verifying token: {e}", exc_info=True)
            raise ValueError("Invalid verification link.")

        try:
            # Enforce single-use: redeem the token's jti atomically. The unique
            # constraint makes a concurrent/replayed redemption fail.
            if magic_jti:
                from app.models.used_magic_token import UsedMagicToken
                self.db.add(UsedMagicToken(jti=magic_jti))
                try:
                    self.db.commit()
                except IntegrityError:
                    self.db.rollback()
                    logger.warning("Magic token replay rejected")
                    raise ValueError("This link has already been used. Please request a new one.")

            # Find the user
            user = self.db.query(User).filter(User.email == email).first()

            if not user:
                logger.error(f"User not found for verified email: {_mask_email(email)}")
                raise ValueError("User not found. Please sign up again.")

            # Shared completion (same path as the 6-digit code)
            session = self._complete_verification(user)

            logger.info(f"Email verification complete for: {_mask_email(email)}")
            return session

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error during email verification for {_mask_email(email)}: {e}", exc_info=True)
            raise

    def _set_pending_code(self, email: str) -> str:
        """Mint (or rotate) the user's 6-digit verification code. Rotating also
        resets the attempt counter, so a locked-out user isn't stuck with a
        dead code until it expires."""
        code = _generate_code()
        user = self.db.query(User).filter(User.email == email).first()
        if user:
            user.pending_code_hash = _hash_code(code)
            user.pending_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
            user.pending_code_attempts = 0
            self.db.commit()
        return code

    def _complete_verification(self, user: User) -> SessionModel:
        """Shared completion for BOTH verification paths (magic link and
        6-digit code): mark verified, clear the pending code, welcome-mail
        first-time verifications, and sign the user in."""
        first_time = not user.is_verified
        user.is_verified = True
        user.pending_code_hash = None
        user.pending_code_expires_at = None
        user.pending_code_attempts = 0
        self.db.commit()

        if first_time:
            logger.info(f"User verified: {_mask_email(user.email)}")
            # Best-effort; never blocks the login
            email_service.send_welcome_email(user.email)

        return self.create_session(user)

    def verify_email_code(self, email: str, code: str) -> SessionModel:
        """
        Verify email using the 6-digit code (alternative to the magic link).

        Same generic error for unknown email, wrong code, expired code and
        too many attempts — no oracle. Max 5 attempts per code.
        """
        import hmac as _hmac
        generic = ValueError("Invalid or expired code. Please request a new one.")

        # Pre-check: exactly 6 ASCII digits (full-width digits from mobile
        # keyboards would otherwise blow up the comparison downstream).
        code = (code or "").strip()
        if len(code) != 6 or not code.isascii() or not code.isdigit():
            raise generic

        user = self.db.query(User).filter(User.email == email).first()
        if not user or not user.pending_code_hash or not user.pending_code_expires_at:
            raise generic

        now = datetime.now(timezone.utc)
        expires = user.pending_code_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now > expires:
            raise generic

        # Count the attempt BEFORE comparing (parallel guesses can't skip it)
        user.pending_code_attempts = (user.pending_code_attempts or 0) + 1
        self.db.commit()
        if user.pending_code_attempts > 5:
            logger.warning(f"Verification code attempt limit hit for {_mask_email(email)}")
            raise generic

        if not _hmac.compare_digest(_hash_code(code), user.pending_code_hash):
            raise generic

        return self._complete_verification(user)

    def login_user(self, email: str, password: str) -> SessionModel:
        """
        Password login. One generic error for every failure mode (unknown
        email, wrong password, unverified account) and a decoy bcrypt compare
        when the email is unknown, so failures are indistinguishable by
        response AND by timing.
        """
        generic = ValueError("Invalid email or password")

        user = self.db.query(User).filter(User.email == email).first()
        password_hash = user.password_hash if user else None

        if not _verify_password(password, password_hash):
            raise generic

        if not user.is_verified:
            # Don't leak that the account exists but is unverified; the resend
            # flow is the recovery path.
            logger.info(f"Login attempt on unverified account: {_mask_email(email)}")
            raise generic

        logger.info(f"Password login OK: {_mask_email(email)}")
        return self.create_session(user)

    def resend_verification(self, email: str) -> None:
        """Re-send the verification email. Always silent about whether the
        account exists; already-verified accounts get nothing."""
        user = self.db.query(User).filter(User.email == email).first()
        if not user or user.is_verified:
            return

        magic_token = generate_magic_token(email=email, secret=settings.SECRET_KEY, expires_in=900)
        verify_url = f"{settings.BASE_URL}/verify?token={magic_token}"
        code = self._set_pending_code(email)
        email_service.send_verification_email(to=email, verify_url=verify_url, code=code)

    def request_password_reset(self, email: str) -> Optional[str]:
        """Send a password-reset link (1h expiry). Silent for unknown emails.
        Returns the reset URL ONLY for dev-mode display (None otherwise)."""
        user = self.db.query(User).filter(User.email == email).first()
        if not user:
            return None

        reset_token = generate_magic_token(
            email=email, secret=settings.SECRET_KEY, expires_in=3600, purpose="reset"
        )
        reset_url = f"{settings.BASE_URL}/reset?token={reset_token}"
        email_service.send_password_reset_email(to=email, reset_url=reset_url)

        if settings.DEBUG and not settings.is_production:
            return reset_url
        return None

    def set_password_with_token(self, token: str, new_password: str) -> SessionModel:
        """
        Complete a password reset: validate the token (single-use, purpose
        'reset'), enforce the password rules, revoke EVERY existing session,
        and sign the user in fresh. Also marks the account verified — the
        emailed link proves address ownership.
        """
        try:
            payload = verify_magic_token(
                token=token, secret=settings.SECRET_KEY, max_age=3600, expected_purpose="reset"
            )
        except SignatureExpired:
            raise ValueError("This reset link has expired. Please request a new one.")
        except (BadSignature, Exception):
            raise ValueError("Invalid reset link. Please request a new one.")

        email = payload["email"]
        magic_jti = payload.get("jti")

        if not password_ok(new_password, email):
            raise ValueError(
                "Password does not meet the requirements: " + ", ".join(failed_rules(new_password, email))
            )

        # Single-use redemption
        if magic_jti:
            from app.models.used_magic_token import UsedMagicToken
            self.db.add(UsedMagicToken(jti=magic_jti))
            try:
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                raise ValueError("This link has already been used. Please request a new one.")

        user = self.db.query(User).filter(User.email == email).first()
        if not user:
            raise ValueError("Invalid reset link. Please request a new one.")

        user.password_hash = _hash_password(new_password)
        user.is_verified = True
        # Revoke everything: a reset means the old credentials can't be trusted
        self.db.query(SessionModel).filter(SessionModel.user_email == email).delete()
        self.db.commit()
        logger.info(f"Password reset completed for {_mask_email(email)}; all sessions revoked")

        return self.create_session(user)

    def create_session(self, user: User) -> SessionModel:
        """
        Create a new authentication session for a user.

        Generates a secure session token and stores it in the database
        with an expiration time based on settings.

        Args:
            user: User object to create session for

        Returns:
            SessionModel: Newly created session

        Raises:
            Exception: If database operation fails

        Example:
            service = AuthService(db)
            session = service.create_session(user)
            print(f"Session token: {session.token}")
            print(f"Expires at: {session.expires_at}")
        """
        logger.info(f"Creating session for user: {_mask_email(user.email)}")

        try:
            # Generate secure session token
            session_token = generate_session_token(length=32)

            # Calculate expiration time (default: 7 days from settings)
            expires_at = datetime.now(timezone.utc) + timedelta(days=settings.SESSION_EXPIRY_DAYS)

            # Store hashed token in DB (plaintext never persisted)
            session = SessionModel(
                token=hash_token(session_token),
                user_email=user.email,
                expires_at=expires_at
            )

            self.db.add(session)
            self.db.commit()
            self.db.refresh(session)

            # Attach raw token for cookie/response use (not persisted)
            session._raw_token = session_token

            logger.info(f"Session created for {_mask_email(user.email)}, expires at {expires_at}")

            return session

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creating session for {_mask_email(user.email)}: {e}", exc_info=True)
            raise

    def validate_session(self, token: str) -> Optional[User]:
        """
        Validate a session token and return the associated user.

        Checks if the session token exists, hasn't expired, and returns
        the associated user if valid.

        Args:
            token: Session token to validate

        Returns:
            User: User associated with the session, or None if invalid

        Example:
            service = AuthService(db)
            user = service.validate_session(token)
            if user:
                print(f"Valid session for: {user.email}")
            else:
                print("Invalid or expired session")
        """
        logger.debug("Validating session token")

        try:
            # Query session (hash the incoming token to match stored hash)
            session = self.db.query(SessionModel).filter(
                SessionModel.token == hash_token(token)
            ).first()

            if not session:
                logger.debug("Session not found")
                return None

            # Check if session has expired
            now = datetime.now(timezone.utc)
            if session.expires_at < now:
                logger.info(f"Session expired for user: {_mask_email(session.user_email)}")
                # Delete expired session
                self.db.delete(session)
                self.db.commit()
                return None

            # Get associated user
            user = self.db.query(User).filter(
                User.email == session.user_email
            ).first()

            if not user:
                logger.error(f"User not found for session: {_mask_email(session.user_email)}")
                return None

            if not user.is_verified:
                logger.warning(f"Unverified user attempting to use session: {_mask_email(user.email)}")
                return None

            logger.debug(f"Valid session for user: {_mask_email(user.email)}")
            return user

        except Exception as e:
            logger.error(f"Error validating session: {e}", exc_info=True)
            return None

    def logout_user(self, token: str) -> bool:
        """
        Log out a user by deleting their session.

        Args:
            token: Session token to invalidate

        Returns:
            bool: True if session was deleted, False if not found

        Example:
            service = AuthService(db)
            success = service.logout_user(token)
            if success:
                print("Logged out successfully")
        """
        logger.info("Processing logout request")

        try:
            # Find and delete the session (hash the incoming token to match stored hash)
            session = self.db.query(SessionModel).filter(
                SessionModel.token == hash_token(token)
            ).first()

            if not session:
                logger.debug("Session not found for logout")
                return False

            user_email = session.user_email
            self.db.delete(session)
            self.db.commit()

            logger.info(f"User logged out: {_mask_email(user_email)}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error during logout: {e}", exc_info=True)
            return False

    def get_user_sessions(self, user_email: str) -> list[SessionModel]:
        """
        Get all active sessions for a user.

        Args:
            user_email: User's email address

        Returns:
            list: List of active sessions

        Example:
            service = AuthService(db)
            sessions = service.get_user_sessions("user@example.com")
            print(f"User has {len(sessions)} active sessions")
        """
        try:
            sessions = self.db.query(SessionModel).filter(
                SessionModel.user_email == user_email,
                SessionModel.expires_at > datetime.now(timezone.utc)
            ).all()

            logger.debug(f"Found {len(sessions)} active sessions for {_mask_email(user_email)}")
            return sessions

        except Exception as e:
            logger.error(f"Error getting user sessions: {e}", exc_info=True)
            return []

    def cleanup_expired_sessions(self) -> int:
        """
        Delete all expired sessions from the database.

        This should be called periodically (e.g., via a cron job or background task)
        to keep the database clean.

        Returns:
            int: Number of sessions deleted

        Example:
            service = AuthService(db)
            deleted = service.cleanup_expired_sessions()
            print(f"Cleaned up {deleted} expired sessions")
        """
        try:
            result = self.db.query(SessionModel).filter(
                SessionModel.expires_at < datetime.now(timezone.utc)
            ).delete()

            self.db.commit()
            logger.info(f"Cleaned up {result} expired sessions")
            return result

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error cleaning up expired sessions: {e}", exc_info=True)
            return 0
