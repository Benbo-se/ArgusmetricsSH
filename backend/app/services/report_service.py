"""
Report service for generating analytics reports.

Generates weekly and monthly summary reports with statistics comparison.
"""
import logging
from typing import Dict
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.services.analytics_service import AnalyticsService

logger = logging.getLogger(__name__)


class ReportService:
    """
    Service for generating analytics reports.

    Generates:
    - Weekly reports (last 7 days)
    - Monthly reports (last 30 days)
    - Growth comparisons vs previous period
    """

    def __init__(self, db: Session):
        """
        Initialize report service with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.analytics = AnalyticsService(db)
        logger.debug("ReportService initialized")

    def generate_weekly_report(self, website_id: int) -> Dict:
        """
        Generate weekly analytics report.

        Compares last 7 days to previous 7 days.

        Args:
            website_id: Website ID

        Returns:
            Dict with report data and growth metrics
        """
        logger.info(f"Generating weekly report: website_id={website_id}")

        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        # Get current week stats
        current_stats = self.analytics.get_dashboard_stats(
            website_id=website_id,
            start_date=week_ago,
            end_date=now
        )

        # Get previous week stats for comparison
        previous_stats = self.analytics.get_dashboard_stats(
            website_id=website_id,
            start_date=two_weeks_ago,
            end_date=week_ago
        )

        # Calculate growth percentages
        pageviews_growth = self._calculate_growth(
            previous_stats['total_pageviews'],
            current_stats['total_pageviews']
        )

        visitors_growth = self._calculate_growth(
            previous_stats['unique_visitors'],
            current_stats['unique_visitors']
        )

        report = {
            'period': 'weekly',
            'start_date': week_ago.isoformat(),
            'end_date': now.isoformat(),
            'current': current_stats,
            'previous': previous_stats,
            'growth': {
                'pageviews': pageviews_growth,
                'visitors': visitors_growth
            }
        }

        logger.debug(f"Weekly report generated: {current_stats['total_pageviews']} pageviews")
        return report

    def generate_monthly_report(self, website_id: int) -> Dict:
        """
        Generate monthly analytics report.

        Compares last 30 days to previous 30 days.

        Args:
            website_id: Website ID

        Returns:
            Dict with report data and growth metrics
        """
        logger.info(f"Generating monthly report: website_id={website_id}")

        now = datetime.utcnow()
        month_ago = now - timedelta(days=30)
        two_months_ago = now - timedelta(days=60)

        # Get current month stats
        current_stats = self.analytics.get_dashboard_stats(
            website_id=website_id,
            start_date=month_ago,
            end_date=now
        )

        # Get previous month stats for comparison
        previous_stats = self.analytics.get_dashboard_stats(
            website_id=website_id,
            start_date=two_months_ago,
            end_date=month_ago
        )

        # Calculate growth percentages
        pageviews_growth = self._calculate_growth(
            previous_stats['total_pageviews'],
            current_stats['total_pageviews']
        )

        visitors_growth = self._calculate_growth(
            previous_stats['unique_visitors'],
            current_stats['unique_visitors']
        )

        report = {
            'period': 'monthly',
            'start_date': month_ago.isoformat(),
            'end_date': now.isoformat(),
            'current': current_stats,
            'previous': previous_stats,
            'growth': {
                'pageviews': pageviews_growth,
                'visitors': visitors_growth
            }
        }

        logger.debug(f"Monthly report generated: {current_stats['total_pageviews']} pageviews")
        return report

    def _calculate_growth(self, old_value: int, new_value: int) -> float:
        """
        Calculate percentage growth between two values.

        Args:
            old_value: Previous period value
            new_value: Current period value

        Returns:
            Growth percentage (can be negative)
        """
        if old_value == 0:
            return 100.0 if new_value > 0 else 0.0

        growth = ((new_value - old_value) / old_value) * 100
        return round(growth, 2)

    def format_report_email_html(self, report: Dict, website_name: str) -> str:
        """
        Format report data as HTML email.

        Args:
            report: Report data dict
            website_name: Website name

        Returns:
            HTML string for email body
        """
        period = report['period'].capitalize()
        current = report['current']
        growth = report['growth']

        # Format growth with + for positive
        pageviews_growth_str = f"+{growth['pageviews']}%" if growth['pageviews'] > 0 else f"{growth['pageviews']}%"
        visitors_growth_str = f"+{growth['visitors']}%" if growth['visitors'] > 0 else f"{growth['visitors']}%"

        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #4F46E5; color: white; padding: 20px; text-align: center; }}
                .stats {{ background: #f5f5f5; padding: 20px; margin: 20px 0; }}
                .stat {{ margin: 15px 0; }}
                .stat-label {{ font-weight: bold; color: #666; }}
                .stat-value {{ font-size: 24px; color: #4F46E5; }}
                .growth {{ color: #10B981; font-weight: bold; }}
                .growth.negative {{ color: #EF4444; }}
                .top-list {{ list-style: none; padding: 0; }}
                .top-list li {{ padding: 8px; border-bottom: 1px solid #ddd; }}
                .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 30px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{period} Analytics Report</h1>
                    <p>{website_name}</p>
                </div>

                <div class="stats">
                    <div class="stat">
                        <div class="stat-label">Total Pageviews</div>
                        <div class="stat-value">{current['total_pageviews']:,}</div>
                        <div class="growth {'negative' if growth['pageviews'] < 0 else ''}">{pageviews_growth_str} vs previous period</div>
                    </div>

                    <div class="stat">
                        <div class="stat-label">Unique Visitors</div>
                        <div class="stat-value">{current['unique_visitors']:,}</div>
                        <div class="growth {'negative' if growth['visitors'] < 0 else ''}">{visitors_growth_str} vs previous period</div>
                    </div>
                </div>

                <h3>Top Pages</h3>
                <ul class="top-list">
        """

        for page in current['top_pages'][:5]:
            html += f"<li>{page['path']} - {page['views']} views</li>\n"

        html += """
                </ul>

                <div class="footer">
                    <p>This is an automated report from Argusmetrics</p>
                </div>
            </div>
        </body>
        </html>
        """

        return html
