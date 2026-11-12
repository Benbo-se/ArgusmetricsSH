"""A page is its path, not the campaign link that led to it.

The tracker keeps every query parameter that is not on the sensitive list, so
an ad click on /pricing is stored as /pricing?fbclid=abc. Top pages grouped on
that raw string and gave every click its own row, and a funnel step for
/pricing never matched the visitor. Nothing stored is rewritten: the raw path
stays in the table, and the readers compare the part before the question mark.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.database import set_rls_context
from sqlalchemy import text

from app.models.funnel import Funnel, FunnelEvent
from app.services.analytics_query_service import AnalyticsQueryService
from app.services.analytics_recording_service import AnalyticsRecordingService

ANCHOR = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def record(db, website):
    def _record(visitor: str, seconds: int, path: str):
        db.execute(
            text(
                'INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp") '
                "VALUES (:w, :p, :h, :t)"
            ),
            {"w": website["id"], "p": path, "h": visitor,
             "t": ANCHOR + timedelta(seconds=seconds)},
        )
        db.commit()
    return _record


def stats(db, website, **filters):
    return AnalyticsQueryService(db).get_dashboard_stats(
        website_id=website["id"],
        start_date=ANCHOR - timedelta(hours=1),
        end_date=ANCHOR + timedelta(hours=2),
        **filters,
    )


class TestReadersGroupOnThePath:
    def test_top_pages_merges_a_page_with_its_campaign_variants(self, db, website, record):
        record("a", 0, "/")
        record("b", 0, "/?utm_source=chatgpt.com")
        record("c", 0, "/?fbclid=abc")
        record("d", 0, "/pricing")

        top = {p["path"]: p["views"] for p in stats(db, website)["top_pages"]}
        assert top == {"/": 3, "/pricing": 1}

    def test_entry_and_exit_pages_merge_too(self, db, website, record):
        record("a", 0, "/?utm_source=x")
        record("a", 60, "/bye")
        record("b", 0, "/")
        record("b", 60, "/bye?ref=y")

        result = stats(db, website)
        assert {e["path"]: e["entries"] for e in result["entry_pages"]} == {"/": 2}
        assert {e["path"]: e["exits"] for e in result["exit_pages"]} == {"/bye": 2}

    def test_the_page_filter_reaches_the_variants(self, db, website, record):
        """Clicking a row in Top pages filters on its path; that must find the
        same rows the row counted."""
        record("a", 0, "/pricing")
        record("b", 0, "/pricing?fbclid=abc")
        record("c", 0, "/other")

        assert stats(db, website, filter_page="/pricing")["total_pageviews"] == 2

    def test_the_raw_path_is_still_what_is_stored(self, db, website, record):
        record("a", 0, "/pricing?fbclid=abc")
        stored = db.execute(
            text("SELECT path FROM pageviews WHERE website_id = :w"), {"w": website["id"]}
        ).scalar()
        assert stored == "/pricing?fbclid=abc"


class TestFunnelWritePath:
    @pytest.fixture
    def funnel(self, db, website):
        funnel = Funnel(
            website_id=website["id"], name="Buy", is_active=True,
            steps=[{"step": 1, "name": "Pricing", "path": "/pricing"},
                   {"step": 2, "name": "Buy", "path": "/buy"}],
        )
        db.add(funnel)
        db.commit()
        return funnel

    def reached(self, db, funnel):
        return sorted(
            (e.visitor_id, e.step_number)
            for e in db.query(FunnelEvent).filter(FunnelEvent.funnel_id == funnel.id)
        )

    def test_a_campaign_landing_reaches_the_step(self, db, funnel):
        set_rls_context(db, 'tracking', website_id=funnel.website_id)
        AnalyticsRecordingService(db)._record_funnel_steps(
            funnel.website_id, "/pricing?fbclid=abc", "v1"
        )
        db.commit()
        assert self.reached(db, funnel) == [("v1", 1)]

    def test_a_step_defined_with_a_query_still_matches_by_path(self, db, website):
        funnel = Funnel(
            website_id=website["id"], name="Q", is_active=True,
            steps=[{"step": 1, "name": "P", "path": "/pricing?x=1"}],
        )
        db.add(funnel)
        db.commit()
        set_rls_context(db, 'tracking', website_id=funnel.website_id)
        AnalyticsRecordingService(db)._record_funnel_steps(
            website["id"], "/pricing?y=2", "v1"
        )
        db.commit()
        assert self.reached(db, funnel) == [("v1", 1)]

    def test_a_different_page_does_not(self, db, funnel):
        set_rls_context(db, 'tracking', website_id=funnel.website_id)
        AnalyticsRecordingService(db)._record_funnel_steps(
            funnel.website_id, "/pricing-old?fbclid=abc", "v1"
        )
        db.commit()
        assert self.reached(db, funnel) == []
