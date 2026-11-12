"""A day is a day in the website's time zone.

Everything used to be counted in UTC, so a Swedish site's day started at 01:00
or 02:00. A website now has a zone, and every place that groups or bounds by
day uses it.

Three things are pinned down here, each against rows placed at exact instants:

* around midnight in Europe/Stockholm, where the local date and the UTC date
  disagree for an hour or two every night;
* the two days a year that are not 24 hours long. In 2026 the clocks go
  forward on 29 March (a 23 hour day) and back on 25 October (25 hours);
* the default. A website nobody has touched is in UTC and must count exactly
  as it did before the column existed.

Few functions with many assertions each, on purpose: the README and the home
page state how many tests there are and CI holds them to it, so a case that
is one more line of the same table is written as a line, not as a test.
"""
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from app.config import pin_psycopg2
from sqlalchemy import create_engine, text

from app.services.analytics_query_service import AnalyticsQueryService
from app.services.ecommerce_service import EcommerceService
from app.services.site_activity import goal_activity, recent_activity
from app.utils.date_helpers import (
    day_bounds, is_valid_timezone, local_date, parse_api_window, site_timezone,
)

STOCKHOLM = "Europe/Stockholm"
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
    # Written behind the ORM's back, and the test shares one session with the
    # app: without this a Website loaded by an earlier request stays as it was.
    db.expire_all()


def stored_zone(db, website_id):
    return db.execute(
        text("SELECT timezone FROM websites WHERE id = :w"), {"w": website_id}
    ).scalar()


def series(db, website_id, start, end, **kwargs):
    stats = AnalyticsQueryService(db).get_dashboard_stats(
        website_id=website_id, start_date=start, end_date=end, **kwargs
    )
    return [(p["date"], p["views"]) for p in stats["timeseries"]], stats


def a_zone_on_another_date(now):
    """A zone whose date differs from the UTC date at this moment, so a test
    against the real clock means the same thing whatever time the suite runs:
    UTC+14 is on tomorrow from 10:00 UTC, UTC-12 on yesterday until 12:00."""
    return next(
        z for z in ("Pacific/Kiritimati", "Etc/GMT+12")
        if local_date(now, z) != now.date()
    )


# ---------------------------------------------------------------- the helpers


def test_where_a_day_starts_and_ends():
    # An ordinary day is 24 hours from local midnight.
    start, end = day_bounds(date(2026, 6, 10), STOCKHOLM)
    assert start == utc(2026, 6, 9, 22, 0)        # 00:00 CEST
    assert end - start == timedelta(hours=24)

    # The day the clocks go forward is 23 hours.
    start, end = day_bounds(date(2026, 3, 29), STOCKHOLM)
    assert (start, end) == (utc(2026, 3, 28, 23, 0), utc(2026, 3, 29, 22, 0))
    assert end - start == timedelta(hours=23)

    # The day they go back is 25.
    start, end = day_bounds(date(2026, 10, 25), STOCKHOLM)
    assert (start, end) == (utc(2026, 10, 24, 22, 0), utc(2026, 10, 25, 23, 0))
    assert end - start == timedelta(hours=25)

    # UTC days are UTC days.
    for day in (date(2026, 3, 29), date(2026, 10, 25)):
        start, end = day_bounds(day)
        assert start == utc(day.year, day.month, day.day)
        assert end - start == timedelta(hours=24)

    # The date an instant falls on, around midnight.
    assert local_date(utc(2026, 6, 10, 21, 59), STOCKHOLM) == date(2026, 6, 10)
    assert local_date(utc(2026, 6, 10, 22, 0), STOCKHOLM) == date(2026, 6, 11)
    assert local_date(utc(2026, 6, 10, 22, 0)) == date(2026, 6, 10)
    # Naive is read as UTC, which is how the database reads it.
    assert local_date(datetime(2026, 6, 10, 22, 0), STOCKHOLM) == date(2026, 6, 11)

    # What is a zone and what is not.
    assert is_valid_timezone("UTC") and is_valid_timezone(STOCKHOLM)
    for bad in ("Mars/Phobos", "europe/stockholm", "localtime", "", None, 5):
        assert not is_valid_timezone(bad), bad

    # A row holding a name that is not a zone counts in UTC.
    class Row:
        timezone = "Mars/Phobos"
    assert site_timezone(Row()) == "UTC"
    assert site_timezone(object()) == "UTC"


