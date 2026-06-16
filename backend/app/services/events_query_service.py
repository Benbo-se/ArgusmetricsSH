"""
Events query service for retrieving custom event analytics.

Handles 404 errors, outbound links, file downloads, event summaries,
and property breakdowns.
"""
import logging
from typing import Optional, Dict, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, distinct

from app.models.custom_event import CustomEvent

logger = logging.getLogger(__name__)


class EventsQueryService:
    """Service for querying custom event analytics."""

    def __init__(self, db: Session):
        self.db = db

    def get_404_errors(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime,
        limit: int = 20
    ) -> List[Dict]:
        """Get 404 error statistics for a website."""
        logger.info(f"Getting 404 errors: website_id={website_id}, start={start_date}, end={end_date}")

        try:
            errors_query = self.db.query(
                CustomEvent.properties['path'].astext.label('path'),
                func.count(CustomEvent.id).label('error_count'),
                func.max(CustomEvent.timestamp).label('last_seen'),
                func.array_agg(
                    func.distinct(CustomEvent.properties['referrer'].astext)
                ).label('referrers')
            ).filter(
                and_(
                    CustomEvent.website_id == website_id,
                    CustomEvent.event_name == '404 Error',
                    CustomEvent.timestamp >= start_date,
                    CustomEvent.timestamp <= end_date,
                    CustomEvent.properties['path'].astext.isnot(None)
                )
            ).group_by(
                CustomEvent.properties['path'].astext
            ).order_by(
                func.count(CustomEvent.id).desc()
            ).limit(limit).all()

            results = []
            for error in errors_query:
                referrers = [r for r in (error.referrers or []) if r and r != 'null']
                top_referrers = referrers[:3] if referrers else []

                results.append({
                    'path': error.path,
                    'error_count': error.error_count,
                    'referrers': top_referrers,
                    'last_seen': error.last_seen.isoformat() if error.last_seen else None
                })

            logger.debug(f"Found {len(results)} unique 404 errors")
            return results

        except Exception as e:
            logger.error(f"Error getting 404 errors: {e}", exc_info=True)
            return []

    def get_custom_events_summary(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """Get custom events summary for dashboard."""
        logger.info(f"Getting custom events summary: website_id={website_id}")

        try:
            events_query = self.db.query(
                CustomEvent.event_name,
                func.count(CustomEvent.id).label('count'),
                func.count(distinct(CustomEvent.visitor_hash)).label('unique_users')
            ).filter(
                and_(
                    CustomEvent.website_id == website_id,
                    CustomEvent.timestamp >= start_date,
                    CustomEvent.timestamp <= end_date
                )
            ).group_by(CustomEvent.event_name)\
             .order_by(func.count(CustomEvent.id).desc())\
             .all()

            events_summary = []
            total_events = 0

            for event in events_query:
                total_events += event.count
                avg_per_user = event.count / event.unique_users if event.unique_users > 0 else 0

                top_properties = self._get_top_property_keys(
                    website_id, event.event_name, start_date, end_date
                )

                events_summary.append({
                    'event_name': event.event_name,
                    'count': event.count,
                    'unique_users': event.unique_users,
                    'avg_per_user': round(avg_per_user, 2),
                    'top_properties': top_properties
                })

            return {
                'events': events_summary,
                'total_events': total_events
            }

        except Exception as e:
            logger.error(f"Error getting custom events summary: {e}", exc_info=True)
            return {'events': [], 'total_events': 0}

    def _get_top_property_keys(
        self,
        website_id: int,
        event_name: str,
        start_date: datetime,
        end_date: datetime,
        limit: int = 3
    ) -> List[str]:
        """Get top property keys for an event."""
        try:
            events = self.db.query(CustomEvent.properties).filter(
                and_(
                    CustomEvent.website_id == website_id,
                    CustomEvent.event_name == event_name,
                    CustomEvent.timestamp >= start_date,
                    CustomEvent.timestamp <= end_date,
                    CustomEvent.properties.isnot(None)
                )
            ).limit(100).all()

            key_counts = {}
            for event in events:
                if event.properties:
                    for key in event.properties.keys():
                        if key not in ['path', 'referrer']:
                            key_counts[key] = key_counts.get(key, 0) + 1

            sorted_keys = sorted(key_counts.items(), key=lambda x: x[1], reverse=True)
            return [key for key, count in sorted_keys[:limit]]

        except Exception as e:
            logger.error(f"Error getting top property keys: {e}", exc_info=True)
            return []

    def get_event_details(
        self,
        website_id: int,
        event_name: str,
        start_date: datetime,
        end_date: datetime,
        limit: int = 100
    ) -> Dict:
        """Get detailed information for a specific custom event."""
        logger.info(f"Getting event details: website_id={website_id}, event={event_name}")

        try:
            stats = self.db.query(
                func.count(CustomEvent.id).label('total_count'),
                func.count(distinct(CustomEvent.visitor_hash)).label('unique_users')
            ).filter(
                and_(
                    CustomEvent.website_id == website_id,
                    CustomEvent.event_name == event_name,
                    CustomEvent.timestamp >= start_date,
                    CustomEvent.timestamp <= end_date
                )
            ).first()

            events = self.db.query(CustomEvent).filter(
                and_(
                    CustomEvent.website_id == website_id,
                    CustomEvent.event_name == event_name,
                    CustomEvent.timestamp >= start_date,
                    CustomEvent.timestamp <= end_date
                )
            ).order_by(CustomEvent.timestamp.desc())\
             .limit(limit)\
             .all()

            property_breakdown = self._get_property_breakdown(
                website_id, event_name, start_date, end_date
            )

            return {
                'event_name': event_name,
                'total_count': stats.total_count or 0,
                'unique_users': stats.unique_users or 0,
                'events': [
                    {
                        'id': e.id,
                        'website_id': e.website_id,
                        'event_name': e.event_name,
                        'properties': e.properties,
                        'path': e.path,
                        'referrer': e.referrer,
                        'country': e.country,
                        'device_type': e.device_type,
                        'browser': e.browser,
                        'timestamp': e.timestamp
                    }
                    for e in events
                ],
                'property_breakdown': property_breakdown
            }

        except Exception as e:
            logger.error(f"Error getting event details: {e}", exc_info=True)
            return {
                'event_name': event_name,
                'total_count': 0,
                'unique_users': 0,
                'events': [],
                'property_breakdown': []
            }

    def _get_property_breakdown(
        self,
        website_id: int,
        event_name: str,
        start_date: datetime,
        end_date: datetime,
        limit: int = 10
    ) -> List[Dict]:
        """Get property value breakdown for an event."""
        try:
            events = self.db.query(CustomEvent.properties).filter(
                and_(
                    CustomEvent.website_id == website_id,
                    CustomEvent.event_name == event_name,
                    CustomEvent.timestamp >= start_date,
                    CustomEvent.timestamp <= end_date,
                    CustomEvent.properties.isnot(None)
                )
            ).all()

            property_counts = {}
            for event in events:
                if event.properties:
                    for key, value in event.properties.items():
                        if key not in ['path', 'referrer']:
                            value_str = str(value)
                            pair_key = f"{key}:{value_str}"
                            if pair_key not in property_counts:
                                property_counts[pair_key] = {
                                    'property_key': key,
                                    'property_value': value_str,
                                    'count': 0
                                }
                            property_counts[pair_key]['count'] += 1

            sorted_items = sorted(
                property_counts.values(),
                key=lambda x: x['count'],
                reverse=True
            )
            return sorted_items[:limit * 3]

        except Exception as e:
            logger.error(f"Error getting property breakdown: {e}", exc_info=True)
            return []

    def get_outbound_links(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """Get outbound link statistics for a website."""
        logger.info(f"Getting outbound links: website_id={website_id}")

        try:
            events = self.db.query(CustomEvent).filter(
                and_(
                    CustomEvent.website_id == website_id,
                    CustomEvent.event_name.like('Outbound Link:%'),
                    CustomEvent.timestamp >= start_date,
                    CustomEvent.timestamp <= end_date
                )
            ).all()

            if not events:
                logger.debug(f"No outbound link events found for website {website_id}")
                return []

            url_stats = {}
            for event in events:
                url = event.event_name.replace('Outbound Link: ', '')

                if url not in url_stats:
                    url_stats[url] = {
                        'url': url,
                        'clicks': 0,
                        'texts': [],
                        'from_pages': []
                    }

                url_stats[url]['clicks'] += 1

                if event.properties:
                    if 'text' in event.properties:
                        url_stats[url]['texts'].append(event.properties['text'])
                    if 'from_page' in event.properties:
                        url_stats[url]['from_pages'].append(event.properties['from_page'])

            total_clicks = sum(stat['clicks'] for stat in url_stats.values())

            results = []
            for url, stats in url_stats.items():
                text_counts = {}
                for text in stats['texts']:
                    text_counts[text] = text_counts.get(text, 0) + 1
                most_common_text = max(text_counts.items(), key=lambda x: x[1])[0] if text_counts else url

                page_counts = {}
                for page in stats['from_pages']:
                    page_counts[page] = page_counts.get(page, 0) + 1
                most_common_page = max(page_counts.items(), key=lambda x: x[1])[0] if page_counts else '/'

                percentage = (stats['clicks'] / total_clicks * 100) if total_clicks > 0 else 0

                results.append({
                    'url': url,
                    'text': most_common_text,
                    'clicks': stats['clicks'],
                    'percentage': round(percentage, 1),
                    'from_page': most_common_page
                })

            results.sort(key=lambda x: x['clicks'], reverse=True)
            logger.debug(f"Found {len(results)} outbound links, returning top 20")
            return results[:20]

        except Exception as e:
            logger.error(f"Error getting outbound links: {e}", exc_info=True)
            return []

    def get_file_downloads(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """Get file download statistics for a website."""
        logger.info(f"Getting file downloads: website_id={website_id}")

        try:
            events = self.db.query(CustomEvent).filter(
                and_(
                    CustomEvent.website_id == website_id,
                    CustomEvent.event_name == 'file_download',
                    CustomEvent.timestamp >= start_date,
                    CustomEvent.timestamp <= end_date
                )
            ).all()

            if not events:
                logger.debug(f"No file download events found for website {website_id}")
                return []

            file_stats = {}
            for event in events:
                if not event.properties:
                    continue

                filename = event.properties.get('filename', 'Unknown')
                file_type = event.properties.get('file_type', 'unknown')
                url = event.properties.get('url', '')
                from_page = event.properties.get('from_page', '/')

                if filename not in file_stats:
                    file_stats[filename] = {
                        'filename': filename,
                        'file_type': file_type,
                        'downloads': 0,
                        'visitor_hashes': set(),
                        'urls': [],
                        'from_pages': []
                    }

                file_stats[filename]['downloads'] += 1
                file_stats[filename]['visitor_hashes'].add(event.visitor_hash)
                file_stats[filename]['urls'].append(url)
                file_stats[filename]['from_pages'].append(from_page)

            results = []
            for filename, stats in file_stats.items():
                url_counts = {}
                for url in stats['urls']:
                    url_counts[url] = url_counts.get(url, 0) + 1
                most_common_url = max(url_counts.items(), key=lambda x: x[1])[0] if url_counts else ''

                page_counts = {}
                for page in stats['from_pages']:
                    page_counts[page] = page_counts.get(page, 0) + 1
                most_common_page = max(page_counts.items(), key=lambda x: x[1])[0] if page_counts else '/'

                results.append({
                    'filename': filename,
                    'file_type': stats['file_type'],
                    'downloads': stats['downloads'],
                    'unique_visitors': len(stats['visitor_hashes']),
                    'url': most_common_url,
                    'from_page': most_common_page
                })

            results.sort(key=lambda x: x['downloads'], reverse=True)
            logger.debug(f"Found {len(results)} file downloads, returning top 50")
            return results[:50]

        except Exception as e:
            logger.error(f"Error getting file downloads: {e}", exc_info=True)
            return []

    def get_available_properties(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, List[str]]:
        """Get all available property keys and their unique values for filtering."""
        logger.info(f"Getting available properties: website_id={website_id}")

        try:
            from app.models.pageview import Pageview

            pageviews_with_props = self.db.query(Pageview.properties).filter(
                Pageview.website_id == website_id,
                Pageview.timestamp >= start_date,
                Pageview.timestamp <= end_date,
                Pageview.properties.isnot(None)
            ).all()

            property_map = {}
            for (properties,) in pageviews_with_props:
                if properties:
                    for key, value in properties.items():
                        if key not in property_map:
                            property_map[key] = set()
                        property_map[key].add(str(value))

            result = {
                key: sorted(list(values))
                for key, values in property_map.items()
            }

            logger.debug(f"Found {len(result)} property keys with values: {list(result.keys())}")
            return result

        except Exception as e:
            logger.error(f"Error getting available properties: {e}", exc_info=True)
            return {}
