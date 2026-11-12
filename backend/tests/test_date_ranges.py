"""Choosing a range: the calendar presets, a custom range, hours, last year.

The dashboard had four ranges, each "the last N times 24 hours". These pin
down what was added beside them:

* today, yesterday, month to date, last month, year to date and a custom
  range, all whole days in the website's time zone;
* a time series by the hour when the range is a day or two;
* a comparison with the same period a year earlier, beside the comparison
  with the period just before.

Rows are placed at exact instants and "now" is passed in wherever the code
lets it be, so the clock the suite runs on decides nothing. The days the
clocks change (29 March and 25 October 2026 in Stockholm) are used on purpose.

Few functions with many assertions each, on purpose: the README and the home
page state how many tests there are and CI holds them to it, so a case that
is one more line of the same table is written as a line, not as a test.
"""
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.analytics_query_service import AnalyticsQueryService
from app.utils.date_helpers import (
    MAX_CUSTOM_DAYS, compare_mode, day_start, hour_start, local_date, resolve_range,
)

STOCKHOLM = "Europe/Stockholm"
# 14:30 on Thursday 12 November 2026 in Stockholm (CET, UTC+1).
NOW = datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc)
US = timedelta(microseconds=1)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def put(db, website_id, visitor, when, path="/"):
    db.execute(
        text(
            'INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp", '
            "  browser, device_type) "
            "VALUES (:w, :p, :h, :t, 'Chrome', 'desktop')"
        ),
        {"w": website_id, "p": path, "h": visitor, "t": when},
    )


def set_zone(db, website_id, zone):
    db.execute(
        text("UPDATE websites SET timezone = :z WHERE id = :w"),
        {"z": zone, "w": website_id},
    )
    db.commit()
    db.expire_all()


def window(key, tz=STOCKHOLM, start=None, end=None, now=NOW):
    return resolve_range(key, tz, start, end, now=now)


# ------------------------------------------------------------------ the ranges


def test_calendar_presets_are_whole_days_in_the_zone():
    # Today starts at local midnight and ends now.
    w = window("today")
    assert (w.start, w.end) == (utc(2026, 11, 11, 23, 0), NOW)
    assert (w.first_day, w.last_day) == (date(2026, 11, 12), date(2026, 11, 12))
    w = window("today", tz="UTC")
    assert (w.start, w.end) == (utc(2026, 11, 12, 0, 0), NOW)

    # 00:30 on 11 June in Stockholm is 22:30 on the 10th in UTC.
    late = utc(2026, 6, 10, 22, 30)
    assert window("today", now=late).first_day == date(2026, 6, 11)
    assert window("today", tz="UTC", now=late).first_day == date(2026, 6, 10)
    assert window("yesterday", now=late).first_day == date(2026, 6, 10)

    # Yesterday is the whole day.
    w = window("yesterday")
    assert (w.start, w.end) == (utc(2026, 11, 10, 23, 0), utc(2026, 11, 11, 23, 0) - US)

    w = window("mtd")
    assert (w.start, w.end) == (utc(2026, 10, 31, 23, 0), NOW)
    assert (w.first_day, w.last_day) == (date(2026, 11, 1), date(2026, 11, 12))

    # Last month is the calendar month. October 2026 starts in summer time
    # and ends in winter time, so it is an hour longer than 31 days.
    w = window("last_month")
    assert (w.first_day, w.last_day) == (date(2026, 10, 1), date(2026, 10, 31))
    assert w.start == utc(2026, 9, 30, 22, 0)              # 00:00 CEST
    assert w.end == utc(2026, 10, 31, 23, 0) - US          # 24:00 CET
    assert w.end - w.start == timedelta(days=31, hours=1) - US
    w = window("last_month", now=utc(2027, 1, 15, 12, 0))
    assert (w.first_day, w.last_day) == (date(2026, 12, 1), date(2026, 12, 31))

    w = window("ytd")
    assert (w.start, w.end) == (utc(2025, 12, 31, 23, 0), NOW)
    assert w.first_day == date(2026, 1, 1)


