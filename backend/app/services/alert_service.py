"""
Alert service for detecting and sending traffic spike alerts.

Monitors traffic patterns and sends alerts when unusual activity is detected.
"""
import logging
from html import escape
from typing import Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.pageview import Pageview
from app.models.website import Website
from app.models.alert_settings import AlertSettings
from app.services.email_service import email_service

logger = logging.getLogger(__name__)


class AlertService:
    """
    Service for traffic spike detection and alerting.

    Monitors:
    - Traffic spikes (current vs typical)
    - Sends email alerts when thresholds exceeded
    """

    def __init__(self, db: Session):
        """
        Initialize alert service with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        logger.debug("AlertService initialized")

    def check_traffic_spike(self, website_id: int) -> Optional[dict]:
        """
        Check for traffic spikes on a website.

        Compares current hour traffic to typical hourly average.

        Args:
            website_id: Website ID

        Returns:
            Dict with spike info if detected, None otherwise
        """
        logger.info(f"Checking traffic spike: website_id={website_id}")

        try:
            # Get alert settings
            settings = self.db.query(AlertSettings).filter(
                AlertSettings.website_id == website_id
            ).first()

            if not settings or not settings.email_enabled:
                logger.debug("Alert settings not found or disabled")
                return None

            now = datetime.utcnow()
            one_hour_ago = now - timedelta(hours=1)
            one_week_ago = now - timedelta(days=7)

            # Get pageviews in last hour
            current_hour_views = self.db.query(
                func.count(Pageview.id)
            ).filter(
                Pageview.website_id == website_id,
                Pageview.timestamp >= one_hour_ago
            ).scalar() or 0

            # Get typical hourly average (last 7 days)
            total_views_week = self.db.query(
                func.count(Pageview.id)
            ).filter(
                Pageview.website_id == website_id,
                Pageview.timestamp >= one_week_ago
            ).scalar() or 0

            # Exclude the current hour from the baseline (it IS the potential
            # spike) and require real history — otherwise a new site's first
            # traffic reads as a huge multiple of its own tiny average.
            baseline_views = max(0, total_views_week - current_hour_views)
            typical_hourly = baseline_views / (7 * 24)  # Average per hour
            if baseline_views < 24:
                logger.debug(f"Spike check skipped: insufficient history ({baseline_views} views/week)")
                return None

            # Check if spike detected
            threshold = settings.spike_threshold
            if typical_hourly > 0 and current_hour_views >= (typical_hourly * threshold):
                spike_data = {
                    'website_id': website_id,
                    'current_hour_views': current_hour_views,
                    'typical_hourly': round(typical_hourly, 2),
                    'threshold': threshold,
                    'spike_percentage': round((current_hour_views / typical_hourly) * 100, 2)
                }
                logger.warning(f"Traffic spike detected: {spike_data}")
                return spike_data

            logger.debug(f"No spike detected: current={current_hour_views}, typical={typical_hourly:.2f}")
            return None

        except Exception as e:
            logger.error(f"Error checking traffic spike: {e}", exc_info=True)
            return None

    def send_spike_alert(
        self,
        website_id: int,
        spike_data: dict,
        user_email: str,
        website_name: str
    ) -> bool:
        """
        Send traffic spike alert email.

        Args:
            website_id: Website ID
            spike_data: Spike information dict
            user_email: User's email address
            website_name: Website name

        Returns:
            True if alert sent successfully
        """
        logger.info(f"Sending spike alert: website_id={website_id}, to={user_email}")

        try:
            # Format alert email
            subject = f"Traffic Spike Alert - {website_name}"

            text_body = f"""
Traffic Spike Detected on {website_name}

Current Hour: {spike_data['current_hour_views']} pageviews
Typical Hour: {spike_data['typical_hourly']} pageviews (7-day average)
Spike: {spike_data['spike_percentage']}% of typical traffic

This is {spike_data['spike_percentage'] / 100:.1f}x your normal traffic level.

View your dashboard for more details.

