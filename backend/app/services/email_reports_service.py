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
from app.services.filters import counted
from app.config import settings
from app.services.traffic_sources import own_referrer_regex
from app.services import email_layout

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
            days = 7
            period_label = "Last 7 Days"
        elif period == "monthly":
            days = 30
            period_label = "Last 30 Days"
        else:
            raise ValueError(f"Invalid period: {period}")
        start_date = now - timedelta(days=days)
        before_that = start_date - timedelta(days=days)

        # Get total pageviews
        total_pageviews = self.db.query(func.count(Pageview.id)).filter(
            Pageview.website_id == website_id,
            counted(website_id),
            Pageview.timestamp >= start_date
        ).scalar() or 0

        # Get unique visitors
        unique_visitors = self.db.query(func.count(func.distinct(Pageview.visitor_hash))).filter(
            Pageview.website_id == website_id,
            counted(website_id),
            Pageview.timestamp >= start_date
        ).scalar() or 0

        # The same two numbers for the stretch before, to say which way it went
        previous = self.db.query(
            func.count(Pageview.id),
            func.count(func.distinct(Pageview.visitor_hash)),
        ).filter(
            Pageview.website_id == website_id,
            counted(website_id),
            Pageview.timestamp >= before_that,
            Pageview.timestamp < start_date,
        ).one()

        # Pageviews per 24 hours counted back from now, so the bars add up to
        # the total above whatever the hour the report is sent.
        age = func.floor(func.extract('epoch', now - Pageview.timestamp) / 86400)
        per_day = dict(self.db.query(age, func.count(Pageview.id)).filter(
            Pageview.website_id == website_id,
            counted(website_id),
            Pageview.timestamp >= start_date,
            Pageview.timestamp <= now,
        ).group_by(age).all())
        daily = [
            {"date": (now - timedelta(days=back)).strftime("%Y-%m-%d"),
             "views": int(per_day.get(back, 0))}
            for back in range(days - 1, -1, -1)
        ]

        # Get top pages
        top_pages = self.db.query(
            Pageview.path,
            func.count(Pageview.id).label('views')
        ).filter(
            Pageview.website_id == website_id,
            counted(website_id),
            Pageview.timestamp >= start_date
        ).group_by(Pageview.path).order_by(func.count(Pageview.id).desc()).limit(10).all()

        # Get top referrers
        own_domain = self.db.query(Website.domain).filter(Website.id == website_id).scalar()
        own_regex = own_referrer_regex(own_domain)
        top_referrers = self.db.query(
            Pageview.referrer,
            func.count(Pageview.id).label('views')
        ).filter(
            Pageview.website_id == website_id,
            counted(website_id),
            Pageview.timestamp >= start_date,
            Pageview.referrer.isnot(None),
            Pageview.referrer != '',
            *([Pageview.referrer.op('!~*')(own_regex)] if own_regex else [])
        ).group_by(Pageview.referrer).order_by(func.count(Pageview.id).desc()).limit(10).all()

        # Get top countries
        top_countries = self.db.query(
            Pageview.country,
            func.count(Pageview.id).label('views')
        ).filter(
            Pageview.website_id == website_id,
            counted(website_id),
            Pageview.timestamp >= start_date,
            Pageview.country.isnot(None)
        ).group_by(Pageview.country).order_by(func.count(Pageview.id).desc()).limit(10).all()

        # Get top devices
        top_devices = self.db.query(
            Pageview.device_type,
            func.count(Pageview.id).label('views')
        ).filter(
            Pageview.website_id == website_id,
            counted(website_id),
            Pageview.timestamp >= start_date,
            Pageview.device_type.isnot(None)
        ).group_by(Pageview.device_type).order_by(func.count(Pageview.id).desc()).limit(5).all()

        # Get top browsers
        top_browsers = self.db.query(
            Pageview.browser,
            func.count(Pageview.id).label('views')
        ).filter(
            Pageview.website_id == website_id,
            counted(website_id),
            Pageview.timestamp >= start_date,
            Pageview.browser.isnot(None)
        ).group_by(Pageview.browser).order_by(func.count(Pageview.id).desc()).limit(5).all()

        return {
            "period": period_label,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": now.strftime("%Y-%m-%d"),
            "total_pageviews": total_pageviews,
            "unique_visitors": unique_visitors,
            "previous_pageviews": int(previous[0] or 0),
            "previous_visitors": int(previous[1] or 0),
            "daily": daily,
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
        dashboard_url = f"{settings.BASE_URL}/dashboard/website/{website.id}"
        visitors = report_data['unique_visitors']
        pageviews = report_data['total_pageviews']
        daily = report_data.get('daily') or []
        stretch = "week" if len(daily) <= 7 else "30 days"

        def against(now_value: int, then_value: Optional[int]) -> Optional[str]:
            if not then_value:
                return None
            change = round(100 * (now_value - then_value) / then_value)
            if change == 0:
                return f"same as the {stretch} before"
            return f"{'up' if change > 0 else 'down'} {abs(change)}% on the {stretch} before"

        if len(daily) <= 7:
            captions = [datetime.strptime(d["date"], "%Y-%m-%d").strftime("%a") for d in daily]
        else:
            # Thirty names do not fit under thirty bars: first, middle and last.
            captions = [""] * len(daily)
            for at in (0, len(daily) // 2, len(daily) - 1):
                captions[at] = datetime.strptime(daily[at]["date"], "%Y-%m-%d").strftime("%-d/%-m")

        if pageviews:
            heading = (f"{visitors:,} {'person' if visitors == 1 else 'people'} came by "
                       f"{email_layout.aside(website.name)}.")
            body = [
                email_layout.figures([
                    ("Visitors", f"{visitors:,}", against(visitors, report_data.get('previous_visitors'))),
                    ("Pageviews", f"{pageviews:,}", against(pageviews, report_data.get('previous_pageviews'))),
                ]),
                email_layout.chart([d["views"] for d in daily], captions) if daily else "",
                email_layout.ranking("Most read pages",
                                     [(i['path'], i['views']) for i in report_data['top_pages'][:5]]),
                email_layout.ranking("Where they came from",
                                     [(self._source_name(i['referrer']), i['views'])
                                      for i in report_data['top_referrers'][:5]]),
                email_layout.ranking("Countries",
                                     [(i['country'], i['views']) for i in report_data['top_countries'][:5]]),
                email_layout.button("Open the dashboard", dashboard_url),
            ]
        else:
            heading = f"A quiet {stretch} for {email_layout.aside(website.name)}."
            body = [
                email_layout.text("No visits were counted. If that is not what you expected, check that the "
                                  "tracking line is still on the pages."),
                email_layout.button("Open the dashboard", dashboard_url),
            ]

        body.append(email_layout.text(
            f"Reports for {html.escape(str(website.domain))} are switched on and off under "
            f"<a href=\"{html.escape(dashboard_url)}/settings\" style=\"color:{email_layout.PEACOCK_DEEP};\">"
            "the website's settings</a>.", small=True))

        return email_layout.render(
            eyebrow=f"{report_data['period']} · {report_data['start_date']} to {report_data['end_date']}",
            heading_html=heading,
            preheader=f"{visitors:,} visitors and {pageviews:,} pageviews, {report_data['period'].lower()}.",
            body=body,
            reason="You are getting this because email reports are switched on for this website.",
        )

    @staticmethod
    def _source_name(referrer: str) -> str:
        """A referrer as a person would say it: the address without the scheme."""
        name = str(referrer).split("://", 1)[-1].rstrip("/")
        return name[4:] if name.startswith("www.") else name

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
        query = self.db.query(Website).filter(
            Website.email_reports_enabled == True,
            Website.email_reports_frequency == frequency,
        )

        if frequency == "monthly":
            import calendar
            from datetime import datetime, timezone as _tz
            now = datetime.now(_tz.utc)
            last_day = calendar.monthrange(now.year, now.month)[1]
            if day_of_week_or_month == last_day:
                # On the last day of a short month, also send the reports
                # configured for days that don't exist this month (29/30/31),
                # which would otherwise silently never fire.
                query = query.filter(Website.email_reports_day >= day_of_week_or_month)
            else:
                query = query.filter(Website.email_reports_day == day_of_week_or_month)
        else:
            query = query.filter(Website.email_reports_day == day_of_week_or_month)

        return query.all()

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