def test_rolling_ranges_are_what_they_were():
    """The last N times 24 hours, whatever the zone, and seven days for
    anything not understood."""
    for key, days in (("7d", 7), ("30d", 30), ("90d", 90), ("365d", 365)):
        for tz in ("UTC", STOCKHOLM):
            w = window(key, tz=tz)
            assert (w.start, w.end) == (NOW - timedelta(days=days), NOW), (key, tz)
            assert w.first_day is None and w.bucket == "day" and w.key == key
    for junk in (None, "", "14d", "custom", "TODAY", "'; --"):
        w = window(junk)
        assert (w.key, w.start, w.end) == ("7d", NOW - timedelta(days=7), NOW), junk


def test_custom_range_labels_and_bucket():
    w = window("custom", start="2026-06-01", end="2026-06-10")
    assert (w.start, w.end) == (utc(2026, 5, 31, 22, 0), utc(2026, 6, 10, 22, 0) - US)
    assert w.params == {"range": "custom", "start_date": "2026-06-01", "end_date": "2026-06-10"}

    # Dates the wrong way round are read the right way round.
    w = window("custom", start="2026-06-10", end="2026-06-01")
    assert (w.first_day, w.last_day) == (date(2026, 6, 1), date(2026, 6, 10))

    # A range into the future stops now.
    w = window("custom", start="2026-11-10", end="2027-01-01")
    assert (w.first_day, w.last_day, w.end) == (date(2026, 11, 10), date(2026, 11, 12), NOW)
    w = window("custom", start="2027-01-01", end="2027-02-01")
    assert (w.first_day, w.last_day) == (date(2026, 11, 12), date(2026, 11, 12))

    # Dates that are not dates fall back to seven days.
    for start, end in (
        (None, None), ("2026-06-01", None), (None, "2026-06-01"),
        ("2026-13-01", "2026-06-01"), ("2026-06-01T10:00", "2026-06-02"), ("junk", "junk"),
    ):
        assert window("custom", start=start, end=end).key == "7d", (start, end)

    # A very long range keeps its end and loses its beginning.
    w = window("custom", start="0001-01-01", end="2026-06-10")
    assert w.last_day == date(2026, 6, 10)
    assert (w.last_day - w.first_day).days + 1 == MAX_CUSTOM_DAYS

    # What the button says.
    assert window("today").label == "Today"
    assert window("mtd").label == "Month to date"
    assert window("365d").label == "Last 12 months"
    assert window("custom", start="2026-06-10", end="2026-06-10").label == "Jun 10, 2026"
    assert window("custom", start="2026-06-01", end="2026-06-10").label == "Jun 1 to Jun 10, 2026"
    assert window("custom", start="2025-12-30", end="2026-01-02").label == "Dec 30, 2025 to Jan 2, 2026"

    # A day or two is drawn by the hour, anything longer by the day.
    assert window("today").bucket == "hour"
    assert window("yesterday").bucket == "hour"
    assert window("custom", start="2026-06-09", end="2026-06-10").bucket == "hour"
    assert window("custom", start="2026-06-08", end="2026-06-10").bucket == "day"
    assert window("mtd").bucket == "day"
    # Month to date on the first of the month is one day long.
    assert window("mtd", now=utc(2026, 11, 1, 12, 0)).bucket == "hour"

    # 16:17 in India is 10:47 UTC, and that hour began at 10:30 UTC.
    assert hour_start(utc(2026, 6, 10, 10, 47), "Asia/Kolkata") == utc(2026, 6, 10, 10, 30)
    assert hour_start(utc(2026, 6, 10, 10, 47), STOCKHOLM) == utc(2026, 6, 10, 10, 0)
    assert hour_start(datetime(2026, 6, 10, 10, 47)) == utc(2026, 6, 10, 10, 0)


# ------------------------------------------------------------ what to compare


