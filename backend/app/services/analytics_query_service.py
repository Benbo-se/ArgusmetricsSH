"""
Analytics query service for dashboard statistics and reporting.

Handles dashboard stats, timeseries data, comparison calculations,
and realtime analytics.
"""
import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, distinct

from app.models.pageview import Pageview

logger = logging.getLogger(__name__)


class AnalyticsQueryService:
    """Service for querying analytics data."""

    def __init__(self, db: Session, goals_service=None, events_service=None, recording_service=None):
        self.db = db
        self._goals = goals_service
        self._events = events_service
        self._recording = recording_service

    def get_dashboard_stats(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime,
        compare: bool = False,
        filter_country: Optional[str] = None,
        filter_device: Optional[str] = None,
        filter_browser: Optional[str] = None,
        filter_page: Optional[str] = None,
        filter_referrer: Optional[str] = None,
        filter_properties: Optional[Dict[str, str]] = None
    ) -> Dict:
        """Get dashboard statistics for a date range."""
        logger.info(
            f"Getting dashboard stats: website_id={website_id}, "
            f"start={start_date}, end={end_date}, compare={compare}, "
            f"filters: country={filter_country}, device={filter_device}, "
            f"browser={filter_browser}, page={filter_page}, referrer={filter_referrer}, "
            f"properties={filter_properties}"
        )

        try:
            # Build base filter conditions
            base_conditions = [
                Pageview.website_id == website_id,
                Pageview.timestamp >= start_date,
                Pageview.timestamp <= end_date
            ]

            if filter_country:
                base_conditions.append(Pageview.country == filter_country)
            if filter_device:
                base_conditions.append(Pageview.device_type == filter_device)
            if filter_browser:
                base_conditions.append(Pageview.browser == filter_browser)
            if filter_page:
                base_conditions.append(Pageview.path == filter_page)
            if filter_referrer:
                base_conditions.append(Pageview.referrer == filter_referrer)
            if filter_properties:
                base_conditions.append(Pageview.properties.contains(filter_properties))

            # Exclude system URLs
            base_conditions.append(
                and_(
                    ~Pageview.path.like('/api/%'),
                    ~Pageview.path.like('/static/%'),
                    ~Pageview.path.like('/admin/%'),
                    ~Pageview.path.like('/dashboard/%'),
                    ~Pageview.path.like(r'/\_%', escape='\\')
                )
            )

            # Total pageviews
            total_pageviews = self.db.query(func.count(Pageview.id)).filter(
                and_(*base_conditions)
            ).scalar()

            # Unique visitors
            unique_visitors = self.db.query(
                func.count(distinct(Pageview.visitor_hash))
            ).filter(
                and_(*base_conditions)
            ).scalar()

            # Top pages
            # avg_scroll comes along for free: it is the same grouping, and
            # the column has been written on every pageview since the tracker
            # was built while nothing ever read it. Averaged over the rows
            # that have a value, since a visitor who leaves before the script
            # measures anything records NULL rather than nought.
            top_pages = self.db.query(
                Pageview.path,
                func.count(Pageview.id).label('views'),
                func.avg(Pageview.scroll_depth).label('avg_scroll')
            ).filter(
                and_(*base_conditions)
            ).group_by(Pageview.path)\
             .order_by(func.count(Pageview.id).desc())\
             .limit(10)\
             .all()

            # Entry pages
            entry_pages_subquery = self.db.query(
                Pageview.visitor_hash,
                func.min(Pageview.timestamp).label('first_visit')
            ).filter(and_(*base_conditions))\
             .group_by(Pageview.visitor_hash, func.date(Pageview.timestamp))\
             .subquery()

            entry_pages = self.db.query(
                Pageview.path,
                func.count(Pageview.id).label('entries')
            ).join(entry_pages_subquery,
                and_(
                    Pageview.visitor_hash == entry_pages_subquery.c.visitor_hash,
                    Pageview.timestamp == entry_pages_subquery.c.first_visit
                )
            ).filter(and_(*base_conditions))\
             .group_by(Pageview.path)\
             .order_by(func.count(Pageview.id).desc())\
             .limit(10).all()

            # Exit pages
            exit_pages_subquery = self.db.query(
                Pageview.visitor_hash,
                func.max(Pageview.timestamp).label('last_visit')
            ).filter(and_(*base_conditions))\
             .group_by(Pageview.visitor_hash, func.date(Pageview.timestamp))\
             .subquery()

            exit_pages = self.db.query(
                Pageview.path,
                func.count(Pageview.id).label('exits')
            ).join(exit_pages_subquery,
                and_(
                    Pageview.visitor_hash == exit_pages_subquery.c.visitor_hash,
                    Pageview.timestamp == exit_pages_subquery.c.last_visit
                )
            ).filter(and_(*base_conditions))\
             .group_by(Pageview.path)\
             .order_by(func.count(Pageview.id).desc())\
             .limit(10).all()

            # Top countries
            top_countries = self.db.query(
                Pageview.country,
                func.count(Pageview.id).label('views')
            ).filter(
                and_(*base_conditions, Pageview.country.isnot(None))
            ).group_by(Pageview.country)\
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

            # Top referrers
            top_referrers = self.db.query(
                Pageview.referrer,
                func.count(Pageview.id).label('views')
            ).filter(
                and_(*base_conditions,
                     Pageview.referrer.isnot(None),
                     Pageview.referrer != '')
            ).group_by(Pageview.referrer)\
             .order_by(func.count(Pageview.id).desc())\
             .limit(10)\
             .all()

            # Top browsers
            top_browsers = self.db.query(
                Pageview.browser,
                func.count(Pageview.id).label('views')
            ).filter(
                and_(*base_conditions)
            ).group_by(Pageview.browser)\
             .order_by(func.count(Pageview.id).desc())\
             .limit(10)\
             .all()

            # UTM Campaigns
            utm_campaigns = self.db.query(
                Pageview.utm_source,
                Pageview.utm_medium,
                Pageview.utm_campaign,
                func.count(Pageview.id).label('views')
            ).filter(
                and_(*base_conditions,
                     func.coalesce(Pageview.utm_source, Pageview.utm_medium, Pageview.utm_campaign).isnot(None))
            ).group_by(Pageview.utm_source, Pageview.utm_medium, Pageview.utm_campaign)\
             .order_by(func.count(Pageview.id).desc())\
             .limit(10)\
             .all()

            # Traffic Channels
            all_pageviews = self.db.query(
                Pageview.referrer,
                Pageview.utm_medium
            ).filter(
                and_(*base_conditions)
            ).all()

            channel_counts = {}
            for pv in all_pageviews:
                channel = self._recording._categorize_channel(pv.referrer, pv.utm_medium) if self._recording else "Unknown"
                channel_counts[channel] = channel_counts.get(channel, 0) + 1

            traffic_channels = [
                {"channel": channel, "views": count}
                for channel, count in sorted(
                    channel_counts.items(),
                    key=lambda x: x[1],
                    reverse=True
                )
            ]

            # Goal statistics (delegate to goals service)
            goals_stats = {"goals": [], "total_visitors": 0}
            if self._goals:
                goals_stats = self._goals.get_goal_stats(website_id, start_date, end_date)

            # Outbound links and file downloads (delegate to events service)
            outbound_links = []
            file_downloads = []
            if self._events:
                outbound_links = self._events.get_outbound_links(website_id, start_date, end_date)
                file_downloads = self._events.get_file_downloads(website_id, start_date, end_date)

            # Time series data
            timeseries = self._get_timeseries_data(
                website_id, start_date, end_date,
                filter_country, filter_device, filter_browser, filter_page, filter_referrer,
                filter_properties
            )

            stats = {
                "total_pageviews": total_pageviews or 0,
                "unique_visitors": unique_visitors or 0,
                "top_pages": [
                    {
                        "path": p.path,
                        "views": p.views,
                        # None when no visitor on that page reported a depth,
                        # which the template shows as a dash rather than 0%.
                        "avg_scroll": round(float(p.avg_scroll)) if p.avg_scroll is not None else None,
                    }
                    for p in top_pages
                ],
                "entry_pages": [
                    {"path": e.path, "entries": e.entries} for e in entry_pages
                ],
                "exit_pages": [
                    {"path": e.path, "exits": e.exits} for e in exit_pages
                ],
                "top_countries": [
                    {"country": c.country, "views": c.views} for c in top_countries
                ],
                # device_type is nullable, and a None key here is not merely
                # ugly: json.dumps sorts keys, so mixing None with strings
                # raises and takes the whole dashboard down with a 500.
                "devices": {
                    (d.device_type or "Unknown"): d.views for d in device_stats
                },
                "top_referrers": [
                    {"referrer": r.referrer, "views": r.views} for r in top_referrers
                ],
                "utm_campaigns": [
                    {
                        "utm_source": u.utm_source,
                        "utm_medium": u.utm_medium,
                        "utm_campaign": u.utm_campaign,
                        "views": u.views
                    } for u in utm_campaigns
                ],
                "top_browsers": [
                    {"browser": b.browser, "views": b.views} for b in top_browsers
                ],
                "traffic_channels": traffic_channels,
                "timeseries": timeseries,
                "goals": goals_stats.get("goals", []),
                "total_visitors": goals_stats.get("total_visitors", 0),
                "outbound_links": outbound_links,
                "file_downloads": file_downloads
            }

            # Add comparison data if requested
            if compare:
                period_length = end_date - start_date
                prev_end_date = start_date - timedelta(seconds=1)
                prev_start_date = prev_end_date - period_length

                timeseries_previous = self._get_timeseries_data(
                    website_id, prev_start_date, prev_end_date,
                    filter_country, filter_device, filter_browser, filter_page, filter_referrer,
                    filter_properties
                )
                stats['timeseries_previous'] = timeseries_previous

                comparison_data = self._get_comparison_data(
                    website_id, start_date, end_date,
                    total_pageviews or 0, unique_visitors or 0
                )
                stats.update(comparison_data)

            logger.debug(
                f"Dashboard stats generated: {stats['total_pageviews']} pageviews, "
                f"{stats['unique_visitors']} unique visitors"
            )
            return stats

        except Exception as e:
            logger.error(f"Error getting dashboard stats: {e}", exc_info=True)
            return {
                "total_pageviews": 0,
                "unique_visitors": 0,
                "top_pages": [],
                "entry_pages": [],
                "exit_pages": [],
                "top_countries": [],
                "devices": {},
                "top_referrers": [],
                "utm_campaigns": [],
                "top_browsers": [],
                "traffic_channels": [],
                "timeseries": [],
                "goals": [],
                "total_visitors": 0,
                "outbound_links": [],
                "file_downloads": []
            }

    def _get_timeseries_data(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime,
        filter_country: Optional[str] = None,
        filter_device: Optional[str] = None,
        filter_browser: Optional[str] = None,
        filter_page: Optional[str] = None,
        filter_referrer: Optional[str] = None,
        filter_properties: Optional[Dict[str, str]] = None
    ) -> List[Dict]:
        """Get pageviews over time (for graph)."""
        try:
            conditions = [
                Pageview.website_id == website_id,
                Pageview.timestamp >= start_date,
                Pageview.timestamp <= end_date
            ]

            if filter_country:
                conditions.append(Pageview.country == filter_country)
            if filter_device:
                conditions.append(Pageview.device_type == filter_device)
            if filter_browser:
                conditions.append(Pageview.browser == filter_browser)
            if filter_page:
                conditions.append(Pageview.path == filter_page)
            if filter_referrer:
                conditions.append(Pageview.referrer == filter_referrer)
            if filter_properties:
                conditions.append(Pageview.properties.contains(filter_properties))

            # Same system-URL exclusion as the headline totals — without it the
            # graph disagrees with total_pageviews on any site with API traffic.
            conditions.append(
                and_(
                    ~Pageview.path.like('/api/%'),
                    ~Pageview.path.like('/static/%'),
                    ~Pageview.path.like('/admin/%'),
                    ~Pageview.path.like('/dashboard/%'),
                    ~Pageview.path.like(r'/\_%', escape='\\')
                )
            )

            results = self.db.query(
                func.date(Pageview.timestamp).label('date'),
                func.count(Pageview.id).label('views')
            ).filter(
                and_(*conditions)
            ).group_by(func.date(Pageview.timestamp))\
             .order_by(func.date(Pageview.timestamp)).all()

            return [
                {
                    "date": r.date.isoformat(),
                    "views": r.views
                } for r in results
            ]

        except Exception as e:
            logger.error(f"Error getting timeseries data: {e}", exc_info=True)
            return []

    def _get_comparison_data(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime,
        current_pageviews: int,
        current_visitors: int
    ) -> Dict:
        """Get comparison data for previous period."""
        try:
            period_length = end_date - start_date
            prev_end_date = start_date - timedelta(seconds=1)
            prev_start_date = prev_end_date - period_length

            logger.debug(
                f"Calculating comparison: current={start_date} to {end_date}, "
                f"previous={prev_start_date} to {prev_end_date}"
            )

            prev_pageviews = self.db.query(func.count(Pageview.id)).filter(
                and_(
                    Pageview.website_id == website_id,
                    Pageview.timestamp >= prev_start_date,
                    Pageview.timestamp <= prev_end_date
                )
            ).scalar() or 0

            prev_visitors = self.db.query(
                func.count(distinct(Pageview.visitor_hash))
            ).filter(
                and_(
                    Pageview.website_id == website_id,
                    Pageview.timestamp >= prev_start_date,
                    Pageview.timestamp <= prev_end_date
                )
            ).scalar() or 0

            def calculate_change(current: int, previous: int) -> Optional[float]:
                if previous == 0:
                    if current == 0:
                        return 0.0
                    return 100.0
                return ((current - previous) / previous) * 100

            pageviews_change = calculate_change(current_pageviews, prev_pageviews)
            visitors_change = calculate_change(current_visitors, prev_visitors)

            current_avg = current_pageviews / current_visitors if current_visitors > 0 else 0
            prev_avg = prev_pageviews / prev_visitors if prev_visitors > 0 else 0
            avg_views_change = calculate_change(
                int(current_avg * 100),
                int(prev_avg * 100)
            )

            comparison = {
                "comparison": {
                    "pageviews_change": round(pageviews_change, 1) if pageviews_change is not None else None,
                    "visitors_change": round(visitors_change, 1) if visitors_change is not None else None,
                    "avg_views_change": round(avg_views_change, 1) if avg_views_change is not None else None,
                    "prev_pageviews": prev_pageviews,
                    "prev_visitors": prev_visitors
                }
            }

            logger.debug(
                f"Comparison calculated: pageviews {pageviews_change}%, "
                f"visitors {visitors_change}%"
            )

            return comparison

        except Exception as e:
            logger.error(f"Error calculating comparison data: {e}", exc_info=True)
            return {
                "comparison": {
                    "pageviews_change": None,
                    "visitors_change": None,
                    "avg_views_change": None,
                    "prev_pageviews": 0,
                    "prev_visitors": 0
                }
            }

    def get_realtime_stats(
        self,
        website_id: int
    ) -> Dict:
        """Get realtime analytics (current visitors and recent activity)."""
        logger.info(f"Getting realtime stats: website_id={website_id}")

        try:
            now = datetime.now(timezone.utc)
            five_minutes_ago = now - timedelta(minutes=5)
            one_hour_ago = now - timedelta(hours=1)

            current_visitors = self.db.query(
                func.count(distinct(Pageview.visitor_hash))
            ).filter(
                and_(
                    Pageview.website_id == website_id,
                    Pageview.timestamp >= five_minutes_ago
                )
            ).scalar()

            recent_pageviews = self.db.query(func.count(Pageview.id)).filter(
                and_(
                    Pageview.website_id == website_id,
                    Pageview.timestamp >= one_hour_ago
                )
            ).scalar()

            # Bounded to the last hour: without a time filter this returned the
            # 50 most recent pageviews EVER and presented them as "live".
            live_visitors_query = self.db.query(
                Pageview.country,
                Pageview.path,
                Pageview.timestamp
            ).filter(
                and_(
                    Pageview.website_id == website_id,
                    Pageview.timestamp >= one_hour_ago
                )
            ).order_by(Pageview.timestamp.desc())\
             .limit(50)\
             .all()

            live_visitors = [
                {
                    "country": v.country,
                    "path": v.path,
                    "timestamp": v.timestamp.isoformat() if v.timestamp else None
                } for v in live_visitors_query
            ]

            stats = {
                "current_visitors": current_visitors or 0,
                "recent_pageviews": recent_pageviews or 0,
                "live_visitors": live_visitors
            }

            logger.debug(
                f"Realtime stats: {stats['current_visitors']} current visitors, "
                f"{stats['recent_pageviews']} recent pageviews"
            )
            return stats

        except Exception as e:
            logger.error(f"Error getting realtime stats: {e}", exc_info=True)
            return {
                "current_visitors": 0,
                "recent_pageviews": 0,
                "live_visitors": []
            }