def test_the_dates_the_api_takes():
    # UTC is exactly what it was before websites had a zone, naive and all.
    start, end = parse_api_window("2026-10-25", "2026-10-25")
    assert start == datetime(2026, 10, 25, 0, 0)
    assert end == datetime(2026, 10, 25, 23, 59, 59, 999999)
    assert start.tzinfo is None and end.tzinfo is None
    assert parse_api_window("2026-10-25", "2026-10-25", "UTC") == (start, end)

    # A bare date is a day in the zone.
    assert parse_api_window("2026-06-10", "2026-06-10", STOCKHOLM) == (
        utc(2026, 6, 9, 22, 0), utc(2026, 6, 10, 22, 0) - US
    )
    # The 25 hour day is whole.
    assert parse_api_window("2026-10-25", "2026-10-25", STOCKHOLM) == (
        utc(2026, 10, 24, 22, 0), utc(2026, 10, 25, 23, 0) - US
    )
    # The 23 hour day does not reach into the next.
    assert parse_api_window("2026-03-29", "2026-03-29", STOCKHOLM) == (
        utc(2026, 3, 28, 23, 0), utc(2026, 3, 29, 22, 0) - US
    )
    # An offset is taken as given, and a time without one is local.
    assert parse_api_window("2026-06-10T08:00:00Z", "2026-06-10T12:00:00", STOCKHOLM) == (
        utc(2026, 6, 10, 8, 0), utc(2026, 6, 10, 10, 0)       # 12:00 CEST
    )


# ------------------------------------------------------------ the time series


def test_the_time_series_around_midnight(db, website):
    """Two pageviews on either side of Stockholm's midnight, both on the same
    UTC date, and one the night before for the previous period."""
    w = website["id"]
    put(db, w, "a", utc(2026, 6, 10, 21, 30))   # 23:30 on the 10th
    put(db, w, "b", utc(2026, 6, 10, 22, 30))   # 00:30 on the 11th
    put(db, w, "c", utc(2026, 6, 9, 22, 30))    # 00:30 on the 10th
    db.commit()
    day = (utc(2026, 6, 10, 0, 0), utc(2026, 6, 10, 23, 0))

    days, _ = series(db, w, *day, tz=STOCKHOLM)
    assert days == [("2026-06-10", 1), ("2026-06-11", 1)]
    days, _ = series(db, w, *day)
    assert days == [("2026-06-10", 2)]

    # A local day holds what happened on it, and so does the day before it
    # when the two are compared.
    start, end = parse_api_window("2026-06-11", "2026-06-11", STOCKHOLM)
    days, stats = series(db, w, start, end, tz=STOCKHOLM, compare=True)
    assert days == [("2026-06-11", 1)]
    assert stats["total_pageviews"] == 1
    previous = {p["date"]: p["views"] for p in stats["timeseries_previous"]}
    assert previous.get("2026-06-10") == 2, previous
    assert previous.get("2026-06-09", 0) == 0, previous