def test_the_previous_period():
    # A rolling range: what the service always computed.
    w = window("7d")
    prev_end = w.start - timedelta(seconds=1)
    assert w.previous() == (prev_end - (w.end - w.start), prev_end)

    # Today so far against yesterday so far.
    assert window("today").previous() == (utc(2026, 11, 10, 23, 0), utc(2026, 11, 11, 13, 30))

    # A finished day against the whole day before.
    assert window("yesterday").previous() == (
        utc(2026, 11, 9, 23, 0), utc(2026, 11, 10, 23, 0) - US
    )

    # The day before was 25 hours, and all of it counts.
    w = window("custom", start="2026-10-26", end="2026-10-26")
    assert w.end - w.start == timedelta(hours=24) - US
    assert w.previous() == (utc(2026, 10, 24, 22, 0), utc(2026, 10, 25, 23, 0) - US)

    # The day before was 23 hours, and the two do not overlap.
    w = window("custom", start="2026-03-30", end="2026-03-30")
    start, end = w.previous()
    assert (start, end) == (utc(2026, 3, 28, 23, 0), utc(2026, 3, 29, 22, 0) - US)
    assert end < w.start

    # The same time of day across a clock change: 15:00 on the 25 hour day,
    # and the day before 15:00 was an hour earlier in UTC.
    w = window("today", now=utc(2026, 10, 25, 14, 0))
    assert w.previous() == (utc(2026, 10, 23, 22, 0), utc(2026, 10, 24, 13, 0))

    # Month to date: twelve days so far, so the twelve before, 20 October to
    # the 31st at 14:30.
    assert window("mtd").previous() == (utc(2026, 10, 19, 22, 0), utc(2026, 10, 31, 13, 30))


def test_the_same_period_last_year():
    assert window("today").previous("year") == (
        utc(2025, 11, 11, 23, 0), utc(2025, 11, 12, 13, 30)
    )
    # A month keeps its dates.
    assert window("last_month").previous("year") == (
        utc(2025, 9, 30, 22, 0), utc(2025, 10, 31, 23, 0) - US
    )
    # The same wall-clock time when the offset differs: 29 March 2026 12:00
    # is summer time, 29 March 2025 was still winter time.
    w = window("today", now=utc(2026, 3, 29, 10, 0))
    assert w.previous("year") == (utc(2025, 3, 28, 23, 0), utc(2025, 3, 29, 11, 0))

    # Leap day is compared with 28 February.
    late = utc(2028, 6, 1, 12, 0)
    w = window("custom", start="2028-02-29", end="2028-02-29", now=late)
    assert w.previous("year") == (utc(2027, 2, 27, 23, 0), utc(2027, 2, 28, 23, 0) - US)
    w = window("custom", start="2028-02-01", end="2028-02-29", now=late)
    assert w.previous("year") == (utc(2027, 1, 31, 23, 0), utc(2027, 2, 28, 23, 0) - US)

    # A rolling range moves back a year.
    w = window("30d", tz="UTC")
    assert w.previous("year") == (w.start.replace(year=2025), w.end.replace(year=2025))

    # What ?compare= means. 'true' is what the old checkbox sent.
    assert compare_mode("year") == "year"
    for old in ("true", "True", "1", "on", "previous"):
        assert compare_mode(old) == "previous", old
    for off in (None, "", "false", "0", "no", "junk", False):
        assert compare_mode(off) is None, off


# ---------------------------------------------------------- the hourly series


def hourly(db, website_id, w, **kwargs):
    stats = AnalyticsQueryService(db).get_dashboard_stats(
        website_id=website_id, start_date=w.start, end_date=w.end,
        tz=w.tz, bucket=w.bucket, **kwargs
    )
    return stats["timeseries"], stats


