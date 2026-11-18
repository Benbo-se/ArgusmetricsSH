"""
Email service for sending transactional emails.

Supports generic SMTP (any provider), the legacy Lettermint HTTP API, and a stub mode for development.
"""
import logging
import httpx
from html import escape
from typing import Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.email_log import EmailLog
from app.services import email_layout

logger = logging.getLogger(__name__)


class EmailService:
    """
    Service for sending transactional emails.

    Supports, in priority order:
    - Generic SMTP (any provider - Lettermint, Postmark, your own relay ...)
    - Lettermint HTTP API (legacy path, kept for existing installs)
    - Stub mode (development/testing, logs verification links to console)
    """

    def __init__(self):
        """Initialize email service with configuration from settings."""
        self.email_backend = settings.EMAIL_BACKEND

        # Generic SMTP configuration (preferred: works with any provider)
        self.smtp_configured = bool(settings.SMTP_HOST)

        # Lettermint configuration (legacy HTTP API path)
        self.lettermint_api_key = settings.LETTERMINT_API_KEY
        self.lettermint_api_url = settings.LETTERMINT_API_URL
        self.lettermint_from_email = settings.LETTERMINT_FROM_EMAIL
        self.lettermint_from_name = settings.LETTERMINT_FROM_NAME
        self.lettermint_configured = (
            self.email_backend == "lettermint"
            and self.lettermint_api_key
            and self.lettermint_api_key != "changeme"
        )

        # One flag the rest of the app checks: can we actually deliver mail?
        self.configured = self.smtp_configured or self.lettermint_configured

        if self.smtp_configured:
            logger.info(f"EmailService initialized with SMTP ({settings.SMTP_HOST}:{settings.SMTP_PORT})")
        elif self.lettermint_configured:
            logger.info("EmailService initialized with Lettermint HTTP API")
        else:
            logger.info("EmailService initialized in STUB mode - configure SMTP_HOST to send real emails")

    def _log_email(self, to: str, email_type: str, subject: str, success: bool, error_message: Optional[str] = None):
        """
        Log sent email to database for audit trail.

        Args:
            to: Recipient email address
            email_type: Type of email (verification, welcome, password_reset, team_invitation, generic)
            subject: Email subject
            success: Whether email was sent successfully
            error_message: Error message if failed
        """
        db = SessionLocal()
        try:
            email_log = EmailLog(
                to_email=to,
                email_type=email_type,
                subject=subject,
                success=success,
                error_message=error_message
            )
            db.add(email_log)
            db.commit()
        except Exception as e:
            # close() must run even when commit raises, or the connection is
            # leaked back to nobody and repeated failures exhaust the pool.
            logger.error(f"Failed to log email to database: {e}")
        finally:
            db.close()

    def _send_via_lettermint(self, to: str, subject: str, text: str, html: str) -> bool:
        """
        Send email via Lettermint HTTP API.

        Args:
            to: Recipient email address
            subject: Email subject
            text: Plain text content
            html: HTML content

        Returns:
            bool: True if email was sent successfully
        """
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    self.lettermint_api_url,
                    headers={
                        "Content-Type": "application/json",
                        "x-lettermint-token": self.lettermint_api_key,
                        "Accept": "application/json"
                    },
                    json={
                        "from": f"{self.lettermint_from_name} <{self.lettermint_from_email}>",
                        "to": [to],
                        "subject": subject,
                        "text": text,
                        "html": html
                    }
                )

            if response.status_code in [200, 201, 202]:
                logger.info(f"Email sent successfully via Lettermint to {to}")
                return True
            else:
                logger.error(f"Lettermint API error: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Failed to send email via Lettermint: {e}")
            return False

    def _send_via_smtp(self, to: str, subject: str, text: str, html: str) -> bool:
        """
        Send a multipart (text + HTML) email over plain SMTP.

        Multipart matters: HTML-only mail scores worse with strict providers,
        and the text part is the accessible fallback.
        """
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.utils import formataddr

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))
            msg["To"] = to
            msg.attach(MIMEText(text, "plain", "utf-8"))
            msg.attach(MIMEText(html, "html", "utf-8"))

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
                if settings.SMTP_USE_TLS:
                    smtp.starttls()
                if settings.SMTP_USER and settings.SMTP_PASSWORD:
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                smtp.sendmail(settings.SMTP_FROM_EMAIL, [to], msg.as_string())

            logger.info(f"Email sent successfully via SMTP to {to}")
            return True

        except Exception as e:
            # Log BEFORE returning: callers treat mail as best-effort and a
            # silent False here is how delivery regressions go unnoticed.
            logger.error(f"Failed to send email via SMTP ({settings.SMTP_HOST}): {e}")
            return False

    def _deliver(self, to: str, subject: str, text: str, html: str) -> bool:
        """Single delivery chokepoint: SMTP first, Lettermint API as legacy fallback."""
        if self.smtp_configured:
            return self._send_via_smtp(to, subject, text, html)
        if self.lettermint_configured:
            return self._send_via_lettermint(to, subject, text, html)
        logger.warning(f"Email NOT sent (no backend configured): '{subject}' to {to}")
        return False

    def send_verification_email(self, to: str, verify_url: str, code: Optional[str] = None) -> bool:
        """
        Send email verification: a magic link AND (when provided) a 6-digit
        code that can be typed on the /verify page — for mail clients where
        links are awkward (corporate scanners, another device, etc).

        Args:
            to: Recipient email address
            verify_url: Full URL for verification (includes magic token)
            code: Optional 6-digit verification code

        Returns:
            bool: True if email was sent successfully
        """
        logger.info("=" * 80)
        logger.info("SENDING VERIFICATION EMAIL")
        logger.info("=" * 80)
        logger.info(f"To: {to}")
        logger.info(f"Subject: Verify your email for {settings.APP_NAME}")

        code_text = f"\nOr enter this code on the verification page: {code}\n" if code else ""
        # Plain text version
        text = f"""Welcome to {settings.APP_NAME}!

Please click the link below to verify your email address:

{verify_url}
{code_text}
This link will expire in 15 minutes.

If you didn't request this, you can safely ignore this email.

Thanks,
The {settings.APP_NAME} Team
"""

        # HTML version
        html = email_layout.render(
            eyebrow="Confirm your address",
            heading_html=f"One click, and {email_layout.aside('you are in')}.",
            preheader="Confirm your address to finish creating your account.",
            body=[
                email_layout.text(f"Someone asked for a {escape(settings.APP_NAME)} account with this address. "
                                  "If that was you, confirm it here."),
                email_layout.button("Confirm my address", verify_url),
                *([email_layout.text("Reading this on another device? Type this code on the verification page instead."),
                   email_layout.code(code)] if code else []),
                email_layout.text("The link and the code work for 15 minutes. If you did not ask for this, "
                                  "ignore it and no account is created.", small=True),
            ],
            reason="You are getting this because this address was entered on the sign-up page.",
        )

        subject = f"Verify your email for {settings.APP_NAME}"

        # If no email backend configured, use stub mode
        if not self.configured:
            logger.warning("NO EMAIL BACKEND CONFIGURED - Using stub mode")
            logger.info("-" * 80)
            logger.info("VERIFICATION LINK (copy this to browser):")
            logger.info(f"{verify_url}")
            if code:
                logger.info(f"VERIFICATION CODE: {code}")
            logger.info("=" * 80)
            self._log_email(to, "verification", subject, True)
            return True

        # Try Lettermint
        success = self._deliver(to, subject, text, html)
        if success:
            logger.info("=" * 80)
            self._log_email(to, "verification", subject, True)
            return True

        # Lettermint failed
        # As for invitations: with mail configured, a link that could not be
        # sent is not put in the log instead.
        logger.error("Failed to send verification email")
        logger.info("=" * 80)
        self._log_email(to, "verification", subject, False, "Lettermint send failed")
        return False

    def send_welcome_email(self, to: str) -> bool:
        """
        Send welcome email after successful verification.

        Args:
            to: Recipient email address

        Returns:
            bool: True if email was sent successfully
        """
        subject = f"Welcome to {settings.APP_NAME}!"

        if not self.configured:
            logger.info(f"STUB MODE: Welcome email would be sent to {to}")
            self._log_email(to, "welcome", subject, True)
            return True

        text = f"""Welcome to {settings.APP_NAME}!

Your email has been verified successfully.

You can now access your dashboard at: {settings.BASE_URL}

Thanks,
The {settings.APP_NAME} Team
"""

        html = email_layout.render(
            eyebrow="Welcome",
            heading_html=f"Your address is confirmed. {email_layout.aside('Now the first visit.')}",
            preheader="Your account is ready. Add a website to see its first visit.",
            body=[
                email_layout.text("Add a website, paste one line into its pages, and the first visit shows up "
                                  "within seconds. No cookies are set and no banner is needed."),
                email_layout.button("Open my dashboard", settings.BASE_URL),
            ],
            reason="You are getting this because you just created an account.",
        )

        # Try Lettermint
        if self._deliver(to, subject, text, html):
            self._log_email(to, "welcome", subject, True)
            return True

        # Lettermint failed
        logger.error(f"Failed to send welcome email to {to}")
        self._log_email(to, "welcome", subject, False, "Lettermint send failed")
        return False

    def send_password_reset_email(self, to: str, reset_url: str) -> bool:
        """
        Send password reset email.

        Args:
            to: Recipient email address
            reset_url: Full URL for password reset (includes token)

        Returns:
            bool: True if email was sent successfully
        """
        if not self.configured:
            logger.info(f"STUB MODE: Password reset email - Link: {reset_url}")
            return True

        text = f"""You requested to reset your password.

Click the link below to reset your password:

{reset_url}

This link will expire in 15 minutes.

If you didn't request this, you can safely ignore this email.

Thanks,
The {settings.APP_NAME} Team
"""

        html = email_layout.render(
            eyebrow="Password",
            heading_html=f"Choose a {email_layout.aside('new password')}.",
            preheader="A link to choose a new password. It works for 15 minutes.",
            body=[
                email_layout.text("Someone asked to reset the password for this account. If that was you, "
                                  "choose a new one here."),
                email_layout.button("Choose a new password", reset_url),
                email_layout.text("The link works once and for 15 minutes. If you did not ask for this, ignore it "
                                  "and your password stays as it is.", small=True),
            ],
            reason="You are getting this because a password reset was requested for this address.",
        )

        # Try Lettermint
        if self._deliver(to, f"Reset your {settings.APP_NAME} password", text, html):
            return True

        # Lettermint failed
        logger.error(f"Failed to send password reset email to {to}")
        return False

    def send_account_invitation(self, to: str, invited_by: str, join_url: str, days: int) -> bool:
        """An invitation to an account of one's own (services/account_invites.py).

        Neither the address nor the link is logged. The link creates an
        account, so in a log it would be a working credential.
        """
        subject = f"You're invited to {settings.APP_NAME}"
        if not self.configured:
            logger.warning("No email backend configured: the account invitation was not sent")
            self._log_email(to, "account_invitation", subject, False, "no email backend")
            return False

        text = f"""{invited_by} has invited you to {settings.APP_NAME}, cookieless web analytics.

Choose a password here and add your own website:

{join_url}

The link works once and for {days} days. If you did not expect this, ignore it
and nothing happens.

{settings.APP_NAME}
"""
        html = email_layout.render(
            eyebrow="Invitation",
            heading_html=f"An account of {email_layout.aside('your own')}.",
            preheader=f"{invited_by} has invited you to {settings.APP_NAME}.",
            body=[
                email_layout.text(f"{email_layout.strong(invited_by)} has invited you to {escape(settings.APP_NAME)}, "
                                  "web analytics that counts visits without cookies and without following anyone "
                                  "around. Choose a password and add your own website."),
                email_layout.button("Create my account", join_url),
                email_layout.text(f"The link works once and for {escape(str(days))} days. If you did not expect this, "
                                  "ignore it and nothing happens.", small=True),
            ],
            reason="You are getting this because someone with an account entered your address.",
        )
        success = self._deliver(to, subject, text, html)
        self._log_email(to, "account_invitation", subject, success,
                        None if success else "delivery failed")
        if not success:
            logger.error("Failed to send an account invitation")
        return success

    def send_team_invitation(self, to: str, website_name: str, website_domain: str, role: str, invited_by: str, invite_url: str) -> bool:
        """
        Send team invitation email.

        Args:
            to: Recipient email address
            website_name: Name of website they're being invited to
            website_domain: Domain of website
            role: Role being offered (admin, viewer)
            invited_by: Email of person who sent invite
            invite_url: Full URL for accepting invitation (includes token)

        Returns:
            bool: True if email was sent successfully
        """
        subject = f"You've been invited to join {website_name}"

        logger.info("=" * 80)
        logger.info("SENDING TEAM INVITATION EMAIL")
        logger.info("=" * 80)
        logger.info(f"To: {to}")
        logger.info(f"Subject: {subject}")

        if not self.configured:
            logger.warning("NO EMAIL BACKEND CONFIGURED - Using stub mode")
            logger.info("-" * 80)
            logger.info("INVITATION LINK (copy this to browser):")
            logger.info(f"{invite_url}")
            logger.info("=" * 80)
            self._log_email(to, "team_invitation", subject, True)
            return True

        # Plain text version
        text = f"""You've been invited to join {website_name}!

{invited_by} has invited you to collaborate on {website_name} ({website_domain}) with {role} access.

Click the link below to accept this invitation:

{invite_url}

This invitation will expire in 7 days.

As a {role}, you will be able to:
"""

        if role == 'admin':
            text += """- View all analytics data
- Configure website settings
- Manage conversion goals
- Invite other team members (as viewers)"""
        else:  # viewer
            text += """- View all analytics data
- Access the dashboard
- See reports and statistics"""

        text += f"""

If you didn't expect this invitation, you can safely ignore this email.

Thanks,
The {settings.APP_NAME} Team
"""

        role_summary = (
            "You can read every report, change the website's settings and goals, and invite others as viewers."
            if role == 'admin' else
            "You can read every report and the live dashboard. Nothing you do there changes anything."
        )

        html = email_layout.render(
            eyebrow="Invitation",
            heading_html=f"Come and see how {email_layout.aside(website_name)} is doing.",
            preheader=f"{invited_by} has invited you to the statistics for {website_name}.",
            body=[
                email_layout.text(f"{email_layout.strong(invited_by)} has opened the visitor statistics for this "
                                  f"website to you on {escape(settings.APP_NAME)}."),
                email_layout.ledger([
                    ("Website", f"{email_layout.strong(website_name)}<br>"
                                f"<span style=\"color:{email_layout.INK_FAINT};font-size:13px;\">"
                                f"{escape(str(website_domain))}</span>"),
                    ("Your role", f"{email_layout.strong(str(role).capitalize())}<br>"
                                  f"<span style=\"color:{email_layout.INK_DIM};font-size:14px;\">"
                                  f"{escape(role_summary)}</span>"),
                    ("Invited by", escape(str(invited_by))),
                ]),
                email_layout.button("Accept the invitation", invite_url),
                email_layout.text("The invitation is good for 7 days. If you did not expect it, ignore this mail "
                                  "and nothing happens.", small=True),
            ],
            reason="You are getting this because someone invited this address to a website.",
        )

        # Try Lettermint
        success = self._deliver(to, subject, text, html)
        if success:
            logger.info("=" * 80)
            self._log_email(to, "team_invitation", subject, True)
            return True

        # Lettermint failed
        # The link is not written to the log here. With mail configured the
        # log is not where an invitation travels, and the link is the whole
        # credential.
        logger.error("Failed to send team invitation email")
        logger.info("=" * 80)
        self._log_email(to, "team_invitation", subject, False, "Lettermint send failed")
        return False

    def send_email(self, to: str, subject: str, html_content: str, text_content: Optional[str] = None) -> bool:
        """
        Send a generic HTML email.

        Args:
            to: Recipient email address
            subject: Email subject
            html_content: HTML content of email
            text_content: Optional plain text version (auto-generated if not provided)

        Returns:
            bool: True if email was sent successfully
        """
        logger.info("=" * 80)
        logger.info(f"SENDING EMAIL: {subject}")
        logger.info("=" * 80)
        logger.info(f"To: {to}")

        # If no email backend configured, use stub mode
        if not self.configured:
            logger.warning("NO EMAIL BACKEND CONFIGURED - Using stub mode")
            logger.info("-" * 80)
            logger.info("EMAIL CONTENT (first 500 chars):")
            logger.info(html_content[:500] + "..." if len(html_content) > 500 else html_content)
            logger.info("=" * 80)
            self._log_email(to, "generic", subject, True)
            return True

        # Auto-generate plain text if not provided (strip HTML tags)
        if not text_content:
            import re
            text_content = re.sub('<[^<]+?>', '', html_content)

        # Try Lettermint
        success = self._deliver(to, subject, text_content, html_content)
        if success:
            logger.info("=" * 80)
            self._log_email(to, "generic", subject, True)
            return True

        # Lettermint failed
        logger.error(f"Failed to send email to {to}")
        logger.info("=" * 80)
        self._log_email(to, "generic", subject, False, "Lettermint send failed")
        return False


# Global email service instance
email_service = EmailService()
