"""One definition of a goal's conversion rate, on the overview and the goals page.

The overview divided conversions by visitors, so one visitor ordering twice
counted twice, while the goals page divided people who converted by visitors.
Same goal, same period, two numbers. The definition is the second one: the
share of the period's unique visitors who converted at least once.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.services.analytics_service import AnalyticsService
from app.services.site_activity import goal_activity

NOW = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
SINCE = datetime(2026, 2, 14, tzinfo=timezone.utc)  # the goals page's first day


def _seed(db, website_id):
    goal_id = db.execute(
        text("INSERT INTO goals (website_id, name, event_name, created_at) "
             "VALUES (:w, 'Order', 'order', now()) RETURNING id"),
        {"w": website_id},
    ).scalar()
    for visitor in ("a", "b", "c", "d"):
        db.execute(
            text('INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp") '
                 "VALUES (:w, '/', :h, :t)"),
            {"w": website_id, "h": visitor, "t": NOW - timedelta(days=1)},
        )
    # Visitor a converts three times, b once: 4 conversions, 2 converters.
    for visitor, hours in (("a", 30), ("a", 20), ("a", 2), ("b", 5)):
        db.execute(
            text('INSERT INTO goal_conversions (goal_id, website_id, visitor_hash, "timestamp") '
                 "VALUES (:g, :w, :h, :t)"),
            {"g": goal_id, "w": website_id, "h": visitor, "t": NOW - timedelta(hours=hours)},
        )
    db.commit()
    return goal_id


def test_overview_and_goals_page_agree_for_the_same_window(db, website):
    goal_id = _seed(db, website["id"])

    page = goal_activity(db, website["id"], now=NOW)["goals"][goal_id]
    overview = AnalyticsService(db).get_goal_stats(
        website["id"], SINCE, NOW + timedelta(days=1)
    )["goals"][0]

    assert page["conversions"] == overview["conversions"] == 4
    assert overview["converters"] == 2
    assert overview["conversion_rate"] == page["rate"] == 50.0, (
        "the overview must count people who converted, not conversions"
    )


def test_a_rate_cannot_pass_one_hundred_percent(db, website):
    w = website["id"]
    goal_id = db.execute(
        text("INSERT INTO goals (website_id, name, event_name, created_at) "
             "VALUES (:w, 'Order', 'order', now()) RETURNING id"),
        {"w": w},
    ).scalar()
    db.execute(
        text('INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp") '
             "VALUES (:w, '/', 'solo', :t)"),
        {"w": w, "t": NOW - timedelta(days=1)},
    )
    for hours in (3, 2, 1):
        db.execute(
            text('INSERT INTO goal_conversions (goal_id, website_id, visitor_hash, "timestamp") '
                 "VALUES (:g, :w, 'solo', :t)"),
            {"g": goal_id, "w": w, "t": NOW - timedelta(hours=hours)},
        )
    db.commit()

    overview = AnalyticsService(db).get_goal_stats(w, SINCE, NOW)["goals"][0]

    assert overview["conversions"] == 3
    assert overview["conversion_rate"] == 100.0
