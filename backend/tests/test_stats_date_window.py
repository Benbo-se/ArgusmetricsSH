"""A bare end date means the end of that day, on every endpoint that takes one.

`end_date=2026-11-10` used to be read as midnight at the start of that day, so
everything that happened on it fell outside the range, and the error message
tells callers to send exactly that format. Each endpoint had its own copy of
the parsing, so each is tested against data placed late on the end day.
"""
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import text

from app.utils.date_helpers import parse_api_window

TODAY = datetime.now(timezone.utc).date()
# Midday on the end day: after the midnight the old parser stopped at.
LATE = datetime.combine(TODAY, time(12, 0), tzinfo=timezone.utc)
START = (TODAY - timedelta(days=3)).isoformat()
END = TODAY.isoformat()
WINDOW = f"start_date={START}&end_date={END}"


@pytest.fixture
def seeded(db, website, goal):
    """One pageview, one custom event and one conversion, all on the end day."""
    wid = website["id"]
    visitor = uuid.uuid4().hex[:16]
    db.execute(
        text(
            "INSERT INTO pageviews (website_id, path, visitor_hash, timestamp, "
            "  browser, device_type, properties) "
            "VALUES (:w, '/on-the-end-day', :h, :t, 'Chrome', 'desktop', "
            "  CAST(:p AS jsonb))"
        ),
        {"w": wid, "h": visitor, "t": LATE, "p": json.dumps({"plan": "pro"})},
    )
    db.execute(
        text(
            "INSERT INTO custom_events (website_id, event_name, visitor_hash, timestamp) "
            "VALUES (:w, 'end_day_event', :h, :t)"
        ),
        {"w": wid, "h": visitor, "t": LATE},
    )
    db.execute(
        text(
            "INSERT INTO goal_conversions (goal_id, website_id, visitor_hash, timestamp) "
            "VALUES (:g, :w, :h, :t)"
        ),
        {"g": goal["id"], "w": wid, "h": visitor, "t": LATE},
    )
    db.commit()
    return website


class TestEveryEndpointIncludesTheEndDay:
    def test_stats(self, owner_client, seeded):
        r = owner_client.get(f"/api/v1/analytics/stats/{seeded['id']}?{WINDOW}")
        assert r.status_code == 200, r.text
        assert r.json()["total_pageviews"] == 1

    def test_goals(self, owner_client, seeded):
        r = owner_client.get(f"/api/v1/analytics/goals/{seeded['id']}?{WINDOW}")
        assert r.status_code == 200, r.text
        assert r.json()["goals"][0]["conversions"] == 1

    def test_csv_export(self, owner_client, seeded):
        r = owner_client.get(f"/api/v1/analytics/export/{seeded['id']}/csv?{WINDOW}")
        assert r.status_code == 200, r.text
        assert "/on-the-end-day" in r.text

    def test_json_export(self, owner_client, seeded):
        r = owner_client.get(f"/api/v1/analytics/export/{seeded['id']}/json?{WINDOW}")
        assert r.status_code == 200, r.text
        assert r.json()["total_pageviews"] == 1

    def test_custom_events(self, owner_client, seeded):
        r = owner_client.get(f"/api/v1/analytics/custom-events/{seeded['id']}?{WINDOW}")
        assert r.status_code == 200, r.text
        assert r.json()["total_events"] == 1

    def test_event_details(self, owner_client, seeded):
        r = owner_client.get(
            f"/api/v1/analytics/custom-events/{seeded['id']}/end_day_event?{WINDOW}"
        )
        assert r.status_code == 200, r.text
        assert r.json()["total_count"] == 1

    def test_properties(self, owner_client, seeded):
        r = owner_client.get(f"/api/v1/analytics/properties/{seeded['id']}?{WINDOW}")
        assert r.status_code == 200, r.text
        assert r.json() == {"plan": ["pro"]}

    def test_the_day_after_the_end_day_is_still_excluded(self, owner_client, seeded):
        yesterday = (TODAY - timedelta(days=1)).isoformat()
        r = owner_client.get(
            f"/api/v1/analytics/stats/{seeded['id']}?start_date={START}&end_date={yesterday}"
        )
        assert r.status_code == 200, r.text
        assert r.json()["total_pageviews"] == 0


class TestTheSharedParser:
    def test_a_bare_end_date_is_the_end_of_that_day(self):
        _, end = parse_api_window("2026-11-01", "2026-11-10")
        assert end.date() == date(2026, 11, 10)
        assert end.time() > time(23, 59, 59)

    def test_a_start_date_is_the_start_of_the_day(self):
        start, _ = parse_api_window("2026-11-01", "2026-11-10")
        assert start == datetime(2026, 11, 1)

    def test_an_end_with_a_time_is_left_alone(self):
        _, end = parse_api_window("2026-11-01", "2026-11-10T08:30:00Z")
        assert end == datetime(2026, 11, 10, 8, 30, tzinfo=timezone.utc)

    def test_defaults_are_thirty_days_back_from_now(self):
        start, end = parse_api_window(None, None)
        assert timedelta(days=29, hours=23) < end - start <= timedelta(days=30)

    def test_garbage_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_api_window("nope", None)
        with pytest.raises(ValueError):
            parse_api_window(None, "2026-13-45")
