"""Date ranges, and what a day is for a website.

Timestamps are stored in UTC and stay that way. A website has a time zone
(websites.timezone, an IANA name, UTC unless someone chose otherwise), and a
"day" in anything that groups or bounds by day is a day in that zone. For a
Swedish site that moves midnight from 01:00 or 02:00 local time to 00:00.

Days are not 24 hours. The day the clocks go forward has 23 and the day they
go back has 25, so a day's bounds are always worked out from the calendar
date in the zone (day_bounds), never by adding 24 hours to the day before.
"""
from dataclasses import dataclass
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


def sql_local_hour(column, tz: str = DEFAULT_TIMEZONE):
    """SQL for the instant the clock hour containing a timestamptz began, in
    the zone.

    The wall-clock time less its minutes and seconds, taken off the instant
    itself. An instant comes back rather than a wall-clock hour, because on
    the day the clocks go back the hour from 02:00 to 03:00 happens twice and
    the two must stay two points. It also follows zones that sit half an hour
    off UTC, where an hour does not start on a UTC hour.
    """
    wall = func.timezone(tz, column)
    return column - (wall - func.date_trunc('hour', wall))


def hour_start(moment: datetime, tz: str = DEFAULT_TIMEZONE) -> datetime:
    """The same thing in Python: when the clock hour containing `moment`
    began in the zone, as a UTC instant."""
    moment = as_utc(moment)
    wall = moment.astimezone(ZoneInfo(tz))
    return moment - timedelta(
        minutes=wall.minute, seconds=wall.second, microseconds=wall.microsecond
    )


