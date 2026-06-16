"""
AI Insights Dashboard Service for Argusmetrics.

Provides AI-powered analysis of website analytics data using Anthropic Claude API.
Analyzes traffic patterns, identifies trends, and generates actionable recommendations.

Features:
- Traffic trend analysis with AI explanations
- Top performing content identification
- Traffic source analysis
- Optimization suggestions
- Executive summaries
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, distinct

from app.config import settings
from app.models.pageview import Pageview
from app.models.website import Website

logger = logging.getLogger(__name__)


class AIInsightsService:
    """
    Service for generating AI-powered analytics insights.

    Uses Anthropic Claude API to analyze website analytics data and provide
    actionable insights for website owners.

    Attributes:
        db: SQLAlchemy database session
    """

    def __init__(self, db: Session):
        """
        Initialize AI insights service with database session.

        Args:
            db: SQLAlchemy database session for database operations
        """
        self.db = db
        logger.debug("AIInsightsService initialized")

    def _call_claude_api(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful analytics assistant that provides concise, actionable insights.",
        max_tokens: int = 500,
        temperature: float = 0.7
    ) -> Optional[str]:
        """
        Call Anthropic Claude API for AI analysis.

        Args:
            prompt: User prompt with data to analyze
            system_prompt: System prompt to guide AI behavior
            max_tokens: Maximum tokens in response
            temperature: Randomness in response (0-1)

        Returns:
            str: AI response text, or None if error
        """
        if not settings.DEEPSEEK_API_KEY:
            logger.warning("DEEPSEEK_API_KEY not configured, AI insights unavailable")
            return None

        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

            logger.info(f"Calling DeepSeek API with prompt length: {len(prompt)} chars")

            response = client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature
            )

            result = response.choices[0].message.content
            logger.info(f"DeepSeek API response received: {len(result)} chars")
            return result

        except ImportError:
            logger.error("openai package not installed. Install with: pip install openai")
            return None
        except Exception as e:
            logger.error(f"DeepSeek API error: {e}", exc_info=True)
            return None

    def _get_period_data(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        Get analytics data for a specific period.

        Args:
            website_id: Website ID
            start_date: Period start date
            end_date: Period end date

        Returns:
            dict: Analytics metrics for the period
        """
        try:
            # Base filter conditions
            base_conditions = [
                Pageview.website_id == website_id,
                Pageview.timestamp >= start_date,
                Pageview.timestamp <= end_date,
                # Exclude system URLs
                and_(
                    ~Pageview.path.like('/api/%'),
                    ~Pageview.path.like('/static/%'),
                    ~Pageview.path.like('/admin/%'),
                    ~Pageview.path.like('/dashboard/%'),
                    ~Pageview.path.startswith('/_')
                )
            ]

            # Total pageviews
            total_pageviews = self.db.query(func.count(Pageview.id)).filter(
                and_(*base_conditions)
            ).scalar() or 0

            # Unique visitors
            unique_visitors = self.db.query(
                func.count(distinct(Pageview.visitor_hash))
            ).filter(
                and_(*base_conditions)
            ).scalar() or 0

            # Top pages
            top_pages = self.db.query(
                Pageview.path,
                func.count(Pageview.id).label('views')
            ).filter(
                and_(*base_conditions)
            ).group_by(Pageview.path)\
             .order_by(func.count(Pageview.id).desc())\
             .limit(10)\
             .all()

            # Traffic sources (referrers)
            top_referrers = self.db.query(
                Pageview.referrer,
                func.count(Pageview.id).label('views')
            ).filter(
                and_(*base_conditions, Pageview.referrer.isnot(None), Pageview.referrer != '')
            ).group_by(Pageview.referrer)\
             .order_by(func.count(Pageview.id).desc())\
             .limit(10)\
             .all()

            # Device breakdown
            device_stats = self.db.query(
                Pageview.device_type,
                func.count(Pageview.id).label('views')
            ).filter(
                and_(*base_conditions)
            ).group_by(Pageview.device_type).all()

            # Country breakdown
            top_countries = self.db.query(
                Pageview.country,
                func.count(Pageview.id).label('views')
            ).filter(
                and_(*base_conditions, Pageview.country.isnot(None))
            ).group_by(Pageview.country)\
             .order_by(func.count(Pageview.id).desc())\
             .limit(5)\
             .all()

            return {
                'total_pageviews': total_pageviews,
                'unique_visitors': unique_visitors,
                'top_pages': [{'path': p.path, 'views': p.views} for p in top_pages],
                'top_referrers': [{'referrer': r.referrer, 'views': r.views} for r in top_referrers],
                'devices': {d.device_type: d.views for d in device_stats},
                'top_countries': [{'country': c.country, 'views': c.views} for c in top_countries]
            }

        except Exception as e:
            logger.error(f"Error getting period data: {e}", exc_info=True)
            return {
                'total_pageviews': 0,
                'unique_visitors': 0,
                'top_pages': [],
                'top_referrers': [],
                'devices': {},
                'top_countries': []
            }

    def analyze_traffic_trends(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        Analyze traffic trends compared to previous period with AI insights.

        Args:
            website_id: Website ID
            start_date: Current period start date
            end_date: Current period end date

        Returns:
            dict: Traffic trend analysis with AI explanation

        Example:
            {
                "change_percentage": 23.4,
                "direction": "up",
                "current_pageviews": 1500,
                "previous_pageviews": 1200,
                "analysis": "AI explanation of why traffic increased"
            }
        """
        logger.info(f"Analyzing traffic trends for website {website_id}")

        try:
            # Get current period data
            current_data = self._get_period_data(website_id, start_date, end_date)

            # Calculate previous period dates
            period_length = end_date - start_date
            prev_end_date = start_date - timedelta(seconds=1)
            prev_start_date = prev_end_date - period_length

            # Get previous period data
            previous_data = self._get_period_data(website_id, prev_start_date, prev_end_date)

            # Calculate change
            current_views = current_data['total_pageviews']
            prev_views = previous_data['total_pageviews']

            if prev_views == 0:
                change_percentage = 100.0 if current_views > 0 else 0.0
            else:
                change_percentage = ((current_views - prev_views) / prev_views) * 100

            direction = "up" if change_percentage > 0 else "down" if change_percentage < 0 else "stable"

            # Prepare data for AI analysis
            prompt = f"""Analyze this website traffic trend:

Current period ({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}):
- Pageviews: {current_views}
- Unique visitors: {current_data['unique_visitors']}
- Top pages: {', '.join([p['path'] for p in current_data['top_pages'][:3]])}

Previous period ({prev_start_date.strftime('%Y-%m-%d')} to {prev_end_date.strftime('%Y-%m-%d')}):
- Pageviews: {prev_views}
- Unique visitors: {previous_data['unique_visitors']}

Change: {change_percentage:.1f}% {direction}

Provide a 2-3 sentence analysis explaining this trend. Be specific and actionable. Focus on what might have caused the change."""

            # Get AI analysis
            ai_analysis = self._call_claude_api(
                prompt=prompt,
                system_prompt="You are a web analytics expert. Provide concise, actionable insights about traffic trends.",
                max_tokens=200
            )

            return {
                'change_percentage': round(change_percentage, 1),
                'direction': direction,
                'current_pageviews': current_views,
                'previous_pageviews': prev_views,
                'current_visitors': current_data['unique_visitors'],
                'previous_visitors': previous_data['unique_visitors'],
                'analysis': ai_analysis or f"Traffic {direction} by {abs(change_percentage):.1f}% compared to the previous period."
            }

        except Exception as e:
            logger.error(f"Error analyzing traffic trends: {e}", exc_info=True)
            return {
                'change_percentage': 0.0,
                'direction': 'stable',
                'current_pageviews': 0,
                'previous_pageviews': 0,
                'current_visitors': 0,
                'previous_visitors': 0,
                'analysis': 'Unable to analyze traffic trends at this time.'
            }

    def identify_top_performing_content(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Identify top performing pages with AI-powered insights on why they perform well.

        Args:
            website_id: Website ID
            start_date: Analysis start date
            end_date: Analysis end date
            limit: Number of top pages to analyze

        Returns:
            list: Top performing pages with insights

        Example:
            [
                {
                    "path": "/blog/post",
                    "views": 1234,
                    "unique_visitors": 890,
                    "insight": "AI analysis of why this page performs well"
                }
            ]
        """
        logger.info(f"Identifying top performing content for website {website_id}")

        try:
            # Get period data
            data = self._get_period_data(website_id, start_date, end_date)
            top_pages = data['top_pages'][:limit]

            if not top_pages:
                return []

            # Prepare data for AI analysis
            pages_list = "\n".join([
                f"- {p['path']}: {p['views']} views"
                for p in top_pages
            ])

            prompt = f"""Analyze these top performing pages:

{pages_list}

Total traffic: {data['total_pageviews']} pageviews
Top referrers: {', '.join([r['referrer'][:50] for r in data['top_referrers'][:3]])}

For each page, provide ONE brief sentence explaining why it likely performs well. Be specific to the page path."""

            # Get AI analysis
            ai_response = self._call_claude_api(
                prompt=prompt,
                system_prompt="You are a content marketing expert. Analyze why certain pages perform well based on their URLs and traffic patterns.",
                max_tokens=300
            )

            # Parse AI response and match to pages
            # For simplicity, we'll provide a general insight if AI is unavailable
            results = []
            for page in top_pages:
                # Get unique visitors for this page
                unique_visitors = self.db.query(
                    func.count(distinct(Pageview.visitor_hash))
                ).filter(
                    and_(
                        Pageview.website_id == website_id,
                        Pageview.path == page['path'],
                        Pageview.timestamp >= start_date,
                        Pageview.timestamp <= end_date
                    )
                ).scalar() or 0

                results.append({
                    'path': page['path'],
                    'views': page['views'],
                    'unique_visitors': unique_visitors,
                    'percentage': round((page['views'] / data['total_pageviews'] * 100), 1) if data['total_pageviews'] > 0 else 0,
                    'insight': ai_response or f"This page receives {page['views']} views, representing strong user interest."
                })

            return results

        except Exception as e:
            logger.error(f"Error identifying top performing content: {e}", exc_info=True)
            return []

    def detect_traffic_sources(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        Analyze which traffic sources drive most traffic with AI insights.

        Args:
            website_id: Website ID
            start_date: Analysis start date
            end_date: Analysis end date

        Returns:
            dict: Traffic source analysis

        Example:
            {
                "top_sources": [
                    {"source": "google.com", "views": 500, "percentage": 45.5}
                ],
                "analysis": "AI analysis of traffic sources"
            }
        """
        logger.info(f"Detecting traffic sources for website {website_id}")

        try:
            # Get period data
            data = self._get_period_data(website_id, start_date, end_date)

            # Count direct traffic (no referrer)
            direct_traffic = self.db.query(func.count(Pageview.id)).filter(
                and_(
                    Pageview.website_id == website_id,
                    Pageview.timestamp >= start_date,
                    Pageview.timestamp <= end_date,
                    (Pageview.referrer.is_(None)) | (Pageview.referrer == '')
                )
            ).scalar() or 0

            # Prepare source list
            sources = []
            total_views = data['total_pageviews']

            # Add referrers
            for ref in data['top_referrers']:
                sources.append({
                    'source': ref['referrer'],
                    'views': ref['views'],
                    'percentage': round((ref['views'] / total_views * 100), 1) if total_views > 0 else 0
                })

            # Add direct traffic
            if direct_traffic > 0:
                sources.append({
                    'source': 'Direct / None',
                    'views': direct_traffic,
                    'percentage': round((direct_traffic / total_views * 100), 1) if total_views > 0 else 0
                })

            # Sort by views
            sources.sort(key=lambda x: x['views'], reverse=True)

            # Prepare data for AI analysis
            sources_list = "\n".join([
                f"- {s['source']}: {s['views']} views ({s['percentage']}%)"
                for s in sources[:5]
            ])

            prompt = f"""Analyze these traffic sources:

{sources_list}

Total pageviews: {total_views}
Top countries: {', '.join([c['country'] for c in data['top_countries'][:3]])}

Provide 2-3 sentences analyzing the traffic source distribution. What does it tell us about marketing effectiveness? What should be optimized?"""

            # Get AI analysis
            ai_analysis = self._call_claude_api(
                prompt=prompt,
                system_prompt="You are a digital marketing expert. Analyze traffic sources and provide actionable recommendations.",
                max_tokens=250
            )

            return {
                'top_sources': sources[:10],
                'direct_traffic_percentage': round((direct_traffic / total_views * 100), 1) if total_views > 0 else 0,
                'total_views': total_views,
                'analysis': ai_analysis or "Traffic sources analyzed. Consider diversifying your traffic acquisition strategy."
            }

        except Exception as e:
            logger.error(f"Error detecting traffic sources: {e}", exc_info=True)
            return {
                'top_sources': [],
                'direct_traffic_percentage': 0,
                'total_views': 0,
                'analysis': 'Unable to analyze traffic sources at this time.'
            }

    def suggest_optimizations(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> List[str]:
        """
        Generate AI-powered optimization recommendations.

        Args:
            website_id: Website ID
            start_date: Analysis start date
            end_date: Analysis end date

        Returns:
            list: List of actionable optimization recommendations

        Example:
            [
                "Improve mobile experience - 65% of traffic is mobile",
                "Create more content like /blog/popular-post which has 40% of traffic"
            ]
        """
        logger.info(f"Generating optimization suggestions for website {website_id}")

        try:
            # Get comprehensive data
            data = self._get_period_data(website_id, start_date, end_date)

            # Calculate device percentages
            total_views = data['total_pageviews']
            device_breakdown = {}
            for device, views in data['devices'].items():
                device_breakdown[device] = {
                    'views': views,
                    'percentage': round((views / total_views * 100), 1) if total_views > 0 else 0
                }

            # Prepare data for AI
            device_list = "\n".join([
                f"- {device}: {stats['views']} views ({stats['percentage']}%)"
                for device, stats in device_breakdown.items()
            ])

            top_pages_list = "\n".join([
                f"- {p['path']}: {p['views']} views"
                for p in data['top_pages'][:5]
            ])

            referrers_list = "\n".join([
                f"- {r['referrer']}: {r['views']} views"
                for r in data['top_referrers'][:5]
            ])

            prompt = f"""Based on this analytics data, provide 5 specific, actionable optimization recommendations:

Device breakdown:
{device_list}

Top pages:
{top_pages_list}

Traffic sources:
{referrers_list}

Total pageviews: {total_views}
Unique visitors: {data['unique_visitors']}

Format: Return exactly 5 recommendations as a numbered list. Be specific and actionable."""

            # Get AI recommendations
            ai_response = self._call_claude_api(
                prompt=prompt,
                system_prompt="You are a website optimization expert. Provide specific, actionable recommendations based on analytics data.",
                max_tokens=400
            )

            if ai_response:
                # Parse recommendations from AI response
                recommendations = []
                lines = ai_response.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    # Remove numbering and clean up
                    if line and (line[0].isdigit() or line.startswith('-') or line.startswith('•')):
                        # Remove number/bullet and clean
                        cleaned = line.lstrip('0123456789.-•) ').strip()
                        if cleaned:
                            recommendations.append(cleaned)

                return recommendations[:5] if recommendations else self._fallback_recommendations(data, device_breakdown)
            else:
                return self._fallback_recommendations(data, device_breakdown)

        except Exception as e:
            logger.error(f"Error generating optimization suggestions: {e}", exc_info=True)
            return ["Unable to generate optimization suggestions at this time."]

    def _fallback_recommendations(self, data: Dict, device_breakdown: Dict) -> List[str]:
        """Generate fallback recommendations when AI is unavailable."""
        recommendations = []

        # Device optimization
        if 'mobile' in device_breakdown and device_breakdown['mobile']['percentage'] > 60:
            recommendations.append(f"Optimize for mobile - {device_breakdown['mobile']['percentage']}% of traffic is mobile")

        # Content suggestions
        if data['top_pages']:
            top_page = data['top_pages'][0]
            recommendations.append(f"Create more content similar to {top_page['path']} which drives {top_page['views']} views")

        # Traffic diversity
        if data['top_referrers'] and len(data['top_referrers']) < 3:
            recommendations.append("Diversify traffic sources - currently too dependent on few channels")

        # Engagement
        avg_pages_per_visitor = data['total_pageviews'] / data['unique_visitors'] if data['unique_visitors'] > 0 else 0
        if avg_pages_per_visitor < 2:
            recommendations.append("Improve internal linking to increase pages per visitor")

        recommendations.append("Consider implementing conversion goals to track user actions")

        return recommendations[:5]

    def generate_executive_summary(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        Generate comprehensive AI-powered executive summary of website performance.

        Args:
            website_id: Website ID
            start_date: Analysis start date
            end_date: Analysis end date

        Returns:
            dict: Executive summary with all insights combined

        Example:
            {
                "period": "2024-01-01 to 2024-01-31",
                "overview": "AI summary of overall performance",
                "key_metrics": {...},
                "traffic_trend": {...},
                "top_content": [...],
                "recommendations": [...]
            }
        """
        logger.info(f"Generating executive summary for website {website_id}")

        try:
            # Get all analysis components
            traffic_trend = self.analyze_traffic_trends(website_id, start_date, end_date)
            top_content = self.identify_top_performing_content(website_id, start_date, end_date, limit=5)
            traffic_sources = self.detect_traffic_sources(website_id, start_date, end_date)
            recommendations = self.suggest_optimizations(website_id, start_date, end_date)

            # Get current period data for metrics
            current_data = self._get_period_data(website_id, start_date, end_date)

            # Generate AI overview
            prompt = f"""Create a brief executive summary (3-4 sentences) for this website's performance:

Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}

Key Metrics:
- Pageviews: {current_data['total_pageviews']} (change: {traffic_trend['change_percentage']}%)
- Unique Visitors: {current_data['unique_visitors']}
- Traffic Trend: {traffic_trend['direction']}

Top Page: {top_content[0]['path'] if top_content else 'N/A'}
Main Traffic Source: {traffic_sources['top_sources'][0]['source'] if traffic_sources['top_sources'] else 'Direct'}

Provide a concise, positive executive summary highlighting the most important insights."""

            ai_overview = self._call_claude_api(
                prompt=prompt,
                system_prompt="You are an analytics executive. Provide clear, concise summaries for stakeholders.",
                max_tokens=250
            )

            return {
                'period': f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
                'overview': ai_overview or f"Website received {current_data['total_pageviews']} pageviews with a {traffic_trend['direction']} trend.",
                'key_metrics': {
                    'total_pageviews': current_data['total_pageviews'],
                    'unique_visitors': current_data['unique_visitors'],
                    'change_percentage': traffic_trend['change_percentage'],
                    'trend_direction': traffic_trend['direction']
                },
                'traffic_trend': traffic_trend,
                'top_content': top_content,
                'traffic_sources': traffic_sources,
                'recommendations': recommendations
            }

        except Exception as e:
            logger.error(f"Error generating executive summary: {e}", exc_info=True)
            return {
                'period': f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
                'overview': 'Unable to generate summary at this time.',
                'key_metrics': {},
                'traffic_trend': {},
                'top_content': [],
                'traffic_sources': {},
                'recommendations': []
            }