def test_an_hourly_day_is_24_points_in_local_hours(db, website):
    wid = website["id"]
    put(db, wid, "before", utc(2026, 11, 10, 22, 59))   # 23:59 the day before
    put(db, wid, "a", utc(2026, 11, 10, 23, 0))         # 00:00
    put(db, wid, "a", utc(2026, 11, 10, 23, 59))        # 00:59, same visitor
    put(db, wid, "b", utc(2026, 11, 11, 13, 5))         # 14:05
    put(db, wid, "c", utc(2026, 11, 11, 22, 59))        # 23:59
    put(db, wid, "after", utc(2026, 11, 11, 23, 0))     # 00:00 the day after
    db.commit()

    points, stats = hourly(db, wid, window("yesterday"))
    assert stats["timeseries_bucket"] == "hour"
    assert len(points) == 24
    assert points[0] == {"date": "2026-11-11T00:00+01:00", "views": 2, "visitors": 1}
    assert points[14] == {"date": "2026-11-11T14:00+01:00", "views": 1, "visitors": 1}
    assert points[23] == {"date": "2026-11-11T23:00+01:00", "views": 1, "visitors": 1}
    assert sum(p["views"] for p in points) == stats["total_pageviews"] == 4

    # The same rows for a site in UTC: UTC hours, and a different day.
    points, _ = hourly(db, wid, window("yesterday", tz="UTC"))
    assert len(points) == 24
    assert [(p["date"], p["views"]) for p in points if p["views"]] == [
        ("2026-11-11T13:00+00:00", 1), ("2026-11-11T22:00+00:00", 1), ("2026-11-11T23:00+00:00", 1),
    ]

    # Today stops at the current hour; two days are hourly too; three are not.
    points, _ = hourly(db, wid, window("today"))
    assert len(points) == 15 and points[-1]["date"][11:16] == "14:00"
    points, _ = hourly(db, wid, window("custom", start="2026-06-09", end="2026-06-10"))
    assert len(points) == 48 and points[24]["date"] == "2026-06-10T00:00+02:00"
    points, stats = hourly(db, wid, window("custom", start="2026-06-08", end="2026-06-10"))
    assert stats["timeseries_bucket"] == "day"
    assert [p["date"] for p in points] == ["2026-06-08", "2026-06-09", "2026-06-10"]


def test_hours_when_the_clocks_change_and_in_a_half_hour_zone(db, website):
    wid = website["id"]
    put(db, wid, "a", utc(2026, 10, 25, 0, 30))    # 02:30 summer time
    put(db, wid, "b", utc(2026, 10, 25, 1, 30))    # 02:30 winter time
    put(db, wid, "c", utc(2026, 10, 25, 1, 45))    # 02:45 winter time
    put(db, wid, "d", utc(2026, 3, 29, 0, 30))     # 01:30 winter time
    put(db, wid, "e", utc(2026, 3, 29, 1, 30))     # 03:30 summer time
    db.commit()

    # Back: 25 points, and 02:00 twice, each with its own visitors.
    points, stats = hourly(db, wid, window("custom", start="2026-10-25", end="2026-10-25"))
    assert len(points) == 25
    assert [p for p in points if "T02:00" in p["date"]] == [
        {"date": "2026-10-25T02:00+02:00", "views": 1, "visitors": 1},
        {"date": "2026-10-25T02:00+01:00", "views": 2, "visitors": 2},
    ]
    assert sum(p["views"] for p in points) == stats["total_pageviews"] == 3

    # Forward: 23 points, and no 02:00 at all.
    points, _ = hourly(db, wid, window("custom", start="2026-03-29", end="2026-03-29"))
    assert len(points) == 23
    assert [p["date"][11:16] for p in points[:4]] == ["00:00", "01:00", "03:00", "04:00"]
    assert [p["date"] for p in points if p["views"]] == [
        "2026-03-29T01:00+01:00", "2026-03-29T03:00+02:00",
    ]

    # A zone half an hour off UTC gets its own hours.
    put(db, wid, "a", utc(2026, 6, 10, 10, 20))    # 15:50 in India
    put(db, wid, "b", utc(2026, 6, 10, 10, 47))    # 16:17 in India
    db.commit()
    w = window("custom", tz="Asia/Kolkata", start="2026-06-10", end="2026-06-10")
    points, _ = hourly(db, wid, w)
    assert len(points) == 24
    assert [p["date"] for p in points if p["views"]] == [
        "2026-06-10T15:00+05:30", "2026-06-10T16:00+05:30",
    ]


