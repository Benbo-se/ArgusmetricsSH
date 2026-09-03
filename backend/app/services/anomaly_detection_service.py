"""
Anomaly Detection Service - AI-powered traffic analysis.

Detects unusual patterns in analytics data:
- Traffic spikes
- Geographic anomalies
- Bot attacks
- Referrer spam
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.models.pageview import Pageview
from app.models.website import Website
from app.models.user import User

logger = logging.getLogger(__name__)


class AnomalyDetectionService:
    """Service for detecting anomalies in analytics data."""

    def __init__(self, db: Session):
        """
        Initialize anomaly detection service.

        Args:
            db: Database session
        """
        self.db = db

    def _get_baseline_metrics(
        self,
        website_id: int,
        hours: int = 24
    ) -> Dict[str, float]:
        """
        Calculate baseline metrics for comparison.

        Args:
            website_id: Website ID
            hours: Hours to look back for baseline

        Returns:
            dict: Baseline metrics (avg pageviews/hour, unique countries, etc.)
        """
        now = datetime.now(timezone.utc)
        baseline_start = now - timedelta(hours=hours)

        # Get baseline pageview count
        baseline_count = self.db.query(func.count(Pageview.id)).filter(
            Pageview.website_id == website_id,
            Pageview.timestamp >= baseline_start
        ).scalar() or 0

        # Calculate average pageviews per hour
        avg_pageviews_per_hour = baseline_count / hours if hours > 0 else 0

        # Get unique countries in baseline period
        unique_countries = self.db.query(func.count(func.distinct(Pageview.country))).filter(
            Pageview.website_id == website_id,
            Pageview.timestamp >= baseline_start,
            Pageview.country.isnot(None)
        ).scalar() or 0

        # Get top referrers
        top_referrers = self.db.query(
            Pageview.referrer,
            func.count(Pageview.id).label('count')
        ).filter(
            Pageview.website_id == website_id,
            Pageview.timestamp >= baseline_start,
            Pageview.referrer.isnot(None)
        ).group_by(Pageview.referrer).order_by(func.count(Pageview.id).desc()).limit(10).all()

        return {
            'avg_pageviews_per_hour': avg_pageviews_per_hour,
            'total_pageviews': baseline_count,
            'unique_countries': unique_countries,
            'top_referrers': [r.referrer for r in top_referrers]
        }

    def detect_traffic_spike(
        self,
        website_id: int,
        threshold_multiplier: float = 3.0
    ) -> Optional[Dict]:
        """
        Detect traffic spikes (sudden increase in pageviews).

        Args:
            website_id: Website ID
            threshold_multiplier: How many times normal traffic to trigger alert

        Returns:
            dict: Anomaly details if detected, None otherwise
        """
        # Get baseline (last 24 hours average)
        baseline = self._get_baseline_metrics(website_id, hours=24)

        # Get current hour traffic
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)

        current_hour_count = self.db.query(func.count(Pageview.id)).filter(
            Pageview.website_id == website_id,
            Pageview.timestamp >= hour_start
        ).scalar() or 0

        # Exclude the current hour from the baseline (it contains the very
        # spike being measured) and require a real history: a brand-new site
        # whose only traffic is this hour would otherwise compute
        # baseline = N/24 and flag its own first visitors as a ~24x spike.
        baseline_count_excl = max(0, baseline['total_pageviews'] - current_hour_count)
        baseline_avg = baseline_count_excl / 24
        if baseline_count_excl < 24:
            return None

        # Check if current traffic exceeds threshold
        if baseline_avg > 0:
            spike_ratio = current_hour_count / baseline_avg

            if spike_ratio >= threshold_multiplier:
                return {
                    'type': 'traffic_spike',
                    'severity': 'high' if spike_ratio >= 5.0 else 'medium',
                    'current_pageviews': current_hour_count,
                    'baseline_avg': round(baseline_avg, 2),
                    'spike_ratio': round(spike_ratio, 2),
                    'message': f"Traffic spike detected: {int(spike_ratio)}x normal volume",
                    'timestamp': now.isoformat()
                }

        return None

    def detect_geographic_anomaly(
        self,
        website_id: int
    ) -> Optional[Dict]:
        """
        Detect unusual geographic traffic patterns.

        Args:
            website_id: Website ID

        Returns:
            dict: Anomaly details if detected, None otherwise
        """
        # Get baseline countries (last 7 days)
        baseline = self._get_baseline_metrics(website_id, hours=24 * 7)

        # Get current hour countries
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)

        current_countries = self.db.query(
            Pageview.country,
            func.count(Pageview.id).label('count')
        ).filter(
            Pageview.website_id == website_id,
            Pageview.timestamp >= hour_start,
            Pageview.country.isnot(None)
        ).group_by(Pageview.country).all()

        # Total traffic this hour is invariant across the loop; compute once.
        total_this_hour = sum(c.count for c in current_countries)

        # Check for new countries with significant traffic
        for country in current_countries:
            # If country has >50% of traffic this hour, flag it
            country_percentage = (country.count / total_this_hour * 100) if total_this_hour > 0 else 0

            if country_percentage >= 50 and country.count >= 10:
                return {
                    'type': 'geographic_anomaly',
                    'severity': 'medium',
                    'country': country.country,
                    'percentage': round(country_percentage, 1),
                    'pageviews': country.count,
                    'message': f"Unusual traffic from {country.country}: {int(country_percentage)}% of traffic",
                    'timestamp': now.isoformat()
                }

        return None

    def detect_bot_attack(
        self,
        website_id: int
    ) -> Optional[Dict]:
        """
        Detect potential bot attacks (repeated requests from same IP/visitor).

        Args:
            website_id: Website ID

        Returns:
            dict: Anomaly details if detected, None otherwise
        """
        # Get current hour
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)

        # Find visitors with excessive pageviews
        suspicious_visitors = self.db.query(
            Pageview.visitor_hash,
            func.count(Pageview.id).label('count')
        ).filter(
            Pageview.website_id == website_id,
            Pageview.timestamp >= hour_start,
            Pageview.visitor_hash.isnot(None)
        ).group_by(Pageview.visitor_hash).having(
            func.count(Pageview.id) > 50  # More than 50 pageviews/hour is suspicious
        ).all()

        if suspicious_visitors:
            top_bot = max(suspicious_visitors, key=lambda x: x.count)

            return {
                'type': 'bot_attack',
                'severity': 'high',
                'visitor_count': len(suspicious_visitors),
                'top_bot_pageviews': top_bot.count,
                'message': f"Potential bot attack: {len(suspicious_visitors)} visitors with >50 pageviews/hour",
                'timestamp': now.isoformat()
            }

        return None

    def detect_referrer_spam(
        self,
        website_id: int
    ) -> Optional[Dict]:
        """
        Detect referrer spam (suspicious referrer patterns).

        Args:
            website_id: Website ID

        Returns:
            dict: Anomaly details if detected, None otherwise
        """
        # Get current hour referrers
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)

        # Common spam referrer patterns
        spam_patterns = [
            '.ru/', 'semalt', 'buttons-for-website', 'free-share-buttons',
            'get-free-traffic', 'social-buttons', 'event-tracking'
        ]

        # Check for spam referrers
        for pattern in spam_patterns:
            spam_count = self.db.query(func.count(Pageview.id)).filter(
                Pageview.website_id == website_id,
                Pageview.timestamp >= hour_start,
                Pageview.referrer.ilike(f'%{pattern}%')
            ).scalar() or 0

            if spam_count >= 10:
                return {
                    'type': 'referrer_spam',
                    'severity': 'low',
                    'pattern': pattern,
                    'count': spam_count,
                    'message': f"Referrer spam detected: {spam_count} pageviews from suspicious source",
                    'timestamp': now.isoformat()
                }

        return None

    def run_all_detections(
        self,
        website_id: int,
        user: User
    ) -> List[Dict]:
        """
        Run all anomaly detection checks.

        Args:
            website_id: Website ID
            user: User making the request

        Returns:
            list: List of detected anomalies
        """
        anomalies = []

        # Run all detection methods
        detections = [
            self.detect_traffic_spike(website_id),
            self.detect_geographic_anomaly(website_id),
            self.detect_bot_attack(website_id),
            self.detect_referrer_spam(website_id)
        ]

        # Collect all detected anomalies
        for anomaly in detections:
            if anomaly:
                anomalies.append(anomaly)

        logger.info(f"Anomaly detection for website {website_id}: {len(anomalies)} anomalies found")

        return anomalies