def test_the_days_the_clocks_change(db, website):
    w = website["id"]
    put(db, w, "before", utc(2026, 10, 24, 21, 30))   # 23:30 CEST on the 24th
    put(db, w, "a", utc(2026, 10, 24, 22, 30))        # 00:30 CEST on the 25th
    put(db, w, "b", utc(2026, 10, 25, 0, 30))         # 02:30 CEST, first time
    put(db, w, "c", utc(2026, 10, 25, 1, 30))         # 02:30 CET, second time
    put(db, w, "d", utc(2026, 10, 25, 22, 30))        # 23:30 CET, the 25th hour
    put(db, w, "after", utc(2026, 10, 25, 23, 30))    # 00:30 CET on the 26th

    put(db, w, "before", utc(2026, 3, 28, 22, 30))    # 23:30 CET on the 28th
    put(db, w, "a", utc(2026, 3, 28, 23, 30))         # 00:30 CET on the 29th
    put(db, w, "b", utc(2026, 3, 29, 1, 30))          # 03:30 CEST, 02:30 never was
    put(db, w, "c", utc(2026, 3, 29, 21, 30))         # 23:30 CEST on the 29th
    put(db, w, "after", utc(2026, 3, 29, 22, 30))     # 00:30 CEST on the 30th
    db.commit()

    # The 25 hour day is one point with all 25 hours in it.
    start, end = parse_api_window("2026-10-25", "2026-10-25", STOCKHOLM)
    days, stats = series(db, w, start, end, tz=STOCKHOLM)
    assert days == [("2026-10-25", 4)]
    assert stats["total_pageviews"] == 4

    # The 23 hour day is one point and stops at midnight.
    start, end = parse_api_window("2026-03-29", "2026-03-29", STOCKHOLM)
    days, stats = series(db, w, start, end, tz=STOCKHOLM)
    assert days == [("2026-03-29", 3)]
    assert stats["total_pageviews"] == 3

    # Every day appears once across the change.
    start, end = parse_api_window("2026-10-24", "2026-10-26", STOCKHOLM)
    days, _ = series(db, w, start, end, tz=STOCKHOLM)
    assert days == [("2026-10-24", 1), ("2026-10-25", 4), ("2026-10-26", 1)]


def test_the_default_is_unchanged(owner_client, db, website):
    """A website nobody gave a zone counts UTC days, through the service and
    through the API, and stops doing so the moment it is given one."""
    w = website["id"]
    put(db, w, "a", utc(2026, 10, 24, 22, 30))     # the 25th in Stockholm only
    put(db, w, "b", utc(2026, 10, 24, 23, 59, 59))
    put(db, w, "c", utc(2026, 10, 25, 0, 0, 0))
    put(db, w, "d", utc(2026, 10, 25, 23, 30))     # the 25th in UTC only
    db.commit()
    assert stored_zone(db, w) == "UTC"

    start, end = parse_api_window("2026-10-24", "2026-10-25")
    days, stats = series(db, w, start, end)
    assert days == [("2026-10-24", 2), ("2026-10-25", 2)]
    assert stats["total_pageviews"] == 4

    # And it is what grouping on the UTC date gives, row for row.
    plain = db.execute(
        text(
            'SELECT (("timestamp" AT TIME ZONE \'UTC\')::date)::text, count(*) '
            "FROM pageviews WHERE website_id = :w GROUP BY 1 ORDER BY 1"
        ),
        {"w": w},
    ).all()
    assert days == [(day, n) for day, n in plain]

    url = f"/api/v1/analytics/stats/{w}?start_date=2026-10-25&end_date=2026-10-25"
    body = owner_client.get(url).json()
    assert body["total_pageviews"] == 2
    assert [(p["date"], p["views"]) for p in body["timeseries"]] == [("2026-10-25", 2)]

    # The same request once the site is in Stockholm: a different three.
    set_zone(db, w, STOCKHOLM)
    body = owner_client.get(url).json()
    assert body["total_pageviews"] == 3
    assert [(p["date"], p["views"]) for p in body["timeseries"]] == [("2026-10-25", 3)]


# ------------------------------------------------------- the other day counts


