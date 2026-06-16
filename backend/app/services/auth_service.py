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
from app.config import settings

logger = logging.getLogger(__name__)


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

    def signup_user(self, email: str, plan: str = 'free', e2e_secret: Optional[str] = None) -> Dict[str, str]:
        """
        Register a new user and send verification email.

        Creates a new user account (or updates existing unverified account)
        and sends a magic link to the user's email for verification.

        Args:
            email: User's email address
            plan: Subscription plan (free, starter, pro, business). Defaults to 'free'.

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
            result = service.signup_user("user@example.com", plan="starter")
            print(result["message"])
        """
        # Validate email format
        if not validate_email(email):
            logger.warning(f"Invalid email format attempted: {_mask_email(email)}")
            raise ValueError("Invalid email format")

        logger.info(f"Processing signup for email: {_mask_email(email)}")

        try:
            # Check if user already exists
            existing_user = self.db.query(User).filter(User.email == email).first()

            if existing_user:
                if existing_user.is_verified:
                    logger.info(f"User already verified: {_mask_email(email)}, sending login magic link")
                    # User is already verified, send login magic link instead
                    # Generate magic link token (expires in 15 minutes)
                    magic_token = generate_magic_token(
                        email=email,
                        secret=settings.SECRET_KEY,
                        expires_in=900  # 15 minutes
                    )

                    # Build verification URL (same endpoint, will create session)
                    verify_url = f"{settings.BASE_URL}/verify?token={magic_token}"

                    # E2E bypass requires a *presented* secret (non-prod only)
                    is_e2e_test = self._e2e_secret_ok(e2e_secret, email)

                    if not is_e2e_test:
                        # Send login email (reuse verification email for now)
                        email_sent = email_service.send_verification_email(
                            to=email,
                            verify_url=verify_url
                        )

                        if not email_sent:
                            logger.error(f"Failed to send login email to: {_mask_email(email)}")

                    logger.info(f"Login magic link sent to: {_mask_email(email)}")

                    # Return success message (don't reveal if user exists for security)
                    response = {
                        "message": "If this email is registered, you will receive a login link.",
                        "email": email
                    }
                    # Fail closed: only expose the link in non-prod dev mode or to a
                    # verified E2E caller. Never expose it just because email is unconfigured.
                    if is_e2e_test or (settings.DEBUG and not settings.is_production):
                        response["verify_url"] = verify_url
                        if not is_e2e_test:
                            response["message"] = "⚠️ DEV MODE: email not sent — use the login link below."
                        logger.warning("DEV/E2E: returning verify_url in API response")

                    return response
                else:
                    logger.info(f"User exists but not verified, resending verification: {_mask_email(email)}")
                    # User exists but not verified, resend verification email
            else:
                # Create new user with trial and billing fields
                from datetime import datetime, timedelta, timezone

                def get_next_month_start():
                    now = datetime.now(timezone.utc)
                    if now.month == 12:
                        return datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
                    else:
                        return datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)

                # Determine trial and quota based on plan
                if plan in ['starter', 'pro', 'business']:
                    # Paid plans get 14-day trial
                    trial_expires = datetime.now(timezone.utc) + timedelta(days=14)
                    subscription_status = 'trial'
                    # AI quotas per plan (FREE TIER = ZERO AI)
                    ai_quota_map = {
                        'starter': 50,
                        'pro': 1000,
                        'business': 10000
                    }
                    ai_quota = ai_quota_map[plan]
                else:
                    # Free plan = no trial, active immediately
                    trial_expires = None
                    subscription_status = 'active'
                    ai_quota = 0  # FREE = NO AI

                new_user = User(
                    email=email,
                    is_verified=False,
                    trial_expires=trial_expires,
                    plan=plan,
                    subscription_status=subscription_status,
                    monthly_pageviews_used=0,
                    monthly_reset_date=get_next_month_start(),
                    # AI quota fields
                    ai_chatbot_quota=ai_quota,
                    ai_chatbot_used_this_month=0,
                    ai_quota_reset_date=get_next_month_start()
                )
                self.db.add(new_user)
                self.db.commit()
                self.db.refresh(new_user)
                logger.info(f"New user created on {plan.upper()} plan: {_mask_email(email)}, status: {subscription_status}, trial_expires: {trial_expires}, AI quota: {ai_quota}")

            # Generate magic link token (expires in 15 minutes)
            magic_token = generate_magic_token(
                email=email,
                secret=settings.SECRET_KEY,
                expires_in=900  # 15 minutes
            )

            # Build verification URL
            # In production, this should be the frontend URL
            verify_url = f"{settings.BASE_URL}/verify?token={magic_token}"

            # E2E bypass requires a *presented* secret (non-prod only)
            is_e2e_test = self._e2e_secret_ok(e2e_secret, email)

            if not is_e2e_test:
                # Send verification email
                email_sent = email_service.send_verification_email(
                    to=email,
                    verify_url=verify_url
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

            # Mark user as verified
            if not user.is_verified:
                user.is_verified = True
                self.db.commit()
                logger.info(f"User verified: {_mask_email(email)}")

                # Send welcome email
                email_service.send_welcome_email(email)
            else:
                logger.info(f"User already verified: {_mask_email(email)}")

            # Create session for the user
            session = self.create_session(user)

            logger.info(f"Email verification complete for: {_mask_email(email)}")
            return session

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error during email verification for {_mask_email(email)}: {e}", exc_info=True)
            raise

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
