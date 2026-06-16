"""
Analytics service facade.

Delegates to specialized services while maintaining backward compatibility
for all existing call sites. No caller needs to change imports.

Sub-services:
- AnalyticsRecordingService: pageview/event recording, device detection, GeoIP
- AnalyticsQueryService: dashboard stats, timeseries, comparison, realtime
- GoalsService: goal CRUD and conversion tracking
- EventsQueryService: custom events, 404s, outbound links, file downloads
"""
import logging
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from sqlalchemy.orm import Session

from app.services.analytics_recording_service import AnalyticsRecordingService
from app.services.analytics_query_service import AnalyticsQueryService
from app.services.goals_service import GoalsService
from app.services.events_query_service import EventsQueryService

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Facade — delegates to specialized analytics services."""

    def __init__(self, db: Session):
        self.db = db
        self._recording = AnalyticsRecordingService(db)
        self._goals = GoalsService(db)
        self._events = EventsQueryService(db)
        self._query = AnalyticsQueryService(
            db,
            goals_service=self._goals,
            events_service=self._events,
            recording_service=self._recording
        )

    # --- Recording ---

    def record_pageview(self, *args, **kwargs) -> Tuple[bool, str]:
        return self._recording.record_pageview(*args, **kwargs)

    def record_custom_event(self, *args, **kwargs) -> Tuple[bool, str]:
        return self._recording.record_custom_event(*args, **kwargs)

    # --- Dashboard queries ---

    def get_dashboard_stats(self, *args, **kwargs) -> Dict:
        return self._query.get_dashboard_stats(*args, **kwargs)

    def get_realtime_stats(self, *args, **kwargs) -> Dict:
        return self._query.get_realtime_stats(*args, **kwargs)

    # --- Goals ---

    def create_goal(self, *args, **kwargs):
        return self._goals.create_goal(*args, **kwargs)

    def record_goal_conversion(self, *args, **kwargs) -> Tuple[bool, str]:
        return self._goals.record_goal_conversion(*args, **kwargs)

    def get_goal_stats(self, *args, **kwargs) -> Dict:
        return self._goals.get_goal_stats(*args, **kwargs)

    def get_goals_list(self, *args, **kwargs) -> List:
        return self._goals.get_goals_list(*args, **kwargs)

    def delete_goal(self, *args, **kwargs) -> bool:
        return self._goals.delete_goal(*args, **kwargs)

    # --- Events ---

    def get_404_errors(self, *args, **kwargs) -> List[Dict]:
        return self._events.get_404_errors(*args, **kwargs)

    def get_custom_events_summary(self, *args, **kwargs) -> Dict:
        return self._events.get_custom_events_summary(*args, **kwargs)

    def get_event_details(self, *args, **kwargs) -> Dict:
        return self._events.get_event_details(*args, **kwargs)

    def get_outbound_links(self, *args, **kwargs) -> List[Dict]:
        return self._events.get_outbound_links(*args, **kwargs)

    def get_file_downloads(self, *args, **kwargs) -> List[Dict]:
        return self._events.get_file_downloads(*args, **kwargs)

    def get_available_properties(self, *args, **kwargs) -> Dict[str, List[str]]:
        return self._events.get_available_properties(*args, **kwargs)
