"""The websites list: what each card says about its site.

Every card used to read "Active" whatever was happening on the site. These
pin down the numbers that replaced it, against pageviews placed on exact
days, so a week boundary or an empty day cannot drift unnoticed.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.services.site_activity import ago, recent_activity

NOW = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)


def put(db, website_id, visitor, when):
    db.execute(
        text('INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp") VALUES (:w, \'/\', :h, :t)'),
        {"w": website_id, "h": visitor, "t": when},
    )
    db.commit()


def test_a_site_nobody_has_visited_says_so(db, website):
    a = recent_activity(db, [website["id"]], now=NOW)[website["id"]]
    assert (a["week"], a["change"], a["online"], a["last_seen"], a["spark"]) == (0, None, 0, None, None)


def test_this_week_against_last_and_who_is_here_now(db, website):
    w = website["id"]
    put(db, w, "a", NOW - timedelta(days=10))        # the week before
    put(db, w, "b", NOW - timedelta(days=9))
    put(db, w, "c", NOW - timedelta(days=2))         # this week
    put(db, w, "c", NOW - timedelta(days=2, minutes=5))  # same visitor, same day
    put(db, w, "d", NOW - timedelta(days=1))
    put(db, w, "e", NOW - timedelta(minutes=2))      # here now
    a = recent_activity(db, [w], now=NOW)[w]
    assert len(a["days"]) == 14 and a["days"][-1] == 1
    assert a["week"] == 3
    assert a["change"] == 50.0
    assert a["online"] == 1
    assert a["last_seen"] == "2 minutes ago"
    assert a["spark"]["line"].count(",") == 14


def test_the_week_is_seven_times_twentyfour_hours_not_seven_calendar_days(db, website):
    """The card and the website's own overview both say "last 7 days".

    NOW is 2026-03-15 12:00, so the rolling week opens at 2026-03-08 12:00
    while the seventh calendar bucket back opens at 2026-03-09 00:00. A visit
    at 2026-03-08 18:00 sits between the two: inside the rolling window the
    overview uses, outside the buckets the sparkline draws. Summing the bars
    put it in the week before and the two screens disagreed.
    """
    w = website["id"]
    put(db, w, "a", NOW - timedelta(days=6, hours=18))
    a = recent_activity(db, [w], now=NOW)[w]
    assert a["week"] == 1
    assert a["change"] is None  # nothing in the week before it to compare with


def test_the_week_before_is_the_matching_window(db, website):
    """The comparison moves with the window it compares against: the seven
    times twenty-four hours before this one, not the seven calendar days."""
    w = website["id"]
    put(db, w, "old", NOW - timedelta(days=13, hours=18))  # inside the previous window
    put(db, w, "gone", NOW - timedelta(days=14, hours=6))  # older than both
    put(db, w, "new", NOW - timedelta(days=1))
    a = recent_activity(db, [w], now=NOW)[w]
    assert (a["week"], a["change"]) == (1, 0.0)


def test_an_old_visit_is_not_online_and_not_this_week(db, website):
    w = website["id"]
    put(db, w, "a", NOW - timedelta(days=40))
    a = recent_activity(db, [w], now=NOW)[w]
    assert (a["week"], a["online"], a["last_seen"]) == (0, 0, "40 days ago")


def test_ago():
    assert ago(NOW, NOW - timedelta(seconds=20)) == "just now"
    assert ago(NOW, NOW - timedelta(minutes=1)) == "1 minute ago"
    assert ago(NOW, NOW - timedelta(hours=5)) == "5 hours ago"


class TestGoalCards:
    """The goals page: thirty days of conversions per goal, and the share of
    visitors who converted, which unlike conversions per visitor cannot pass
    100%."""

    def goal(self, db, website_id, event):
        return db.execute(
            text("INSERT INTO goals (website_id, name, event_name, created_at) "
                 "VALUES (:w, :e, :e, now()) RETURNING id"),
            {"w": website_id, "e": event},
        ).scalar()

    def convert(self, db, website_id, goal_id, visitor, when):
        db.execute(
            text('INSERT INTO goal_conversions (goal_id, website_id, visitor_hash, "timestamp") '
                 "VALUES (:g, :w, :h, :t)"),
            {"g": goal_id, "w": website_id, "h": visitor, "t": when},
        )
        db.commit()

    def test_conversions_rate_and_line(self, db, website):
        from app.services.site_activity import goal_activity
        w = website["id"]
        order = self.goal(db, w, "order")
        quiet = self.goal(db, w, "quiet")
        for v in ("a", "b", "c", "d"):
            put(db, w, v, NOW - timedelta(days=1))
        self.convert(db, w, order, "a", NOW - timedelta(days=1))
        self.convert(db, w, order, "a", NOW - timedelta(hours=2))   # same person again
        self.convert(db, w, order, "b", NOW - timedelta(days=40))   # outside the window
        out = goal_activity(db, w, now=NOW)
        assert out["visitors"] == 4
        assert out["goals"][order]["conversions"] == 2
        assert out["goals"][order]["rate"] == 25.0
        assert out["goals"][order]["spark"]["line"].count(",") == 30
        assert quiet not in out["goals"]