def _wall_shift(moment: datetime, tz: str, *, days: int = 0, years: int = 0) -> datetime:
    """The same wall-clock time `days` and `years` earlier in the zone.

    Not a subtraction of hours: a week before 14:30 is 14:30, also when the
    clocks changed in between. 29 February a year earlier is 28 February.
    """
    wall = as_utc(moment).astimezone(ZoneInfo(tz)).replace(tzinfo=None)
    wall -= timedelta(days=days)
    if years:
        try:
            wall = wall.replace(year=wall.year - years)
        except ValueError:
            wall = wall.replace(year=wall.year - years, day=28)
    return wall.replace(tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


def _year_before(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


#: The rolling ranges: the last N times 24 hours, ending now.
ROLLING_DAYS = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}

#: The calendar ranges: whole days in the website's zone.
RANGE_LABELS = {
    "today": "Today",
    "yesterday": "Yesterday",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
    "90d": "Last 90 days",
    "mtd": "Month to date",
    "last_month": "Last month",
    "ytd": "Year to date",
    "365d": "Last 12 months",
}

#: A calendar range this many days long or shorter is drawn by the hour.
HOURLY_MAX_DAYS = 2

#: The longest custom range. The time series holds a point per day whether or
#: not anything happened on it, so the range needs an upper bound.
MAX_CUSTOM_DAYS = 732

COMPARE_PREVIOUS = "previous"
COMPARE_YEAR = "year"


def compare_mode(value) -> Optional[str]:
    """What ?compare= asks for: None, COMPARE_PREVIOUS or COMPARE_YEAR.

    'true' is what the checkbox sent before there was a second kind of
    comparison, and bookmarks still carry it.
    """
    text = str(value or "").strip().lower()
    if text == COMPARE_YEAR:
        return COMPARE_YEAR
    if text in (COMPARE_PREVIOUS, "true", "1", "on", "yes"):
        return COMPARE_PREVIOUS
    return None


def _day_label(day: date, with_year: bool = True) -> str:
    text = f"{day.strftime('%b')} {day.day}"
    return f"{text}, {day.year}" if with_year else text


@dataclass(frozen=True)
class DateWindow:
    """A range chosen on the dashboard, resolved to two instants.

    `start` and `end` are UTC and both inclusive, which is how every query
    here bounds its rows. A calendar range also knows its first and last day
    in the website's zone; a rolling one has neither, because it starts at
    whatever time it is now.
    """

    key: str
    start: datetime
    end: datetime
    tz: str
    first_day: Optional[date] = None
    last_day: Optional[date] = None

    @property
    def is_calendar(self) -> bool:
        return self.first_day is not None

    @property
    def bucket(self) -> str:
        """'hour' for a day or two, 'day' for anything longer."""
        if self.is_calendar and (self.last_day - self.first_day).days < HOURLY_MAX_DAYS:
            return "hour"
        return "day"

    @property
    def label(self) -> str:
        if self.key != "custom":
            return RANGE_LABELS[self.key]
        if self.first_day == self.last_day:
            return _day_label(self.first_day)
        same_year = self.first_day.year == self.last_day.year
        return f"{_day_label(self.first_day, not same_year)} to {_day_label(self.last_day)}"

    @property
    def params(self) -> dict:
        """The query parameters that ask for this range again."""
        if self.key != "custom":
            return {"range": self.key}
        return {
            "range": "custom",
            "start_date": self.first_day.isoformat(),
            "end_date": self.last_day.isoformat(),
        }

    def previous(self, mode: str = COMPARE_PREVIOUS) -> Tuple[datetime, datetime]:
        """The range this one is compared against.

        COMPARE_YEAR is the same dates and times of day one year earlier.

        COMPARE_PREVIOUS is the period just before, of the same length. For a
        rolling range that is a length in seconds, as it always was. For a
        calendar range it is the same number of days, and when the range is
        still running (today, month to date) it stops at the same time of day
        as now, so that a morning is compared with a morning and not with a
        whole day.
        """
        if mode == COMPARE_YEAR:
            if self.is_calendar:
                start = day_start(_year_before(self.first_day), self.tz)
            else:
                start = _wall_shift(self.start, self.tz, years=1)
            return start, _wall_shift(self.end, self.tz, years=1)

        if not self.is_calendar:
            prev_end = self.start - timedelta(seconds=1)
            return prev_end - (self.end - self.start), prev_end

        days = (self.last_day - self.first_day).days + 1
        prev_start = day_start(self.first_day - timedelta(days=days), self.tz)
        return prev_start, _wall_shift(self.end, self.tz, days=days)


def _parse_day(text) -> Optional[date]:
    if not isinstance(text, str) or not _BARE_DATE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def resolve_range(
    range_str: Optional[str],
    tz: str = DEFAULT_TIMEZONE,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    now: Optional[datetime] = None,
) -> DateWindow:
    """Turn ?range= (and, for a custom range, ?start_date= and ?end_date=)
    into a DateWindow.

    The rolling ranges (7d, 30d, 90d, 365d) are the last N times 24 hours and
    do not depend on the zone. The calendar ranges (today, yesterday, mtd,
    last_month, ytd, custom) are whole days in the website's zone; one that
    includes today ends now.

    Anything not understood is the last seven days, as it always was. A
    custom range with its dates the wrong way round is read the right way
    round, one that reaches into the future stops today, and one longer than
    MAX_CUSTOM_DAYS keeps its end and loses its beginning.
    """
    now = as_utc(now or datetime.now(timezone.utc))
    today = local_date(now, tz)

    first = last = None
    key = range_str
    if key == "today":
        first = last = today
    elif key == "yesterday":
        first = last = today - timedelta(days=1)
    elif key == "mtd":
        first, last = today.replace(day=1), today
    elif key == "last_month":
        last = today.replace(day=1) - timedelta(days=1)
        first = last.replace(day=1)
    elif key == "ytd":
        first, last = today.replace(month=1, day=1), today
    elif key == "custom":
        first, last = _parse_day(start_date), _parse_day(end_date)
        if first is None or last is None:
            first = last = None
        else:
            if first > last:
                first, last = last, first
            last = min(last, today)
            first = min(first, last)
            first = max(first, last - timedelta(days=MAX_CUSTOM_DAYS - 1))

    if first is None:
        key = key if key in ROLLING_DAYS else "7d"
        return DateWindow(
            key=key, start=now - timedelta(days=ROLLING_DAYS[key]), end=now, tz=tz
        )

    end_of_last = day_start(last + timedelta(days=1), tz) - timedelta(microseconds=1)
    return DateWindow(
        key=key,
        start=day_start(first, tz),
        end=min(end_of_last, now),
        tz=tz,
        first_day=first,
        last_day=last,
    )


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
    # One of the two may carry an offset and the other not (a naive value is
    # UTC here), so they are compared as instants, and the start keeps the
    # form it came in.
    def instant(moment: datetime) -> datetime:
        return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)

    if instant(start) > instant(end):
        raise ValueError("start_date is after end_date")
    # The same ceiling as a custom range on the dashboard, and applied the
    # same way: the range keeps its end and loses its beginning. Nothing is
    # kept longer than that, and a series is built one point per day.
    # The ceiling is measured back from the last moment that can hold data.
    # "Everything up to 2099" is a common way to ask for everything, and it
    # should get the most recent stretch, not two empty years of the future.
    latest = min(instant(end), datetime.now(timezone.utc))
    floor = latest - timedelta(days=MAX_CUSTOM_DAYS)
    if instant(start) < floor:
        start = floor if start.tzinfo is not None else floor.astimezone(timezone.utc).replace(tzinfo=None)
    return start, end
