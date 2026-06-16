"""
Email reports service for generating and sending automated analytics reports.

Handles:
- Generating report data from analytics
- Formatting reports into HTML emails
- Sending scheduled weekly/monthly reports
"""
import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.website import Website
from app.models.pageview import Pageview
from app.config import settings

logger = logging.getLogger(__name__)


class EmailReportsService:
    """
    Service for generating and sending analytics email reports.
    """

    def __init__(self, db: Session):
        self.db = db

    def generate_report_data(self, website_id: int, period: str = "weekly") -> Dict:
        """
        Generate analytics report data for a website.

        Args:
            website_id: Website ID to generate report for
            period: Report period - "weekly" or "monthly"

        Returns:
            dict: Report data including metrics, top pages, referrers, etc.
        """
        # Calculate date range
        now = datetime.now(timezone.utc)

        if period == "weekly":
            start_date = now - timedelta(days=7)
            period_label = "Last 7 Days"
        elif period == "monthly":
            start_date = now - timedelta(days=30)
            period_label = "Last 30 Days"
        else:
            raise ValueError(f"Invalid period: {period}")

        # Get total pageviews
        total_pageviews = self.db.query(func.count(Pageview.id)).filter(
            Pageview.website_id == website_id,
            Pageview.timestamp >= start_date
        ).scalar() or 0

        # Get unique visitors
        unique_visitors = self.db.query(func.count(func.distinct(Pageview.visitor_hash))).filter(
            Pageview.website_id == website_id,
            Pageview.timestamp >= start_date
        ).scalar() or 0

        # Get top pages
        top_pages = self.db.query(
            Pageview.path,
            func.count(Pageview.id).label('views')
        ).filter(
            Pageview.website_id == website_id,
            Pageview.timestamp >= start_date
        ).group_by(Pageview.path).order_by(func.count(Pageview.id).desc()).limit(10).all()

        # Get top referrers
        top_referrers = self.db.query(
            Pageview.referrer,
            func.count(Pageview.id).label('views')
        ).filter(
            Pageview.website_id == website_id,
            Pageview.timestamp >= start_date,
            Pageview.referrer.isnot(None),
            Pageview.referrer != ''
        ).group_by(Pageview.referrer).order_by(func.count(Pageview.id).desc()).limit(10).all()

        # Get top countries
        top_countries = self.db.query(
            Pageview.country,
            func.count(Pageview.id).label('views')
        ).filter(
            Pageview.website_id == website_id,
            Pageview.timestamp >= start_date,
            Pageview.country.isnot(None)
        ).group_by(Pageview.country).order_by(func.count(Pageview.id).desc()).limit(10).all()

        # Get top devices
        top_devices = self.db.query(
            Pageview.device_type,
            func.count(Pageview.id).label('views')
        ).filter(
            Pageview.website_id == website_id,
            Pageview.timestamp >= start_date,
            Pageview.device_type.isnot(None)
        ).group_by(Pageview.device_type).order_by(func.count(Pageview.id).desc()).limit(5).all()

        # Get top browsers
        top_browsers = self.db.query(
            Pageview.browser,
            func.count(Pageview.id).label('views')
        ).filter(
            Pageview.website_id == website_id,
            Pageview.timestamp >= start_date,
            Pageview.browser.isnot(None)
        ).group_by(Pageview.browser).order_by(func.count(Pageview.id).desc()).limit(5).all()

        return {
            "period": period_label,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": now.strftime("%Y-%m-%d"),
            "total_pageviews": total_pageviews,
            "unique_visitors": unique_visitors,
            "top_pages": [{"path": p.path, "views": p.views} for p in top_pages],
            "top_referrers": [{"referrer": r.referrer, "views": r.views} for r in top_referrers],
            "top_countries": [{"country": c.country, "views": c.views} for c in top_countries],
            "top_devices": [{"device": d.device_type, "views": d.views} for d in top_devices],
            "top_browsers": [{"browser": b.browser, "views": b.views} for b in top_browsers],
        }

    def generate_report_html(self, website: Website, report_data: Dict) -> str:
        """
        Generate HTML email for analytics report.

        Args:
            website: Website model instance
            report_data: Report data from generate_report_data()

        Returns:
            str: HTML email content
        """
        dashboard_url = f"{settings.BASE_URL}/dashboard/{website.id}"
        website_name = html.escape(str(website.name))
        website_domain = html.escape(str(website.domain))

        report_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; text-align: center; }}
        .header h1 {{ margin: 0; font-size: 24px; }}
        .header p {{ margin: 5px 0 0 0; opacity: 0.9; }}
        .content {{ background: #f7f7f7; padding: 30px; border-radius: 0 0 10px 10px; }}
        .metric-card {{ background: white; padding: 20px; margin: 15px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .metric-card h2 {{ margin: 0 0 10px 0; font-size: 36px; color: #667eea; }}
        .metric-card p {{ margin: 0; color: #666; font-size: 14px; }}
        .stat-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 20px 0; }}
        .section {{ margin: 25px 0; }}
        .section h3 {{ color: #333; font-size: 18px; margin-bottom: 15px; }}
        .list-item {{ background: white; padding: 12px 15px; margin: 8px 0; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }}
        .list-item .name {{ font-weight: 500; }}
        .list-item .count {{ color: #667eea; font-weight: 600; }}
        .button {{ display: inline-block; background: #667eea; color: white; padding: 12px 30px; text-decoration: none; border-radius: 6px; margin: 20px 0; font-weight: 500; }}
        .footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{settings.APP_NAME} Analytics Report</h1>
        <p>{website_name} - {report_data['period']}</p>
    </div>

    <div class="content">
        <div class="stat-grid">
            <div class="metric-card">
                <h2>{report_data['total_pageviews']:,}</h2>
                <p>Total Pageviews</p>
            </div>
            <div class="metric-card">
                <h2>{report_data['unique_visitors']:,}</h2>
                <p>Unique Visitors</p>
            </div>
        </div>

        {"<div class='section'><h3>📄 Top Pages</h3>" + "".join(f"<div class='list-item'><span class='name'>{html.escape(str(item['path']))}</span><span class='count'>{item['views']:,} views</span></div>" for item in report_data['top_pages'][:5]) + "</div>" if report_data['top_pages'] else ""}

        {"<div class='section'><h3>🔗 Top Referrers</h3>" + "".join(f"<div class='list-item'><span class='name'>{html.escape(str(item['referrer']))}</span><span class='count'>{item['views']:,} views</span></div>" for item in report_data['top_referrers'][:5]) + "</div>" if report_data['top_referrers'] else ""}

        {"<div class='section'><h3>🌍 Top Countries</h3>" + "".join(f"<div class='list-item'><span class='name'>{html.escape(str(item['country']))}</span><span class='count'>{item['views']:,} views</span></div>" for item in report_data['top_countries'][:5]) + "</div>" if report_data['top_countries'] else ""}

        <div style="text-align: center;">
            <a href="{dashboard_url}" class="button">View Full Dashboard →</a>
        </div>

        <div class="footer">
            <p>You're receiving this because you enabled email reports for {website_domain}</p>
            <p>To change your email preferences, visit your <a href="{dashboard_url}/settings">website settings</a></p>
        </div>
    </div>
</body>
</html>"""

        return report_html

    def send_report(self, website_id: int) -> bool:
        """
        Generate and send analytics report for a website.

        Args:
            website_id: Website ID to send report for

        Returns:
            bool: True if report was sent successfully
        """
        try:
            # Get website
            website = self.db.query(Website).filter(Website.id == website_id).first()
            if not website:
                logger.error(f"Website {website_id} not found")
                return False

            # Check if email reports are enabled
            if not website.email_reports_enabled:
                logger.info(f"Email reports not enabled for website {website_id}")
                return False

            if not website.email_reports_recipient:
                logger.error(f"No recipient configured for website {website_id}")
                return False

            # Generate report data
            period = website.email_reports_frequency or "weekly"
            report_data = self.generate_report_data(website_id, period)

            # Generate HTML
            html_content = self.generate_report_html(website, report_data)

            # Send email
            from app.services.email_service import email_service

            subject = f"{settings.APP_NAME} - {report_data['period']} Report for {website.name}"

            success = email_service.send_email(
                to=website.email_reports_recipient,
                subject=subject,
                html_content=html_content
            )

            if success:
                logger.info(f"Email report sent successfully for website {website_id}")
            else:
                logger.error(f"Failed to send email report for website {website_id}")

            return success

        except Exception as e:
            logger.error(f"Error sending email report for website {website_id}: {e}", exc_info=True)
            return False

    def get_websites_due_for_report(self, frequency: str, day_of_week_or_month: int) -> List[Website]:
        """
        Get all websites that are due for a report.

        Args:
            frequency: "weekly" or "monthly"
            day_of_week_or_month: 1-7 for weekly (Mon-Sun), 1-31 for monthly

        Returns:
            List[Website]: Websites due for reports
        """
        websites = self.db.query(Website).filter(
            Website.email_reports_enabled == True,
            Website.email_reports_frequency == frequency,
            Website.email_reports_day == day_of_week_or_month
        ).all()

        return websites

    def send_scheduled_reports(self) -> Dict[str, int]:
        """
        Send all due email reports based on current date/time.

        Should be called daily by a cron job.

        Returns:
            dict: Statistics about reports sent
        """
        now = datetime.now(timezone.utc)
        day_of_week = now.isoweekday()  # 1-7 (Monday-Sunday)
        day_of_month = now.day  # 1-31

        stats = {
            "weekly_attempted": 0,
            "weekly_sent": 0,
            "monthly_attempted": 0,
            "monthly_sent": 0,
            "total_failures": 0
        }

        # Send weekly reports
        weekly_websites = self.get_websites_due_for_report("weekly", day_of_week)
        for website in weekly_websites:
            stats["weekly_attempted"] += 1
            if self.send_report(website.id):
                stats["weekly_sent"] += 1
            else:
                stats["total_failures"] += 1

        # Send monthly reports
        monthly_websites = self.get_websites_due_for_report("monthly", day_of_month)
        for website in monthly_websites:
            stats["monthly_attempted"] += 1
            if self.send_report(website.id):
                stats["monthly_sent"] += 1
            else:
                stats["total_failures"] += 1

        logger.info(f"Scheduled email reports sent: {stats}")
        return stats
