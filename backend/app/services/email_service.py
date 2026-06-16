"""
Email service for sending transactional emails.

Supports Lettermint HTTP API (EU-based, GDPR-compliant) and stub mode for development.
"""
import logging
import httpx
from typing import Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.email_log import EmailLog

logger = logging.getLogger(__name__)


class EmailService:
    """
    Service for sending transactional emails.

    Supports:
    - Lettermint HTTP API (EU-based, GDPR-compliant)
    - Stub mode (development/testing, logs verification links to console)
    """

    def __init__(self):
        """Initialize email service with configuration from settings."""
        self.email_backend = settings.EMAIL_BACKEND

        # Lettermint configuration
        self.lettermint_api_key = settings.LETTERMINT_API_KEY
        self.lettermint_api_url = settings.LETTERMINT_API_URL
        self.lettermint_from_email = settings.LETTERMINT_FROM_EMAIL
        self.lettermint_from_name = settings.LETTERMINT_FROM_NAME

        # Check if Lettermint is configured
        self.lettermint_configured = (
            self.email_backend == "lettermint"
            and self.lettermint_api_key
            and self.lettermint_api_key != "changeme"
        )

        if self.lettermint_configured:
            logger.info(f"EmailService initialized with Lettermint HTTP API - EU-based, GDPR-compliant")
        else:
            logger.info(f"EmailService initialized in STUB mode - configure Lettermint to send real emails")

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
        try:
            db = SessionLocal()
            email_log = EmailLog(
                to_email=to,
                email_type=email_type,
                subject=subject,
                success=success,
                error_message=error_message
            )
            db.add(email_log)
            db.commit()
            db.close()
        except Exception as e:
            logger.error(f"Failed to log email to database: {e}")

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

    def send_verification_email(self, to: str, verify_url: str) -> bool:
        """
        Send email verification magic link.

        Args:
            to: Recipient email address
            verify_url: Full URL for verification (includes magic token)

        Returns:
            bool: True if email was sent successfully
        """
        logger.info("=" * 80)
        logger.info("SENDING VERIFICATION EMAIL")
        logger.info("=" * 80)
        logger.info(f"To: {to}")
        logger.info(f"Subject: Verify your email for {settings.APP_NAME}")

        # Plain text version
        text = f"""Welcome to {settings.APP_NAME}!

Please click the link below to verify your email address:

{verify_url}

This link will expire in 15 minutes.

If you didn't request this, you can safely ignore this email.

Thanks,
The {settings.APP_NAME} Team
"""

        # HTML version
        html = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .button {{ display: inline-block; padding: 12px 24px; background-color: #007bff; color: white; text-decoration: none; border-radius: 4px; }}
        .footer {{ margin-top: 20px; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <h2>Welcome to {settings.APP_NAME}!</h2>
        <p>Please click the button below to verify your email address:</p>
        <p><a href="{verify_url}" class="button">Verify Email</a></p>
        <p>Or copy and paste this link into your browser:</p>
        <p><a href="{verify_url}">{verify_url}</a></p>
        <p class="footer">This link will expire in 15 minutes. If you didn't request this, you can safely ignore this email.</p>
        <p class="footer">Thanks,<br>The {settings.APP_NAME} Team</p>
    </div>
</body>
</html>
"""

        subject = f"Verify your email for {settings.APP_NAME}"

        # If no email backend configured, use stub mode
        if not self.lettermint_configured:
            logger.warning("NO EMAIL BACKEND CONFIGURED - Using stub mode")
            logger.info("-" * 80)
            logger.info("VERIFICATION LINK (copy this to browser):")
            logger.info(f"{verify_url}")
            logger.info("=" * 80)
            self._log_email(to, "verification", subject, True)
            return True

        # Try Lettermint
        success = self._send_via_lettermint(to, subject, text, html)
        if success:
            logger.info("=" * 80)
            self._log_email(to, "verification", subject, True)
            return True

        # Lettermint failed
        logger.error(f"Failed to send verification email to {to}")
        logger.info("FALLBACK - VERIFICATION LINK (copy this to browser):")
        logger.info(f"{verify_url}")
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

        if not self.lettermint_configured:
            logger.info(f"STUB MODE: Welcome email would be sent to {to}")
            self._log_email(to, "welcome", subject, True)
            return True

        text = f"""Welcome to {settings.APP_NAME}!

Your email has been verified successfully.

You can now access your dashboard at: {settings.BASE_URL}

Thanks,
The {settings.APP_NAME} Team
"""

        html = f"""<!DOCTYPE html>
<html>
<body>
    <h2>Welcome to {settings.APP_NAME}!</h2>
    <p>Your email has been verified successfully.</p>
    <p>You can now access your dashboard at: <a href="{settings.BASE_URL}">{settings.BASE_URL}</a></p>
    <p>Thanks,<br>The {settings.APP_NAME} Team</p>
</body>
</html>
"""

        # Try Lettermint
        if self._send_via_lettermint(to, subject, text, html):
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
        if not self.lettermint_configured:
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

        html = f"""<!DOCTYPE html>
<html>
<body>
    <h2>Password Reset Request</h2>
    <p>You requested to reset your password.</p>
    <p><a href="{reset_url}">Click here to reset your password</a></p>
    <p>This link will expire in 15 minutes.</p>
    <p>If you didn't request this, you can safely ignore this email.</p>
    <p>Thanks,<br>The {settings.APP_NAME} Team</p>
</body>
</html>
"""

        # Try Lettermint
        if self._send_via_lettermint(to, f"Reset your {settings.APP_NAME} password", text, html):
            return True

        # Lettermint failed
        logger.error(f"Failed to send password reset email to {to}")
        return False

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

        if not self.lettermint_configured:
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

        # HTML version
        role_permissions = ""
        if role == 'admin':
            role_permissions = """
            <ul>
                <li>View all analytics data</li>
                <li>Configure website settings</li>
                <li>Manage conversion goals</li>
                <li>Invite other team members (as viewers)</li>
            </ul>
            """
        else:  # viewer
            role_permissions = """
            <ul>
                <li>View all analytics data</li>
                <li>Access the dashboard</li>
                <li>See reports and statistics</li>
            </ul>
            """

        html = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 8px 8px 0 0; text-align: center; }}
        .content {{ background: #ffffff; padding: 30px; border: 1px solid #e5e7eb; border-top: none; }}
        .button {{ display: inline-block; padding: 14px 28px; background-color: #667eea; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; margin: 20px 0; }}
        .button:hover {{ background-color: #5568d3; }}
        .role-badge {{ display: inline-block; padding: 4px 12px; background-color: #f3f4f6; color: #374151; border-radius: 12px; font-size: 14px; font-weight: 600; text-transform: uppercase; }}
        .website-info {{ background: #f9fafb; padding: 15px; border-left: 4px solid #667eea; margin: 20px 0; border-radius: 4px; }}
        .permissions {{ background: #f0fdf4; padding: 15px; border-radius: 6px; margin: 20px 0; }}
        .permissions h3 {{ margin-top: 0; color: #166534; }}
        .permissions ul {{ margin: 10px 0; padding-left: 20px; }}
        .footer {{ margin-top: 20px; padding-top: 20px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0; font-size: 28px;">Team Invitation</h1>
            <p style="margin: 10px 0 0 0; opacity: 0.9;">You've been invited to collaborate!</p>
        </div>
        <div class="content">
            <p><strong>{invited_by}</strong> has invited you to join their team on <strong>{settings.APP_NAME}</strong>.</p>

            <div class="website-info">
                <h3 style="margin: 0 0 10px 0; font-size: 18px;">{website_name}</h3>
                <p style="margin: 0; color: #6b7280; font-size: 14px;">{website_domain}</p>
                <p style="margin: 10px 0 0 0;">Your role: <span class="role-badge">{role}</span></p>
            </div>

            <div class="permissions">
                <h3 style="font-size: 16px;">What you can do as a {role}:</h3>
                {role_permissions}
            </div>

            <center>
                <a href="{invite_url}" class="button">Accept Invitation</a>
            </center>

            <p style="font-size: 14px; color: #6b7280;">Or copy and paste this link into your browser:</p>
            <p style="word-break: break-all; font-size: 12px; color: #9ca3af;"><a href="{invite_url}" style="color: #667eea;">{invite_url}</a></p>

            <div class="footer">
                <p>This invitation will expire in 7 days.</p>
                <p>If you didn't expect this invitation, you can safely ignore this email.</p>
                <p>Thanks,<br>The {settings.APP_NAME} Team</p>
            </div>
        </div>
    </div>
</body>
</html>
"""

        # Try Lettermint
        success = self._send_via_lettermint(to, subject, text, html)
        if success:
            logger.info("=" * 80)
            self._log_email(to, "team_invitation", subject, True)
            return True

        # Lettermint failed
        logger.error(f"Failed to send team invitation email to {to}")
        logger.info("FALLBACK - INVITATION LINK (copy this to browser):")
        logger.info(f"{invite_url}")
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
        if not self.lettermint_configured:
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
        success = self._send_via_lettermint(to, subject, text_content, html_content)
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
