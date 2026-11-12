"""Visits are built from every pageview, and the filter only picks which count.

_get_visit_stats used to build visits from rows the filter had already thinned.
Filter on /pricing and a visitor who read six pages, /pricing once, became a
visit of one page: bounce rate went to 100% and visit duration to zero for
exactly the questions a filter is used to ask.

Entry and exit pages used the first and last pageview per visitor and calendar
day while the screen said "by visits". They now use the same thirty minute
definition as the visit numbers.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.analytics_query_service import (
    VISIT_TIMEOUT_SECONDS,
    AnalyticsQueryService,
)

ANCHOR = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def record(db, website):
    def _record(visitor: str, seconds: int, path: str = "/", device: str = None):
        db.execute(
            text(
                'INSERT INTO pageviews (website_id, path, visitor_hash, device_type, "timestamp") '
                "VALUES (:w, :p, :h, :d, :t)"
            ),
            {"w": website["id"], "p": path, "h": visitor, "d": device,
             "t": ANCHOR + timedelta(seconds=seconds)},
        )
        db.commit()
    return _record


@pytest.fixture
def stats(db, website):
    def _stats(**filters):
        return AnalyticsQueryService(db).get_dashboard_stats(
            website_id=website["id"],
            start_date=ANCHOR - timedelta(days=1),
            end_date=ANCHOR + timedelta(days=1),
            **filters,
        )
    return _stats


class TestAFilterPicksVisitsInsteadOfThinningThem:
    @pytest.fixture(autouse=True)
    def traffic(self, record):
        # alice: one visit, six pages, /pricing in the middle.
        for i, path in enumerate(["/", "/a", "/pricing", "/b", "/c", "/d"]):
            record("alice", i * 60, path)
        # bob: lands on /pricing and leaves.
        record("bob", 0, "/pricing")
        # carol: never sees /pricing.
        record("carol", 0, "/x")
        record("carol", 60, "/y")

    def test_unfiltered_numbers_are_the_baseline(self, stats):
        result = stats()
        assert result["total_visits"] == 3
        assert result["bounce_rate"] == pytest.approx(33.3, abs=0.1)

    def test_a_visit_that_touched_the_page_keeps_all_its_pages(self, stats):
        result = stats(filter_page="/pricing")
        assert result["total_visits"] == 2, "carol never saw /pricing"
        assert result["bounce_rate"] == 50.0, (
            "alice read six pages; building visits from the filtered rows made "
            "her a one-page visit and pushed bounce to 100%"
        )
        assert result["views_per_visit"] == 3.5
        assert result["avg_visit_seconds"] == 150

    def test_the_headline_counts_still_follow_the_filter(self, stats):
        result = stats(filter_page="/pricing")
        assert result["total_pageviews"] == 2
        assert result["unique_visitors"] == 2

    def test_a_filter_matching_nothing_gives_no_visits(self, stats):
        assert stats(filter_page="/nowhere")["total_visits"] == 0

    def test_the_same_holds_for_the_other_filters(self, record, stats):
        record("dora", 0, "/", device="mobile")
        record("dora", 60, "/more", device="desktop")
        result = stats(filter_device="mobile")
        assert result["total_visits"] == 1
        assert result["bounce_rate"] == 0.0

    def test_the_previous_period_is_measured_the_same_way(self, record, stats):
        record("alice", -2 * 86400, "/pricing")
        record("alice", -2 * 86400 + 60, "/other")
        result = stats(filter_page="/pricing", compare=True)
        assert result["comparison"]["prev_pageviews"] == 1
        # The earlier visit has two pages, so it was not a bounce (0%). The
        # current period's bounce is 50%, and a change from 0 reads as +100.
        assert result["comparison"]["bounce_rate_change"] == 100.0


class TestEntryAndExitAreVisits:
    def test_two_visits_in_a_day_are_two_entries_and_two_exits(self, record, stats):
        record("alice", 0, "/")
        record("alice", 60, "/a")
        later = VISIT_TIMEOUT_SECONDS + 600
        record("alice", later, "/b")
        record("alice", later + 60, "/c")

        result = stats()
        assert {e["path"]: e["entries"] for e in result["entry_pages"]} == {"/": 1, "/b": 1}
        assert {e["path"]: e["exits"] for e in result["exit_pages"]} == {"/a": 1, "/c": 1}

    def test_a_visit_across_midnight_is_one_entry(self, record, stats):
        # 23:50 and 00:10 are twenty minutes apart: one visit, not one per day.
        record("alice", 11 * 3600 + 50 * 60, "/late")
        record("alice", 12 * 3600 + 10 * 60, "/early")

        result = stats()
        assert [(e["path"], e["entries"]) for e in result["entry_pages"]] == [("/late", 1)]
        assert [(e["path"], e["exits"]) for e in result["exit_pages"]] == [("/early", 1)]

    def test_a_single_page_visit_is_both(self, record, stats):
        record("alice", 0, "/only")
        result = stats()
        assert [e["path"] for e in result["entry_pages"]] == ["/only"]
        assert [e["path"] for e in result["exit_pages"]] == ["/only"]

    def test_with_a_filter_the_entry_is_where_the_visit_really_began(self, record, stats):
        record("alice", 0, "/blog")
        record("alice", 60, "/pricing")
        record("bob", 0, "/other")

        result = stats(filter_page="/pricing")
        assert [(e["path"], e["entries"]) for e in result["entry_pages"]] == [("/blog", 1)]
        assert [(e["path"], e["exits"]) for e in result["exit_pages"]] == [("/pricing", 1)]
