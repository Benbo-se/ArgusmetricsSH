"""Date range parsing utility."""
from datetime import datetime, timedelta, timezone
import re
from typing import Optional, Tuple

_BARE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date_range(range_str: str) -> Tuple[datetime, datetime]:
    """Parse a date range string into start and end datetimes (UTC).

    Supported values: '7d', '30d', '90d', '365d'. Defaults to 7d.
    """
    end = datetime.now(timezone.utc)

    days_map = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}
    days = days_map.get(range_str, 7)

    start = end - timedelta(days=days)
    return start, end


def parse_api_window(
    start_date: Optional[str], end_date: Optional[str]
) -> Tuple[datetime, datetime]:
    """Parse the start_date/end_date query parameters of the analytics API.

    A bare date (YYYY-MM-DD) as end_date means the end of that day, so the
    whole day is inside the range. Anything carrying a time is taken as given.
    Defaults: the end is now, the start is 30 days before the end. Raises
    ValueError on input that is not ISO 8601.
    """
    if end_date:
        end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        if _BARE_DATE.match(end_date):
            end = end + timedelta(days=1) - timedelta(microseconds=1)
    else:
        end = datetime.utcnow()

    if start_date:
        start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
    else:
        start = end - timedelta(days=30)
    return start, end
