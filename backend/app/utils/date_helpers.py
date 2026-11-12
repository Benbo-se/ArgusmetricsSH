"""Date ranges, and what a day is for a website.

Timestamps are stored in UTC and stay that way. A website has a time zone
(websites.timezone, an IANA name, UTC unless someone chose otherwise), and a
"day" in anything that groups or bounds by day is a day in that zone. For a
Swedish site that moves midnight from 01:00 or 02:00 local time to 00:00.

Days are not 24 hours. The day the clocks go forward has 23 and the day they
go back has 25, so a day's bounds are always worked out from the calendar
date in the zone (day_bounds), never by adding 24 hours to the day before.
"""
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import re
from typing import Optional, Tuple
from zoneinfo import ZoneInfo, available_timezones

from sqlalchemy import func

_BARE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULT_TIMEZONE = "UTC"


@lru_cache(maxsize=1)
def _known_zones() -> frozenset:
    # available_timezones() walks the zone directory on every call, and
    # site_timezone runs on every dashboard request. "localtime" is whatever
    # zone the server happens to be in: it is not a place, and Postgres does
    # not know the name.
    return frozenset(available_timezones() - {"localtime"})


def is_valid_timezone(name) -> bool:
    """Whether `name` is an IANA zone this installation knows."""
    return isinstance(name, str) and name in _known_zones()


def timezone_choices() -> list:
    """Every zone the settings page offers, UTC first."""
    return [DEFAULT_TIMEZONE] + sorted(_known_zones() - {DEFAULT_TIMEZONE})


def site_timezone(website) -> str:
    """The zone a website counts its days in.

    Falls back to UTC for a name that is not a zone. Saving validates the
    name, so this is for a row edited by hand: a dashboard in the wrong zone
    is better than one that answers 500 to everything.
    """
    name = getattr(website, "timezone", None)
    return name if is_valid_timezone(name) else DEFAULT_TIMEZONE


def as_utc(moment: datetime) -> datetime:
    """An aware UTC datetime. A naive one is taken to be UTC already, which
    is how the database reads it."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def local_date(moment: datetime, tz: str = DEFAULT_TIMEZONE) -> date:
    """The calendar date `moment` falls on in the zone."""
    return as_utc(moment).astimezone(ZoneInfo(tz)).date()


def day_start(day: date, tz: str = DEFAULT_TIMEZONE) -> datetime:
    """The first instant of a calendar date in the zone, in UTC.

    Where midnight does not exist (zones that put the clock forward at 00:00)
    this is the first instant that does, because a wall time inside the gap
    is read with the offset from before it.
    """
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


def day_bounds(day: date, tz: str = DEFAULT_TIMEZONE) -> Tuple[datetime, datetime]:
    """Start of a calendar date in the zone and start of the next, in UTC.

    The end is exclusive. 23, 24 or 25 hours apart depending on the day.
    """
    return day_start(day, tz), day_start(day + timedelta(days=1), tz)


def sql_local_day(column, tz: str = DEFAULT_TIMEZONE):
    """SQL for the calendar date of a timestamptz column in the zone.

    timezone(zone, timestamptz) gives the wall-clock time there, and date()
    cuts it to the day. With UTC this is what date(column) gave on a server
    whose session zone is UTC, without depending on the session.
    """
    return func.date(func.timezone(tz, column))


def parse_date_range(range_str: str) -> Tuple[datetime, datetime]:
    """Parse a date range string into start and end datetimes (UTC).

    Supported values: '7d', '30d', '90d', '365d'. Defaults to 7d.
    """
    end = datetime.now(timezone.utc)

    days_map = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}
    days = days_map.get(range_str, 7)

    start = end - timedelta(days=days)
    return start, end


def _in_zone(moment: datetime, tz: str) -> datetime:
    """Read a datetime that came without an offset as wall time in the zone.

    UTC is left exactly as it was, naive: that is what this function returned
    before websites had a zone, and the database reads it as UTC.
    """
    if moment.tzinfo is not None or tz == DEFAULT_TIMEZONE:
        return moment
    return moment.replace(tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


def parse_api_window(
    start_date: Optional[str], end_date: Optional[str], tz: str = DEFAULT_TIMEZONE
) -> Tuple[datetime, datetime]:
    """Parse the start_date/end_date query parameters of the analytics API.

    A bare date (YYYY-MM-DD) is a day in the website's zone: as start_date it
    is that day's first instant, as end_date its last, so the whole day is
    inside the range. A time without an offset is wall time in the zone; one
    with an offset is taken as given. Defaults: the end is now, the start is
    30 days before the end. Raises ValueError on input that is not ISO 8601.
    """
    if end_date:
        end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        if _BARE_DATE.match(end_date):
            # The next day's start in the zone, less a microsecond. Not this
            # day's start plus 24 hours: the day may have 23 or 25.
            end = _in_zone(end + timedelta(days=1), tz) - timedelta(microseconds=1)
        else:
            end = _in_zone(end, tz)
    else:
        end = datetime.utcnow()

    if start_date:
        start = _in_zone(datetime.fromisoformat(start_date.replace('Z', '+00:00')), tz)
    else:
        start = end - timedelta(days=30)
    return start, end