def test_the_website_cards_count_each_sites_own_days(db, website, second_website):
    # 00:30 on 16 March in Stockholm, still the 15th in UTC.
    now = utc(2026, 3, 15, 23, 30)
    stockholm, plain = website["id"], second_website["id"]
    for w in (stockholm, plain):
        put(db, w, "a", utc(2026, 3, 15, 22, 50))   # 23:50 on the 15th, local
        put(db, w, "b", utc(2026, 3, 15, 23, 10))   # 00:10 on the 16th, local
    db.commit()

    out = recent_activity(db, [stockholm, plain], now=now, zones={stockholm: STOCKHOLM})
    assert out[stockholm]["days"][-2:] == [1, 1]
    assert out[plain]["days"][-2:] == [0, 2]
    assert out[stockholm]["week"] == out[plain]["week"] == 2

    # The fourteen days start at local midnight: 00:00 on 3 March in
    # Stockholm is 23:00 UTC on the 2nd.
    put(db, stockholm, "in", utc(2026, 3, 2, 23, 30))
    put(db, stockholm, "out", utc(2026, 3, 2, 22, 30))
    db.commit()
    days = recent_activity(db, [stockholm], now=now, zones={stockholm: STOCKHOLM})[stockholm]["days"]
    assert days[0] == 1 and sum(days) == 3
    # In UTC the window starts at 00:00 on the 2nd and both land on its first day.
    assert recent_activity(db, [stockholm], now=now)[stockholm]["days"][0] == 2


def test_goal_cards_and_revenue_land_on_the_local_day(db, website, goal):
    w = website["id"]
    now = utc(2026, 6, 10, 23, 0)                    # 01:00 on the 11th, local
    for i, when in enumerate((utc(2026, 6, 10, 21, 30), utc(2026, 6, 10, 22, 30))):
        put(db, w, "v", when)
        db.execute(
            text(
                "INSERT INTO goal_conversions (goal_id, website_id, visitor_hash, timestamp) "
                "VALUES (:g, :w, 'v', :t)"
            ),
            {"g": goal["id"], "w": w, "t": when},
        )
        db.execute(
            text(
                "INSERT INTO ecommerce_events (website_id, event_type, event_name, "
                "  visitor_hash, transaction_id, revenue, currency, timestamp) "
                "VALUES (:w, 'purchase', 'purchase', 'v', :tx, 100, 'SEK', :t)"
            ),
            {"w": w, "tx": f"tx-{i}-{uuid.uuid4().hex[:6]}", "t": when},
        )
    db.commit()

    def last_two(**kwargs):
        spark = goal_activity(db, w, now=now, **kwargs)["goals"][goal["id"]]["spark"]["line"]
        return [float(p.split(",")[1]) for p in spark.split()][-2:]

    yesterday, today = last_two(tz=STOCKHOLM)
    assert yesterday == today                        # one each
    yesterday, today = last_two()
    assert today < yesterday == 35.0                 # both on the 10th: UTC today

    start, end = utc(2026, 6, 10, 0, 0), utc(2026, 6, 10, 23, 59)
    service = EcommerceService(db)
    local = service.get_revenue_timeseries(w, start, end, "SEK", tz=STOCKHOLM)
    assert [(r["date"], r["revenue"]) for r in local["data"]] == [
        ("2026-06-10", 100.0), ("2026-06-11", 100.0),
    ]
    plain = service.get_revenue_timeseries(w, start, end, "SEK")
    assert [(r["date"], r["revenue"]) for r in plain["data"]] == [("2026-06-10", 200.0)]


# ------------------------------------------------------------------- settings


