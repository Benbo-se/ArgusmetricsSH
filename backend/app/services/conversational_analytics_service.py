"""
Conversational Analytics Service - Natural language analytics queries.

Allows users to ask questions like:
- "Show me traffic from USA last week"
- "What's my bounce rate?"
- "Which pages get the most visitors?"
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.pageview import Pageview
from app.models.website import Website
from app.services.analytics_service import AnalyticsService

logger = logging.getLogger(__name__)


class ConversationalAnalyticsService:
    """Service for handling natural language analytics queries."""

    def __init__(self, db: Session):
        """
        Initialize conversational analytics service.

        Args:
            db: Database session
        """
        self.db = db
        self.analytics_service = AnalyticsService(db)

    def is_analytics_query(self, message: str) -> bool:
        """
        Detect if message is an analytics query.

        Args:
            message: User message

        Returns:
            bool: True if analytics query, False otherwise
        """
        message_lower = message.lower()

        # Analytics keywords
        analytics_keywords = [
            'traffic', 'visitors', 'pageviews', 'bounce rate', 'bounce',
            'top pages', 'countries', 'referrers', 'devices', 'browsers',
            'show me', 'how many', 'stats', 'statistics', 'data',
            'users from', 'visits from', 'sweden', 'usa', 'mobile', 'desktop'
        ]

        return any(keyword in message_lower for keyword in analytics_keywords)

    def extract_website_from_context(self, context: Optional[Dict]) -> Optional[int]:
        """
        Extract website ID from query context.

        Args:
            context: Query context dict

        Returns:
            int: Website ID if found, None otherwise
        """
        if context and 'website_id' in context:
            return context['website_id']
        return None

    def extract_time_period(self, message: str) -> Tuple[datetime, datetime]:
        """
        Extract time period from natural language.

        Args:
            message: User message

        Returns:
            tuple: (start_date, end_date)
        """
        now = datetime.now(timezone.utc)
        message_lower = message.lower()

        # Default: last 7 days
        if 'today' in message_lower:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        elif 'yesterday' in message_lower:
            yesterday = now - timedelta(days=1)
            start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif 'last week' in message_lower or 'past week' in message_lower:
            start = now - timedelta(days=7)
            end = now
        elif 'last month' in message_lower or 'past month' in message_lower:
            start = now - timedelta(days=30)
            end = now
        elif 'this month' in message_lower:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = now
        else:
            # Default: last 7 days
            start = now - timedelta(days=7)
            end = now

        return start, end

    def extract_country(self, message: str) -> Optional[str]:
        """
        Extract country from message.

        Args:
            message: User message

        Returns:
            str: Country code if found
        """
        message_lower = message.lower()

        country_map = {
            'sweden': 'SE',
            'sverige': 'SE',
            'usa': 'US',
            'america': 'US',
            'united states': 'US',
            'uk': 'GB',
            'united kingdom': 'GB',
            'germany': 'DE',
            'tyskland': 'DE',
            'france': 'FR',
            'frankrike': 'FR',
            'denmark': 'DK',
            'danmark': 'DK',
            'norway': 'NO',
            'norge': 'NO'
        }

        for country_name, code in country_map.items():
            if country_name in message_lower:
                return code

        return None

    def extract_device(self, message: str) -> Optional[str]:
        """
        Extract device type from message.

        Args:
            message: User message

        Returns:
            str: Device type if found
        """
        message_lower = message.lower()

        if 'mobile' in message_lower or 'mobil' in message_lower:
            return 'mobile'
        elif 'desktop' in message_lower or 'dator' in message_lower:
            return 'desktop'
        elif 'tablet' in message_lower or 'surfplatta' in message_lower:
            return 'tablet'

        return None

    async def process_analytics_query(
        self,
        message: str,
        website_id: int,
        user_email: str
    ) -> str:
        """
        Process natural language analytics query.

        Args:
            message: User query
            website_id: Website ID to query
            user_email: User email for auth

        Returns:
            str: Formatted answer with data
        """
        logger.info(f"Processing analytics query: {message} (website: {website_id})")

        # Extract parameters
        start_date, end_date = self.extract_time_period(message)
        country = self.extract_country(message)
        device = self.extract_device(message)

        message_lower = message.lower()

        # Get basic stats
        stats = self.analytics_service.get_dashboard_stats(
            website_id=website_id,
            user_email=user_email,
            start_date=start_date,
            end_date=end_date,
            filter_country=country,
            filter_device=device
        )

        # Determine what user is asking for
        if 'bounce rate' in message_lower or 'bounce' in message_lower:
            bounce_rate = stats.get('bounce_rate', 0)
            return f"📊 **Bounce Rate**: {bounce_rate}% för den valda perioden."

        elif 'top pages' in message_lower or 'most visited' in message_lower:
            top_pages = stats.get('top_pages', [])[:5]
            if not top_pages:
                return "Ingen data tillgänglig för topp-sidor."

            pages_text = "\n".join([
                f"• {page['path']}: {page['count']} pageviews"
                for page in top_pages
            ])
            return f"📄 **Topp 5 sidor**:\n{pages_text}"

        elif 'countries' in message_lower or 'country' in message_lower:
            countries = stats.get('countries', [])[:10]
            if not countries:
                return "Ingen geografisk data tillgänglig."

            countries_text = "\n".join([
                f"• {c['country']}: {c['count']} visitors"
                for c in countries
            ])
            return f"🌍 **Topp 10 länder**:\n{countries_text}"

        elif 'device' in message_lower or 'devices' in message_lower:
            devices = stats.get('devices', [])
            if not devices:
                return "Ingen enhetsdata tillgänglig."

            devices_text = "\n".join([
                f"• {d['device']}: {d['count']} visitors"
                for d in devices
            ])
            return f"📱 **Enheter**:\n{devices_text}"

        elif 'referrer' in message_lower or 'source' in message_lower:
            referrers = stats.get('referrers', [])[:10]
            if not referrers:
                return "Ingen referrer-data tillgänglig."

            refs_text = "\n".join([
                f"• {r['referrer'] or 'Direct'}: {r['count']} visits"
                for r in referrers
            ])
            return f"🔗 **Topp trafikällor**:\n{refs_text}"

        else:
            # General overview
            total_pageviews = stats.get('total_pageviews', 0)
            unique_visitors = stats.get('unique_visitors', 0)
            bounce_rate = stats.get('bounce_rate', 0)

            period_text = f"{start_date.strftime('%Y-%m-%d')} till {end_date.strftime('%Y-%m-%d')}"
            country_text = f" från {country}" if country else ""
            device_text = f" ({device})" if device else ""

            return f"""📊 **Analytics Översikt** ({period_text}){country_text}{device_text}

• **Pageviews**: {total_pageviews:,}
• **Unique Visitors**: {unique_visitors:,}
• **Bounce Rate**: {bounce_rate}%

Fråga mer specifikt för detaljerad data (t.ex. "top pages", "countries", "devices")"""
