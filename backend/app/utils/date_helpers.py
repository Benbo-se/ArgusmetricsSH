"""Date range parsing utility."""
from datetime import datetime, timedelta, timezone
from typing import Tuple


def parse_date_range(range_str: str) -> Tuple[datetime, datetime]:
    """Parse a date range string into start and end datetimes (UTC).

    Supported values: '7d', '30d', '90d', '365d'. Defaults to 7d.
    """
    end = datetime.now(timezone.utc)

    days_map = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}
    days = days_map.get(range_str, 7)

    start = end - timedelta(days=days)
    return start, end