# ------------------------------------------------------- comparing, in the app


@pytest.fixture
def three_days(db, website):
    """10 June 2026 in Stockholm with two pageviews, the day before with
    four, and the same date a year earlier with one."""
    wid = website["id"]
    set_zone(db, wid, STOCKHOLM)
    for hour in (8, 20):
        put(db, wid, f"now-{hour}", utc(2026, 6, 10, hour, 0))
    for hour in (1, 8, 14, 20):
        put(db, wid, f"prev-{hour}", utc(2026, 6, 9, hour, 0))
    put(db, wid, "year", utc(2025, 6, 10, 9, 0))
    # Either side of the days above, to be left out of all three.
    put(db, wid, "x", utc(2026, 6, 10, 22, 30))    # 00:30 on the 11th
    put(db, wid, "y", utc(2025, 6, 9, 21, 30))     # 23:30 on 9 June 2025
    db.commit()
    return wid


DAY = "range=custom&start_date=2026-06-10&end_date=2026-06-10"


def tile(html, label):
    """The value and the change shown on one headline tile."""
    block = html.split(f">{label}</p>", 1)[1].split("stat-tile", 1)[0]
    value = re.search(r'stat-value[^>]*>\s*([^<\s]+)', block).group(1)
    change = re.search(r'stat-delta[^>]*title="([^"]*)"[^>]*>\s*(\S)\s*([\d.]+)%', block)
    return value, (change.groups() if change else None)


def test_the_dashboard_against_either_comparison(owner_client, three_days):
    def pageviews(compare=""):
        html = owner_client.get(
            f"/dashboard/website/{three_days}/stats-basic?{DAY}{compare}"
        ).text
        return tile(html, "Total Pageviews")

    assert pageviews() == ("2", None)
    for flag in ("previous", "true"):
        assert pageviews(f"&compare={flag}") == (
            "2", ("Compared with the previous period of the same length", "▼", "50.0")
        ), flag
    assert pageviews("&compare=year") == (
        "2", ("Compared with the same period last year", "▲", "100.0")
    )

    # The page itself draws the comparison that was asked for.
    page = owner_client.get(f"/dashboard/website/{three_days}?{DAY}&compare=year")
    assert page.status_code == 200
    body = page.text
    # This day, hourly, in local time.
    assert re.search(r'"date":\s*"2026-06-10T10:00\+02:00",\s*"views":\s*1\b', body)
    # Last year's line: 09:00 UTC was 11:00 in Stockholm.
    assert re.search(r'"date":\s*"2025-06-10T11:00\+02:00",\s*"views":\s*1\b', body)
    assert 'bucket: "hour"' in body
    assert 'compareLabel: "Last year"' in body
    # The label, the selected comparison, and the dates carried onwards.
    assert '"range_label": "Jun 10, 2026"' in body
    assert '<option value="year" selected>' in body
    carried = "range=custom&amp;start_date=2026-06-10&amp;end_date=2026-06-10"
    assert f"stats-basic?{carried}&compare=year" in body
    assert f"export-csv?{carried}" in body

    body = owner_client.get(f"/dashboard/website/{three_days}?{DAY}&compare=previous").text
    assert re.search(r'"date":\s*"2026-06-09T03:00\+02:00",\s*"views":\s*1\b', body)
    assert "2025-06-10T" not in body
    assert 'compareLabel: "Previous period"' in body
    assert '<option value="previous" selected>' in body

    body = owner_client.get(f"/dashboard/website/{three_days}?{DAY}").text
    assert '<option value="" selected>' in body
    assert "2026-06-09T" not in body and "2025-06-10T" not in body

    # The export covers the custom range.
    csv = owner_client.get(f"/dashboard/website/{three_days}/export-csv?{DAY}").text
    assert "Date Range:,2026-06-10 to 2026-06-10" in csv
    assert "Total Pageviews,2" in csv