Argusmetrics
            """

            # Safe fallback when no real email backend is configured.
            if not getattr(email_service, "lettermint_configured", False):
                logger.warning(
                    f"Email backend not configured - spike alert for website "
                    f"{website_id} to {user_email} not sent"
                )
                return False

            safe_website_name = escape(str(website_name))
            html_body = f"""<!DOCTYPE html>
<html>
<body>
    <h2>Traffic Spike Detected on {safe_website_name}</h2>
    <p><strong>Current Hour:</strong> {spike_data['current_hour_views']} pageviews</p>
    <p><strong>Typical Hour:</strong> {spike_data['typical_hourly']} pageviews (7-day average)</p>
    <p><strong>Spike:</strong> {spike_data['spike_percentage']}% of typical traffic</p>
    <p>This is {spike_data['spike_percentage'] / 100:.1f}x your normal traffic level.</p>
    <p>View your dashboard for more details.</p>
    <p>Argusmetrics</p>
</body>
</html>
"""

            # Send via the email service
            success = email_service.send_email(
                to=user_email,
                subject=subject,
                html_content=html_body,
                text_content=text_body
            )

            if success:
                logger.info(f"Spike alert sent to {user_email} for website {website_id}")
            else:
                logger.error(f"Failed to send spike alert to {user_email} for website {website_id}")

            return success

        except Exception as e:
            # Do NOT report success on failure
            logger.error(f"Error sending spike alert: {e}", exc_info=True)
            return False

    def _create_default_settings(self, website_id: int) -> Optional[AlertSettings]:
        """Default alert settings for a website, addressed to its owner.

        The owner rather than whoever is saving, because an admin configuring
        alerts for someone else's site should not redirect them to themselves.
        """
        from app.models.website import Website

        owner_email = self.db.query(Website.user_email).filter(
            Website.id == website_id
        ).scalar()

        if not owner_email:
            logger.warning(f"No website {website_id}; cannot create alert settings")
            return None

        settings = AlertSettings(
            website_id=website_id,
            spike_threshold=2.0,
            email_enabled=True,
            alert_email=owner_email,
        )
        self.db.add(settings)
        self.db.flush()
        logger.info(f"Created alert settings: website_id={website_id}")
        return settings

    def get_or_create_settings(
        self,
        website_id: int,
        user_email: str
    ) -> AlertSettings:
        """
        Get or create alert settings for a website.

        Args:
            website_id: Website ID
            user_email: User's email for alerts

        Returns:
            AlertSettings object
        """
        try:
            settings = self.db.query(AlertSettings).filter(
                AlertSettings.website_id == website_id
            ).first()

            if not settings:
                settings = AlertSettings(
                    website_id=website_id,
                    spike_threshold=2.0,  # Default 200%
                    email_enabled=True,
                    alert_email=user_email
                )
                self.db.add(settings)
                self.db.commit()
                self.db.refresh(settings)
                logger.info(f"Created alert settings: website_id={website_id}")

            return settings

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error getting/creating alert settings: {e}", exc_info=True)
            raise

    def update_settings(
        self,
        website_id: int,
        spike_threshold: float,
        email_enabled: bool
    ) -> Optional[AlertSettings]:
        """
        Update alert settings for a website.

        Args:
            website_id: Website ID
            spike_threshold: New threshold multiplier
            email_enabled: Whether to send email alerts

        Returns:
            Updated AlertSettings object or None on error
        """
        try:
            settings = self.db.query(AlertSettings).filter(
                AlertSettings.website_id == website_id
            ).first()

            if not settings:
                # Create it. Returning None here made the endpoint answer 404
                # "Settings not found" for any website whose settings had
                # never been read, since the GET is what creates the row. So
                # saving worked only if you had loaded the page first, and not
                # at all through the API.
                settings = self._create_default_settings(website_id)
                if not settings:
                    return None

            settings.spike_threshold = spike_threshold
            settings.email_enabled = email_enabled
            self.db.commit()
            self.db.refresh(settings)

            logger.info(f"Alert settings updated: website_id={website_id}")
            return settings

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating alert settings: {e}", exc_info=True)
            return None
