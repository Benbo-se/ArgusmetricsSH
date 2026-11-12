"""A query that fails is an error, not a quiet day.

Most query methods caught every exception and returned empty results with HTTP
200, so a timeout looked like a dashboard full of zeros. None of them rolled
back either, and Postgres refuses every statement in a transaction after one
fails, so the next query in the same request failed with a different, more
confusing error.

The failures here are real ones from the database: a value Postgres cannot
read as a timestamp or an integer. Nothing is mocked into raising, because a
mock that raises proves only that the except block was written.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services import usage_service
from app.services.analytics_query_service import AnalyticsQueryService

NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


def session_still_works(db):
    """True if the session accepts a statement. A poisoned one raises."""
    return db.execute(text("SELECT 1")).scalar() == 1


class TestFailuresAreVisible:
    def test_dashboard_stats_raise_instead_of_returning_zeros(self, db, website):
        service = AnalyticsQueryService(db)
        with pytest.raises(DBAPIError):
            service.get_dashboard_stats(
                website_id=website["id"],
                start_date="not a timestamp",
                end_date=NOW,
            )
        assert session_still_works(db), "the failed statement was never rolled back"

    def test_visit_stats_raise(self, db, website):
        service = AnalyticsQueryService(db)
        conditions = service._base_conditions(website["id"], "not a timestamp", NOW)
        with pytest.raises(DBAPIError):
            service._get_visit_stats(conditions)
        assert session_still_works(db)

    def test_the_timeseries_raises(self, db, website):
        service = AnalyticsQueryService(db)
        with pytest.raises(DBAPIError):
            service._get_timeseries_data(website["id"], "not a timestamp", NOW)
        assert session_still_works(db)

    def test_realtime_stats_raise(self, db):
        with pytest.raises(DBAPIError):
            AnalyticsQueryService(db).get_realtime_stats(website_id="not a number")
        assert session_still_works(db)


class TestWhereAFallbackIsIntended:
    def test_a_failed_comparison_leaves_the_numbers_and_drops_the_arrows(self, db):
        """The arrows are decoration on numbers that are already computed, so
        losing them is the right degradation. What must not happen is the
        failed statement poisoning the session the page still has to use."""
        result = AnalyticsQueryService(db)._get_comparison_data(
            "not a number", NOW - timedelta(days=1), NOW, 0, 0
        )
        assert result["comparison"]["pageviews_change"] is None
        assert session_still_works(db), (
            "the comparison fell back but left the transaction aborted, so the "
            "next query in the request would have failed"
        )

    def test_a_failed_usage_lookup_lets_the_event_through_and_the_insert_work(
        self, db, website, monkeypatch
    ):
        """may_record fails open by design. But it fails open into a
        transaction Postgres has already condemned, so the pageview insert
        that follows would fail anyway and the event was lost regardless."""
        from app.config import settings

        monkeypatch.setattr(settings, "MONTHLY_EVENT_LIMIT", 100)

        def broken_lookup(db, owner_email):
            db.execute(text("SELECT 1/0"))

        monkeypatch.setattr(usage_service, "get_usage", broken_lookup)

        assert usage_service.may_record(db, website["email"]) is True
        assert session_still_works(db), (
            "may_record said yes and left a poisoned transaction behind"
        )


class TestThePageSaysSo:
    @pytest.fixture
    def broken(self, monkeypatch):
        def boom(self, *args, **kwargs):
            raise RuntimeError("the database went away")

        monkeypatch.setattr(AnalyticsQueryService, "get_dashboard_stats", boom)

    def test_the_dashboard_is_an_error_page_not_a_page_of_zeros(
        self, owner_client, website, broken
    ):
        response = owner_client.get(f"/dashboard/website/{website['id']}")
        assert response.status_code == 503
        assert "could not be loaded" in response.text
        assert "Total Pageviews" not in response.text, (
            "zeros were rendered as if they were the answer"
        )

    @pytest.mark.parametrize("partial", ["stats", "stats-basic"])
    def test_the_refresh_partials_fail_loudly_so_the_page_keeps_its_numbers(
        self, owner_client, website, broken, partial
    ):
        """htmx does not swap a 5xx, so the last good numbers stay on screen
        and the existing responseError handler shows the toast."""
        response = owner_client.get(
            f"/dashboard/website/{website['id']}/{partial}?range=30d"
        )
        assert response.status_code == 503
        assert "could not be loaded" in response.text
