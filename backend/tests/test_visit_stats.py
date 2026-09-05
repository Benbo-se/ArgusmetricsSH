"""Visits, and the four numbers that only exist once you have them.

The dashboard counted pageviews and distinct visitors and stopped there, which
left out everything every other analytics tool leads with: how many visits
those visitors made, how many pages they saw per visit, how many left on the
page they arrived at, and how long they stayed. None of it is derivable from
two totals, because a visitor is not a visit: someone who reads three pages
this morning and two tonight is one visitor and two visits, and the gap between
them is the whole point.

Visits are derived at query time from timestamps. Nothing is written down, no
identifier follows anyone between visits, and the visitor hash still rotates
daily. A stored session id would have been easier to query and would have been
the one piece of durable state this project has spent its life not keeping.

The timestamps here are placed to the second, because sessionisation is a
question about gaps and a fixture that inserts "some pageviews" cannot ask it.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.analytics_query_service import (
    VISIT_TIMEOUT_SECONDS,
    AnalyticsQueryService,
)

# Far enough back that no other test's data can drift into the window, and
# fixed rather than relative so a failure is reproducible.
ANCHOR = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def record(db, website):
    """Put a pageview at an exact offset from the anchor."""
    def _record(visitor: str, seconds: int, path: str = "/"):
        db.execute(
            text(
                'INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp") '
                "VALUES (:w, :p, :h, :t)"
            ),
            {
                "w": website["id"],
                "p": path,
                "h": visitor,
                "t": ANCHOR + timedelta(seconds=seconds),
            },
        )
        db.commit()
    return _record


@pytest.fixture
def visits(db, website):
    """The visit numbers for the whole anchored window."""
    service = AnalyticsQueryService(db)

    def _visits(**filters):
        conditions = service._base_conditions(
            website["id"],
            ANCHOR - timedelta(days=1),
            ANCHOR + timedelta(days=1),
            **filters,
        )
        return service._get_visit_stats(conditions)
    return _visits


class TestGroupingPageviewsIntoVisits:
    def test_nothing_recorded_is_no_visits_rather_than_a_crash(self, visits, caplog):
        """Zeros, and zeros for the right reason.

        _get_visit_stats swallows a failure and returns exactly this dict, so
        "no data" and "the query is broken" are indistinguishable from the
        outside. The log is the only thing that tells them apart, which makes
        it part of the assertion.
        """
        import logging

        with caplog.at_level(logging.ERROR):
            result = visits()

        assert result == {
            "total_visits": 0,
            "views_per_visit": 0.0,
            "bounce_rate": 0.0,
            "avg_visit_seconds": 0,
        }
        assert not [r for r in caplog.records if "visit stats" in r.message], (
            "the query raised and the fallback made it look like an empty "
            "site: " + "; ".join(r.message for r in caplog.records)
        )

    def test_pageviews_close_together_are_one_visit(self, record, visits):
        record("alice", 0, "/")
        record("alice", 60, "/pricing")
        record("alice", 120, "/signup")

        result = visits()
        assert result["total_visits"] == 1
        assert result["views_per_visit"] == 3.0
        assert result["avg_visit_seconds"] == 120

    def test_a_long_gap_starts_a_second_visit(self, record, visits):
        """The whole reason a visitor is not a visit."""
        record("alice", 0, "/")
        record("alice", VISIT_TIMEOUT_SECONDS + 1, "/again")

        result = visits()
        assert result["total_visits"] == 2, (
            "two pageviews more than the timeout apart are two visits, not one "
            "long one, or the duration becomes the gap between them"
        )
        assert result["views_per_visit"] == 1.0

    def test_a_gap_just_inside_the_timeout_does_not(self, record, visits):
        """The boundary, in the direction that keeps a visit together."""
        record("alice", 0, "/")
        record("alice", VISIT_TIMEOUT_SECONDS, "/still-reading")

        assert visits()["total_visits"] == 1

    def test_visitors_are_sessionised_separately(self, record, visits):
        """Two people reading at the same time are two visits, not one.

        The window functions partition by visitor. Without that partition,
        interleaved traffic would look like one person hopping between pages,
        which on a busy site collapses every visit into a handful.
        """
        record("alice", 0, "/")
        record("bob", 5, "/")
        record("alice", 10, "/pricing")
        record("bob", 15, "/pricing")

        result = visits()
        assert result["total_visits"] == 2
        assert result["views_per_visit"] == 2.0


class TestBounceRate:
    def test_a_single_pageview_visit_is_a_bounce(self, record, visits):
        record("alice", 0, "/")
        assert visits()["bounce_rate"] == 100.0

    def test_a_visit_that_went_somewhere_is_not(self, record, visits):
        record("alice", 0, "/")
        record("alice", 30, "/pricing")
        assert visits()["bounce_rate"] == 0.0

    def test_it_is_a_share_of_visits_not_of_visitors(self, record, visits):
        """One visitor, two visits, one of them a bounce.

        Computed per visitor this would be either 0% or 100% and the number
        would be meaningless on a site with returning readers.
        """
        record("alice", 0, "/")
        record("alice", 30, "/pricing")
        record("alice", VISIT_TIMEOUT_SECONDS + 100, "/")

        result = visits()
        assert result["total_visits"] == 2
        assert result["bounce_rate"] == 50.0


class TestVisitDuration:
    def test_a_bounce_is_zero_seconds(self, record, visits):
        """Not excluded, averaged in.

        A single pageview has no second timestamp to measure against, so its
        duration is nought. Dropping bounces from the average would make the
        number rise every time the site got worse at holding people, which is
        exactly backwards.
        """
        record("alice", 0, "/")
        assert visits()["avg_visit_seconds"] == 0

    def test_it_is_first_to_last_pageview(self, record, visits):
        record("alice", 0, "/")
        record("alice", 45, "/pricing")
        record("alice", 200, "/signup")
        assert visits()["avg_visit_seconds"] == 200

    def test_the_gap_between_visits_is_not_counted(self, record, visits):
        """The failure this whole approach exists to avoid.

        Without sessionisation, "duration" is max minus min over the visitor's
        whole history, and someone who came back a week later would show a
        visit lasting a week.
        """
        record("alice", 0, "/")
        record("alice", 20, "/pricing")
        record("alice", VISIT_TIMEOUT_SECONDS + 1000, "/")

        result = visits()
        assert result["avg_visit_seconds"] == 10, (
            "expected the mean of a 20s visit and a 0s bounce; a larger number "
            "means the idle gap was counted as time on the site"
        )


class TestTheNumbersAgreeWithEachOther:
    """Cross-checks, because four numbers from one query can all be wrong
    together in a way none of them shows alone."""

    def test_views_per_visit_matches_pageviews_over_visits(self, record, visits, db, website):
        for offset, path in ((0, "/"), (30, "/a"), (60, "/b")):
            record("alice", offset, path)
        record("bob", 0, "/")

        result = visits()
        total = db.execute(
            text("SELECT count(*) FROM pageviews WHERE website_id = :w"),
            {"w": website["id"]},
        ).scalar()

        assert result["total_visits"] == 2
        assert result["views_per_visit"] == round(total / result["total_visits"], 2)

    def test_visits_never_outnumber_pageviews(self, record, visits):
        record("alice", 0, "/")
        record("bob", 10, "/")
        record("alice", 20, "/a")

        result = visits()
        assert 0 < result["total_visits"] <= 3


class TestSystemPathsAreExcludedHere_Too:
    def test_a_dashboard_path_does_not_create_a_visit(self, record, visits):
        """The base conditions apply, or these numbers count our own UI.

        The pageview total already excluded /dashboard/ and friends. If the
        visit query did not, the two would disagree and views-per-visit would
        come out below one.
        """
        record("alice", 0, "/dashboard/website/1")
        assert visits()["total_visits"] == 0


class TestTheComparisonMeasuresTheSameThing:
    """The previous period used to be built without the filters.

    So with a filter on, the arrow beside a number compared that filtered
    number against an unfiltered previous week, and pointed wherever the
    unfiltered traffic happened to go. Both periods now come from the same
    builder.
    """

    def test_both_periods_exclude_system_paths(self, db, website):
        service = AnalyticsQueryService(db)
        current = service._base_conditions(
            website["id"], ANCHOR, ANCHOR + timedelta(days=1)
        )
        previous = service._base_conditions(
            website["id"], ANCHOR - timedelta(days=1), ANCHOR
        )
        assert len(current) == len(previous)

    def test_a_filter_reaches_the_previous_period(self, db, website):
        service = AnalyticsQueryService(db)
        unfiltered = service._base_conditions(
            website["id"], ANCHOR, ANCHOR + timedelta(days=1)
        )
        filtered = service._base_conditions(
            website["id"], ANCHOR, ANCHOR + timedelta(days=1),
            filter_country="SE",
        )
        assert len(filtered) == len(unfiltered) + 1

    def test_the_comparison_is_computed_against_the_filtered_previous_period(
        self, db, website, record
    ):
        """End to end: a filter that matches nothing must not borrow traffic.

        Every pageview here has no country. Filtering on one and asking for a
        comparison has to give zero in both periods; the old code would have
        found the previous period's rows because it never applied the filter.
        """
        record("alice", 0, "/")
        record("alice", -VISIT_TIMEOUT_SECONDS * 10, "/")

        stats = AnalyticsQueryService(db).get_dashboard_stats(
            website_id=website["id"],
            start_date=ANCHOR - timedelta(hours=1),
            end_date=ANCHOR + timedelta(hours=1),
            compare=True,
            filter_country="ZZ",
        )

        assert stats["total_pageviews"] == 0
        assert stats["comparison"]["prev_pageviews"] == 0, (
            "the previous period ignored the country filter and counted rows "
            "the current period had excluded"
        )


class TestTheTilesReachThePage:
    """The numbers are useless if the markup that shows them does not render.

    Three pages render the same tiles through one shared partial, and a macro
    import or a missing filter is a 500 that no amount of service-level testing
    would show. This is the cheapest possible check that the wiring is real,
    and it is the check that was missing every previous time a feature was
    complete in the service and absent on the screen.
    """

    HEADINGS = ["Unique Visitors", "Visits", "Total Pageviews", "Views / Visit",
                "Bounce Rate", "Visit Duration", "Avg. Scroll Depth"]

    def test_the_dashboard_renders_every_tile(self, owner_client, website, record):
        record("alice", 0, "/")
        record("alice", 30, "/pricing")

        response = owner_client.get(f"/dashboard/website/{website['id']}")

        assert response.status_code == 200
        for heading in self.HEADINGS:
            assert heading in response.text, f"{heading} is missing from the dashboard"

    def test_the_refresh_partial_renders_every_tile(self, owner_client, website):
        response = owner_client.get(
            f"/dashboard/website/{website['id']}/stats-basic?range=30d"
        )

        assert response.status_code == 200
        for heading in self.HEADINGS:
            assert heading in response.text, f"{heading} is missing from the refresh"

    def test_the_refresh_survives_a_comparison(self, owner_client, website, record):
        """compare=true takes the branch that computes the previous period."""
        record("alice", 0, "/")

        response = owner_client.get(
            f"/dashboard/website/{website['id']}/stats-basic?range=30d&compare=true"
        )
        assert response.status_code == 200
        assert "Bounce Rate" in response.text

    def test_the_dashboard_no_longer_carries_its_own_copy(self):
        """The tiles were transcribed into three files and drifted.

        website.html and public.html both include the partial now. A literal
        tile heading back in either one means someone pasted a fourth copy.
        """
        import pathlib

        templates = pathlib.Path(__file__).resolve().parents[1] / "app" / "templates"
        for name in ("dashboard/website.html", "dashboard/public.html"):
            source = (templates / name).read_text()
            assert "Total Pageviews" not in source, (
                f"{name} spells out a tile again instead of including "
                "_stats_basic.html, so the copies will drift apart again"
            )
            assert '_stats_basic.html' in source


class TestFormatDuration:
    @pytest.mark.parametrize("seconds,expected", [
        (0, "0s"),
        (43, "43s"),
        (60, "1m 0s"),
        (100, "1m 40s"),
        (3599, "59m 59s"),
        (3600, "1h 0m"),
        (7830, "2h 10m"),
    ])
    def test_it_reads_as_a_duration(self, seconds, expected):
        from app.routers.dashboard import format_duration
        assert format_duration(seconds) == expected

    def test_none_is_not_an_exception(self):
        """The column is nullable and the template pipes it straight in."""
        from app.routers.dashboard import format_duration
        assert format_duration(None) == "0s"


class TestThePublicShareRendersThemToo:
    """The third page that renders these tiles, and the one nobody opens
    while developing. It is also the one an owner's client sees."""

    def test_a_shared_dashboard_shows_the_same_numbers(self, client, shared_website):
        response = client.get(f"/public/{shared_website['share_token']}")

        assert response.status_code == 200
        for heading in TestTheTilesReachThePage.HEADINGS:
            assert heading in response.text, (
                f"{heading} is missing from the public dashboard"
            )