def test_choosing_a_zone(owner_client, db, website):
    w = website["id"]
    page = owner_client.get(f"/dashboard/website/{w}/settings")
    assert page.status_code == 200
    assert '<option value="UTC" selected>' in page.text
    assert f'<option value="{STOCKHOLM}">' in page.text

    # A name that is not a zone is refused, and says why.
    for bad in ("Mars/Phobos", "europe/stockholm", "", "+02:00"):
        r = owner_client.put(f"/api/v1/websites/{w}", json={"timezone": bad})
        assert r.status_code in (400, 422), (bad, r.text)
        assert "time zone" in r.text.lower(), (bad, r.text)
        assert stored_zone(db, w) == "UTC", bad

    r = owner_client.put(f"/api/v1/websites/{w}", json={"timezone": STOCKHOLM})
    assert r.status_code == 200, r.text
    assert r.json()["timezone"] == STOCKHOLM
    assert stored_zone(db, w) == STOCKHOLM

    # Renaming leaves the zone alone.
    r = owner_client.put(f"/api/v1/websites/{w}", json={"name": "Renamed"})
    assert r.status_code == 200, r.text
    assert r.json()["timezone"] == STOCKHOLM

    db.expire_all()
    page = owner_client.get(f"/dashboard/website/{w}/settings")
    assert f'<option value="{STOCKHOLM}" selected>' in page.text
    assert '<option value="UTC" selected>' not in page.text


def test_the_dashboards_draw_local_days(owner_client, client, db, shared_website):
    """The signed-in dashboard and the public one, against the real clock."""
    w = shared_website["id"]
    now = datetime.now(timezone.utc)
    zone = a_zone_on_another_date(now)
    set_zone(db, w, zone)
    put(db, w, "a", now - timedelta(minutes=30))
    db.commit()
    local_day = local_date(now - timedelta(minutes=30), zone).isoformat()
    drawn = re.compile(rf'"date":\s*"{local_day}",\s*"views":\s*1\b')

    for url in (f"/dashboard/website/{w}?range=7d",
                f"/public/{shared_website['share_token']}?range=7d"):
        page = (owner_client if url.startswith("/dashboard") else client).get(url)
        assert page.status_code == 200, url
        assert drawn.search(page.text), (
            f"{url}: the pageview is not on {local_day}, its day in {zone}"
        )


# ------------------------------------------- the public dashboard, under RLS

RLS_URL = os.environ.get("RLS_TEST_DATABASE_URL")


@pytest.mark.skipif(
    not RLS_URL,
    reason="RLS_TEST_DATABASE_URL not set; this runs in CI and tests nothing if it skips there.",
)
def test_a_share_link_can_read_its_own_zone_and_no_other(engine):
    """The public dashboard reads the zone from websites, as the role
    production runs as. The share token resolver does not return it."""
    from sqlalchemy.orm import Session
    from app.database import set_rls_context
    from app.routers.dashboard import _public_timezone

    made = []
    with engine.begin() as conn:
        for zone in (STOCKHOLM, "Asia/Tokyo"):
            suffix = uuid.uuid4().hex[:8]
            owner = f"tz-{suffix}@example.com"
            conn.execute(
                text("INSERT INTO users (email, is_verified, created_at) VALUES (:e, true, now())"),
                {"e": owner},
            )
            wid = conn.execute(
                text(
                    "INSERT INTO websites (name, domain, user_email, tracking_code,"
                    "  verification_token, is_verified, is_active, email_reports_enabled,"
                    "  is_public, public_password_enabled, created_at, timezone) "
                    "VALUES (:n, :d, :o, :tc, :vt, true, true, false, true, false, now(), :z) "
                    "RETURNING id"
                ),
                {"n": f"Tz {suffix}", "d": f"https://tz-{suffix}.example.com", "o": owner,
                 "tc": uuid.uuid4().hex[:8], "vt": f"tok-{suffix}", "z": zone},
            ).scalar()
            made.append((wid, owner))

    unprivileged = create_engine(pin_psycopg2(RLS_URL), future=True)
    try:
        with Session(unprivileged) as session:
            set_rls_context(session, context="public", website_id=made[0][0])
            assert _public_timezone(session, made[0][0]) == STOCKHOLM
            # The other website's row is not visible, so it reads as the default.
            assert _public_timezone(session, made[1][0]) == "UTC"
            session.rollback()
    finally:
        unprivileged.dispose()
        with engine.begin() as conn:
            for wid, owner in made:
                conn.execute(text("DELETE FROM websites WHERE id = :w"), {"w": wid})
                conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": owner})