def test_today_on_the_dashboard_is_the_sites_today(owner_client, db, website):
    wid = website["id"]
    now = datetime.now(timezone.utc)
    # A zone whose date differs from the UTC date right now (see
    # test_site_timezone), so a "today" counted in UTC gives another number.
    zone = next(
        z for z in ("Pacific/Kiritimati", "Etc/GMT+12")
        if local_date(now, z) != now.date()
    )
    set_zone(db, wid, zone)
    midnight = day_start(local_date(now, zone), zone)
    put(db, wid, "today", midnight + timedelta(seconds=1))
    put(db, wid, "yesterday", midnight - timedelta(seconds=1))
    db.commit()

    def pageviews(key):
        html = owner_client.get(f"/dashboard/website/{wid}/stats-basic?range={key}").text
        return tile(html, "Total Pageviews")[0]

    assert pageviews("today") == "1"
    assert pageviews("yesterday") == "1"
    assert pageviews("7d") == "2"


def test_every_page_that_takes_a_range_takes_the_new_ones(
    owner_client, client, db, three_days, shared_website
):
    for key, label in (
        ("today", "Today"), ("yesterday", "Yesterday"), ("mtd", "Month to date"),
        ("last_month", "Last month"), ("ytd", "Year to date"), ("30d", "Last 30 days"),
    ):
        page = owner_client.get(f"/dashboard/website/{three_days}?range={key}")
        assert page.status_code == 200, key
        assert f'"range_label": "{label}"' in page.text, key
        assert f'data-value="{key}"' in page.text, key

    # The public dashboard: the presets, without the date fields.
    page = client.get(f"/public/{shared_website['share_token']}?range=today")
    assert page.status_code == 200
    assert 'data-label="Today"' in page.text
    assert 'bucket: "hour"' in page.text
    assert 'href="?range=last_month"' in page.text

    # An event's own page.
    db.execute(
        text(
            "INSERT INTO custom_events (website_id, event_name, visitor_hash, timestamp) "
            "VALUES (:w, 'signup', 'v', :t)"
        ),
        {"w": three_days, "t": utc(2026, 6, 10, 9, 0)},
    )
    db.commit()
    page = owner_client.get(f"/dashboard/website/{three_days}/events/signup?{DAY}")
    assert page.status_code == 200
    assert "Jun 10, 2026" in page.text


# ----------------------------------------------------------------- the JSON API


def test_the_api_cuts_a_range_into_hours_when_asked(owner_client, three_days):
    day = f"/api/v1/analytics/stats/{three_days}?start_date=2026-06-10&end_date=2026-06-10"
    r = owner_client.get(day + "&interval=hour")
    assert r.status_code == 200, r.text
    series = r.json()["timeseries"]
    assert len(series) == 24
    assert [p["date"] for p in series if p["views"]] == [
        "2026-06-10T10:00+02:00", "2026-06-10T22:00+02:00",
    ]

    # By the day is the default, and what it was.
    for url in (day, day + "&interval=day"):
        assert owner_client.get(url).json()["timeseries"] == [{"date": "2026-06-10", "views": 2}]

    r = owner_client.get(f"/api/v1/analytics/stats/{three_days}?interval=minute")
    assert r.status_code == 400 and "interval" in r.text

    # A month with a clock change in it fits; two months do not.
    base = f"/api/v1/analytics/stats/{three_days}?interval=hour"
    month = owner_client.get(base + "&start_date=2026-10-01&end_date=2026-10-31")
    assert month.status_code == 200, month.text
    assert len(month.json()["timeseries"]) == 31 * 24 + 1
    longer = owner_client.get(base + "&start_date=2026-09-01&end_date=2026-10-31")
    assert longer.status_code == 400 and "31 days" in longer.text
