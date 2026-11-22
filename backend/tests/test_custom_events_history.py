"""The Custom Events panel, and the history it does not have.

Before #241 an event sent without properties was stored as a goal conversion
and nothing else. A site that has tracked a goal for months therefore has a
Goals panel counting every conversion beside a Custom Events table that only
starts at the deploy. The numbers are both right and they disagree, and the
dashboard used to offer no reason for it. These pin the reason down.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.services.events_query_service import EventsQueryService

NOW = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)


def put(db, website_id, name, when):
    db.execute(
        text('INSERT INTO custom_events (website_id, event_name, visitor_hash, "timestamp") '
             "VALUES (:w, :n, 'v', :t)"),
        {"w": website_id, "n": name, "t": when},
    )
    db.commit()


def summary(db, website_id, days):
    return EventsQueryService(db).get_custom_events_summary(
        website_id, NOW - timedelta(days=days), NOW
    )


def test_a_table_that_starts_later_than_the_window_says_when(db, website):
    w = website["id"]
    put(db, w, "bestall_qopla", NOW - timedelta(days=10))
    s = summary(db, w, 90)
    assert s.get("starts_at") is not None
    assert s["starts_at"].date() == (NOW - timedelta(days=10)).date()


def test_a_window_inside_the_history_says_nothing(db, website):
    """The note is for a missing beginning, not for every short table."""
    w = website["id"]
    put(db, w, "bestall_qopla", NOW - timedelta(days=10))
    assert summary(db, w, 5).get("starts_at") is None


def test_no_events_at_all_says_nothing(db, website):
    assert summary(db, website["id"], 90).get("starts_at") is None
