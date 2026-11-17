"""One filter object, compiled in one place, that every report takes (#197),
and what it makes possible on the dashboard: any dimension, with "is not",
"contains" and "does not contain" beside "is" (#205).

The query layer used to take six named parameters and compare each with `==`.
The time series kept its own copy of the list, and goals, events, outbound
links, downloads, 404s, funnels and revenue never saw a filter: a page
filtered on Sweden showed the whole world's conversions under Sweden's
visitors.

Three groups below. What a query string turns into; what the SQL then counts;
and that the page, its refresh, the export and the API all ask for the same
thing.
"""
import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import and_, text
from sqlalchemy.dialects import postgresql

from app.models.funnel import Funnel
from app.services.analytics_query_service import AnalyticsQueryService
from app.services.ecommerce_service import EcommerceService
from app.services.events_query_service import EventsQueryService
from app.services.filters import DIMENSIONS, MAX_VALUE_LENGTH, Filter, FilterSet
from app.services.funnel_stats import funnel_stats
from app.services.goals_service import goal_conversion_stats

ANCHOR = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
START, END = ANCHOR - timedelta(days=1), ANCHOR + timedelta(days=1)


# ---------------------------------------------------------------------------
# From a query string to a filter, and back
# ---------------------------------------------------------------------------

class TestReadingAQueryString:
    def test_a_bare_name_still_means_is(self):
        """?country=SE is every link and bookmark made before operators existed."""
        assert FilterSet.from_query({"country": "SE"}).filters == (
            Filter("country", "is", "SE"),
        )

    def test_each_operator_has_its_own_parameter(self):
        found = FilterSet.from_query({
            "page": "/a", "page__not": "/b",
            "page__contains": "blog", "page__not_contains": "draft",
        })
        assert {(f.operator, f.value) for f in found.filters} == {
            ("is", "/a"), ("is_not", "/b"), ("contains", "blog"), ("not_contains", "draft"),
        }

    def test_what_is_not_a_filter_is_left_alone(self):
        found = FilterSet.from_query({
            "range": "30d", "compare": "previous", "nonsense": "x",
            "country": "", "page__sounds_like": "/a",
        })
        assert not found
        assert found.query_items() == []

    def test_a_dimension_only_takes_its_own_operators(self):
        """A country is a code and a screen size a range: neither "contains"."""
        found = FilterSet.from_query({
            "country__contains": "S", "screen__not_contains": "19", "device__contains": "mob",
            "country__not": "SE",
        })
        assert found.filters == (Filter("country", "is_not", "SE"),)

    def test_a_value_longer_than_anything_stored_is_no_filter(self):
        assert not FilterSet.from_query({"page__contains": "a" * (MAX_VALUE_LENGTH + 1)})
        assert FilterSet.from_query({"page__contains": "a" * MAX_VALUE_LENGTH})

    @pytest.mark.parametrize("raw", [
        "not json", "[1, 2]", '"text"', '{"a": {"b": 1}}', '{"a": [1]}', '{"a": null}',
        '{"": "x"}', json.dumps({str(i): "x" for i in range(11)}),
    ])
    def test_a_property_filter_that_is_not_a_flat_object_is_dropped(self, raw):
        assert not FilterSet.from_query({"properties": raw})

    def test_a_property_filter_is_read(self):
        found = FilterSet.from_query({"properties": '{"plan": "pro", "seats": 3}'})
        assert found.properties == {"plan": "pro", "seats": 3}

    def test_what_is_written_reads_back_the_same(self):
        original = FilterSet.from_query({
            "country__not": "SE", "page__contains": "/blog?x=1&y=2",
            "utm_source": "news letter", "properties": '{"plan": "pro"}',
        })
        from urllib.parse import parse_qs
        parsed = {k: v[0] for k, v in parse_qs(original.query_string()).items()}
        again = FilterSet.from_query(parsed)
        assert again.filters == original.filters
        assert again.properties == original.properties

    def test_the_log_line_names_the_filters_without_their_values(self):
        line = repr(FilterSet.of(page__contains="/kund/4711", properties='{"userId": "4711"}'))
        assert "page__contains" in line and "properties.userId" in line
        assert "4711" not in line


def _compiled(condition):
    return condition.compile(dialect=postgresql.dialect())


class TestAValueNeverBecomesSql:
    HOSTILE = "x' OR '1'='1' --"

    @pytest.mark.parametrize("name", sorted(DIMENSIONS))
    def test_every_dimension_and_operator_binds_its_value(self, name):
        for operator in DIMENSIONS[name].operators:
            compiled = _compiled(Filter(name, operator, self.HOSTILE).condition())
            assert "OR '1'" not in str(compiled), (name, operator)
            if name != "screen":
                # A screen size that is not the start of a range matches
                # nothing and so binds nothing.
                assert any(
                    isinstance(v, str) and "OR '1'" in v for v in compiled.params.values()
                ), (name, operator)

    def test_a_property_filter_binds_its_value(self):
        conditions = FilterSet.of(properties=json.dumps({"k": self.HOSTILE})).conditions()
        compiled = _compiled(and_(*conditions))
        assert "OR '1'" not in str(compiled)

    def test_contains_escapes_the_like_wildcards(self):
        compiled = _compiled(Filter("page", "contains", "50%_a/b").condition())
        assert "ESCAPE" in str(compiled)
        assert "50/%/_a//b" in compiled.params.values()


# ---------------------------------------------------------------------------
# What the SQL counts
# ---------------------------------------------------------------------------

@pytest.fixture
def view(db, website):
    """Record one pageview. Columns not named are NULL."""
    def _view(visitor="v", seconds=0, path="/", at=None, website_id=None, **columns):
        row = {
            "website_id": website_id or website["id"],
            "path": path,
            "visitor_hash": visitor,
            "timestamp": at or ANCHOR + timedelta(seconds=seconds),
            **columns,
        }
        if "properties" in row:
            row["properties"] = json.dumps(row["properties"])
        names = ", ".join(f'"{name}"' for name in row)
        values = ", ".join(
            f"CAST(:{name} AS jsonb)" if name == "properties" else f":{name}" for name in row
        )
        db.execute(text(f"INSERT INTO pageviews ({names}) VALUES ({values})"), row)
        db.commit()
    return _view


@pytest.fixture
def total(db, website):
    def _total(**filters):
        return AnalyticsQueryService(db).get_dashboard_stats(
            website_id=website["id"], start_date=START, end_date=END,
            filters=FilterSet.of(**filters),
        )["total_pageviews"]
    return _total


class TestOperators:
    def test_is_not_keeps_the_rows_without_a_value(self, view, total):
        """A pageview with no country is not a Swedish one. A bare NOT would
        drop it from both sides, and the two halves would not add up."""
        view(country="SE")
        view(country="NO")
        view()                              # no country at all

        assert total(country="SE") == 1
        assert total(country__not="SE") == 2
        assert total(country="SE") + total(country__not="SE") == total()

    def test_contains_ignores_case(self, view, total):
        view(path="/Blog/First")
        view(path="/blog/second")
        view(path="/pricing")

        assert total(page__contains="blog") == 2
        assert total(page__contains="BLOG/") == 2

    def test_contains_takes_wildcard_characters_literally(self, view, total):
        view(path="/50%-off")
        view(path="/500-off")
        view(path="/a_b")
        view(path="/axb")
        view(path="/back\\slash")

        assert total(page__contains="50%") == 1, "% matched any run of characters"
        assert total(page__contains="a_b") == 1, "_ matched any one character"
        assert total(page__contains="%") == 1
        assert total(page__contains="\\") == 1

    def test_does_not_contain_is_the_rest_and_keeps_missing_values(self, view, total):
        view(referrer="https://www.google.com/search")
        view(referrer="https://news.example.org/")
        view()                              # direct, no referrer

        assert total(referrer__contains="google") == 1
        assert total(referrer__not_contains="google") == 2

    def test_two_conditions_on_one_dimension_both_hold(self, view, total):
        view(path="/blog/a")
        view(path="/blog/draft-b")
        view(path="/pricing")

        assert total(page__contains="/blog", page__not_contains="draft") == 1

    def test_a_page_is_still_its_path_without_the_query_string(self, view, total):
        view(path="/pricing?fbclid=abc")
        view(path="/pricing")
        view(path="/other?next=/pricing")

        assert total(page="/pricing") == 2
        assert total(page__not="/pricing") == 1
        # The query string is not part of the page, so it cannot be searched.
        assert total(page__contains="pricing") == 2

    def test_a_hostile_value_matches_nothing_and_breaks_nothing(self, view, total):
        view(path="/", country="SE")
        hostile = TestAValueNeverBecomesSql.HOSTILE
        assert total(page=hostile) == 0
        assert total(page__contains=hostile) == 0
        assert total(country=hostile) == 0
        assert total(properties=json.dumps({"k": hostile})) == 0
        assert total() == 1

    def test_campaign_tags_are_dimensions(self, view, total):
        view(utm_source="newsletter", utm_medium="email", utm_campaign="spring")
        view(utm_source="google", utm_medium="cpc", utm_campaign="spring-sale")
        view()

        assert total(utm_source="newsletter") == 1
        assert total(utm_medium__not="email") == 2
        assert total(utm_campaign__contains="spring") == 2

    def test_unknown_is_a_value_for_a_negation_too(self, view, total):
        view(os="Windows", browser="Chrome")
        view(browser="Unknown")             # as the recorder writes it
        view()                              # as rows before #204 have it

        assert total(os="Unknown") == 2
        assert total(os__not="Unknown") == 1
        assert total(browser="Unknown") == 2
        assert total(browser__not="Unknown") == 1

    def test_versions_and_screens_take_the_operators_they_can(self, view, total):
        view(browser="Chrome", browser_version="126", screen_width=1920)
        view(browser="Chrome", browser_version="127", screen_width=390)
        view(browser="Firefox", browser_version="128")

        assert total(browser_version="Chrome 126") == 1
        assert total(browser_version__not="Chrome 126") == 2
        assert total(browser_version__contains="chrome") == 2
        assert total(screen="1920") == 1
        assert total(screen__not="1920") == 2

    def test_a_custom_property_combines_with_the_rest(self, view, total):
        view(country="SE", properties={"plan": "pro"})
        view(country="NO", properties={"plan": "pro"})
        view(country="SE", properties={"plan": "free"})

        assert total(properties='{"plan": "pro"}') == 2
        assert total(properties='{"plan": "pro"}', country__not="NO") == 1


class TestEveryNumberOnThePageIsFiltered:
    """The graph kept a second copy of the filter list. One list now."""

    def test_the_graph_and_the_previous_period_take_every_operator(self, db, website, view):
        view(visitor="a", path="/blog/a")
        view(visitor="b", path="/pricing")
        view(visitor="c", path="/blog/old", seconds=-3 * 86400)
        view(visitor="d", path="/pricing", seconds=-3 * 86400)

        stats = AnalyticsQueryService(db).get_dashboard_stats(
            website_id=website["id"], start_date=START, end_date=END, compare=True,
            filters=FilterSet.of(page__contains="/blog"),
        )

        assert sum(point["views"] for point in stats["timeseries"]) == 1
        assert sum(point["views"] for point in stats["timeseries_previous"]) == 1
        assert stats["comparison"]["prev_pageviews"] == 1
        assert stats["total_visits"] == 1


@pytest.fixture
def event(db, website):
    def _event(name, visitor, properties=None, seconds=0):
        db.execute(
            text(
                "INSERT INTO custom_events (website_id, event_name, visitor_hash, properties, timestamp) "
                "VALUES (:w, :n, :v, CAST(:p AS jsonb), :t)"
            ),
            {"w": website["id"], "n": name, "v": visitor,
             "p": json.dumps(properties) if properties is not None else None,
             "t": ANCHOR + timedelta(seconds=seconds)},
        )
        db.commit()
    return _event


class TestReportsThatAreNotPageviews:
    """Goals, events, funnels and purchases carry a visitor and little else.
    A filter keeps the ones whose visitor has a matching pageview."""

    @pytest.fixture(autouse=True)
    def two_visitors(self, view):
        view(visitor="swede", country="SE", path="/pricing")
        view(visitor="norwegian", country="NO", path="/")

    def test_goals_count_the_filtered_visitors_conversions(self, db, website, goal):
        for visitor in ("swede", "swede", "norwegian"):
            db.execute(
                text(
                    "INSERT INTO goal_conversions (goal_id, website_id, visitor_hash, timestamp) "
                    "VALUES (:g, :w, :v, :t)"
                ),
                {"g": goal["id"], "w": website["id"], "v": visitor, "t": ANCHOR},
            )
        db.commit()

        everyone = goal_conversion_stats(db, website["id"], START, END)
        swedes = goal_conversion_stats(
            db, website["id"], START, END, FilterSet.of(country="SE")
        )
        others = goal_conversion_stats(
            db, website["id"], START, END, FilterSet.of(country__not="SE")
        )

        assert everyone["goals"][goal["id"]]["conversions"] == 3
        assert swedes["visitors"] == 1
        assert swedes["goals"][goal["id"]] == {"conversions": 2, "converters": 1, "rate": 100.0}
        assert others["goals"][goal["id"]]["conversions"] == 1

        # And through the dashboard's own numbers, which is where it is shown.
        stats = AnalyticsQueryService(db, goals_service=_goals(db)).get_dashboard_stats(
            website_id=website["id"], start_date=START, end_date=END,
            filters=FilterSet.of(country="SE"),
        )
        assert stats["goals"][0]["conversions"] == 2
        assert stats["total_visitors"] == 1

    def test_the_four_event_tables_are_filtered(self, db, website, event):
        for visitor in ("swede", "norwegian"):
            event("Outbound Link", visitor, {"url": f"https://{visitor}.example.org/"})
            event("file_download", visitor, {"filename": f"{visitor}.pdf"})
            event("404 Error", visitor, {"path": f"/missing-{visitor}"})
            event("signup", visitor)
        service = EventsQueryService(db)
        only = FilterSet.of(country="SE")

        def names(rows, key):
            return [row[key] for row in rows]

        args = (website["id"], START, END)
        assert len(service.get_outbound_links(*args)) == 2
        assert names(service.get_outbound_links(*args, filters=only), "url") == [
            "https://swede.example.org/"]
        assert names(service.get_file_downloads(*args, filters=only), "filename") == ["swede.pdf"]
        assert names(service.get_404_errors(*args, filters=only), "path") == ["/missing-swede"]

        unfiltered = service.get_custom_events_summary(*args)
        filtered = service.get_custom_events_summary(*args, filters=only)
        assert unfiltered["total_events"] == 8
        assert filtered["total_events"] == 4
        assert {e["event_name"]: e["count"] for e in filtered["events"]}["signup"] == 1

    def test_one_events_own_report_is_filtered(self, db, website, event):
        event("signup", "swede", {"plan": "pro"})
        event("signup", "norwegian", {"plan": "free", "seats": 3})
        service = EventsQueryService(db)
        args = (website["id"], "signup", START, END)

        everyone = service.get_event_details(*args)
        swedes = service.get_event_details(*args, filters=FilterSet.of(country="SE"))

        assert (everyone["total_count"], everyone["unique_users"]) == (2, 2)
        assert (swedes["total_count"], swedes["unique_users"]) == (1, 1)
        assert [e["properties"] for e in swedes["events"]] == [{"plan": "pro"}]
        assert swedes["property_breakdown"] == [
            {"property_key": "plan", "property_value": "pro", "count": 1}
        ]
        summary = service.get_custom_events_summary(
            website["id"], START, END, filters=FilterSet.of(country="SE")
        )
        assert summary["events"][0]["top_properties"] == ["plan"]

    def test_a_filter_that_matches_nobody_empties_them(self, db, website, event):
        event("signup", "swede")
        nobody = FilterSet.of(country="ZZ")
        summary = EventsQueryService(db).get_custom_events_summary(
            website["id"], START, END, filters=nobody
        )
        assert summary == {"events": [], "total_events": 0}

    def test_another_websites_matching_visitor_does_not_count(
        self, db, website, second_website, view, event
    ):
        """The visitors are looked up among this website's pageviews only."""
        view(visitor="dane", country="DK", website_id=second_website["id"])
        event("signup", "dane")

        summary = EventsQueryService(db).get_custom_events_summary(
            website["id"], START, END, filters=FilterSet.of(country="DK")
        )
        assert summary["total_events"] == 0

    def test_a_funnel_is_the_one_the_filtered_visitors_walked(self, db, website):
        funnel = Funnel(
            website_id=website["id"], name="Checkout", is_active=True,
            steps=[{"step": 1, "name": "Pricing", "path": "/pricing"},
                   {"step": 2, "name": "Signup", "path": "/signup"}],
        )
        db.add(funnel)
        db.commit()
        for visitor, step in (("swede", 1), ("swede", 2), ("norwegian", 1)):
            db.execute(
                text(
                    'INSERT INTO funnel_events (funnel_id, visitor_id, step_number, step_name, path, "timestamp", completed) '
                    "VALUES (:f, :v, :s, 'x', '/', :t, false)"
                ),
                {"f": funnel.id, "v": visitor, "s": step, "t": ANCHOR},
            )
        db.commit()
        now = ANCHOR + timedelta(hours=1)

        def counts(**filters):
            stats = funnel_stats(db, funnel, days=7, now=now, filters=FilterSet.of(**filters))
            return [step["visitors"] for step in stats["steps"]]

        assert counts() == [2, 1]
        assert counts(country="NO") == [1, 0]
        assert counts(page__contains="pric") == [1, 1]

    def test_revenue_is_the_filtered_visitors_revenue(self, db, website):
        for visitor, order, amount in (("swede", "t1", 100), ("norwegian", "t2", 40)):
            for kind in ("view_item", "purchase"):
                db.execute(
                    text(
                        "INSERT INTO ecommerce_events (website_id, event_type, event_name, "
                        " transaction_id, revenue, currency, product_id, product_name, quantity, "
                        " visitor_hash, timestamp) "
                        "VALUES (:w, :k, :k, :o, :r, 'SEK', :o, :n, 1, :v, :t)"
                    ),
                    {"w": website["id"], "k": kind, "v": visitor, "t": ANCHOR,
                     "o": order if kind == "purchase" else None,
                     "r": amount if kind == "purchase" else None,
                     "n": f"Thing for {visitor}"},
                )
        db.commit()
        service = EcommerceService(db)
        args = dict(website_id=website["id"], start_date=START, end_date=END)
        only = FilterSet.of(country="SE")

        assert float(service.get_revenue_stats(**args, currency="SEK")["total_revenue"]) == 140
        assert float(
            service.get_revenue_stats(**args, currency="SEK", filters=only)["total_revenue"]
        ) == 100
        products = service.get_top_products(**args, currency="SEK", filters=only)
        assert [p["product_name"] for p in products["products"]] == ["Thing for swede"]
        assert products["total_products"] == 1
        assert service.get_conversion_funnel(**args, filters=only)["viewed_products"] == 1
        series = service.get_revenue_timeseries(**args, currency="SEK", filters=only)
        assert series["total_revenue"] == 100


def _goals(db):
    from app.services.goals_service import GoalsService
    return GoalsService(db)


# ---------------------------------------------------------------------------
# The page, its refresh, the export and the API ask for the same thing
# ---------------------------------------------------------------------------

@pytest.fixture
def traffic(view):
    """Three recent pageviews: two Swedish blog readers and a Norwegian."""
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    view(visitor="a", at=now, path="/blog/first", country="SE", referrer="https://www.google.com/")
    view(visitor="b", at=now, path="/blog/second", country="SE", properties={"plan": "pro"})
    view(visitor="c", at=now, path="/pricing", country="NO")


def _chips(body):
    return re.findall(r'<span class="chip" data-dimension-chip=.*?</button>', body, re.S)


def _pageviews(body):
    """The number in the Total Pageviews tile."""
    return int(
        re.search(r"Total Pageviews.*?stat-value[^>]*>\s*([\d,]+)", body, re.S)
        .group(1).replace(",", "")
    )


class TestTheAnalyticsPage:
    def test_a_condition_other_than_is_is_spelled_out_on_its_chip(
        self, owner_client, website, traffic
    ):
        page = f"/dashboard/website/{website['id']}"

        body = owner_client.get(page + "?page__contains=/blog&country__not=NO&country=SE").text

        chips = {re.search(r'data-filter="([^"]+)"', chip).group(1): chip for chip in _chips(body)}
        assert set(chips) == {"page__contains", "country__not", "country"}
        assert "Page contains" in chips["page__contains"]
        assert "/blog" in chips["page__contains"]
        assert "Country is not" in chips["country__not"]
        assert "Norway" in chips["country__not"]
        # "is" reads as it always did: the dimension and the value.
        assert re.search(r'class="chip-key">Country</span>', chips["country"])
        assert 'data-filter="page" data-value="/pricing"' not in body

    def test_the_refresh_and_the_export_carry_every_filter(self, owner_client, website, traffic):
        page = f"/dashboard/website/{website['id']}"
        query = "?page__contains=%2Fblog&country__not=NO&properties=%7B%22plan%22%3A%22pro%22%7D"

        body = owner_client.get(page + query).text

        refresh = body.split('id="stats-basic"')[1].split(">")[0]
        export = re.search(r'href="([^"]*export-csv[^"]*)"', body).group(1)
        for address in (refresh, export):
            assert "page__contains=/blog" in address
            assert "country__not=NO" in address
            # The property filter was left out of the refresh, so ten seconds
            # after a filtered page loaded its headline numbers were everyone's.
            assert "properties=%7B%22plan%22" in address

    def test_the_refresh_answers_with_the_filtered_numbers(self, owner_client, website, traffic):
        partial = f"/dashboard/website/{website['id']}/stats-basic"

        everything = owner_client.get(partial).text
        blog = owner_client.get(partial + "?page__contains=blog").text
        not_sweden = owner_client.get(partial + "?country__not=SE").text
        pro = owner_client.get(partial + "?properties=%7B%22plan%22%3A%22pro%22%7D").text

        assert [_pageviews(body) for body in (everything, blog, not_sweden, pro)] == [3, 2, 1, 1]

    def test_the_dialog_offers_every_dimension_and_its_operators(
        self, owner_client, website, traffic
    ):
        body = owner_client.get(f"/dashboard/website/{website['id']}").text

        dialog = body.split("data-filter-dialog")[1].split("Apply filter")[0]
        for dimension in DIMENSIONS.values():
            assert f'<option value="{dimension.name}">{dimension.label}</option>' in dialog
        assert '<option value="property">Custom property</option>' in dialog
        for operator in ("is", "is_not", "contains", "not_contains"):
            assert f'<option value="{operator}"' in dialog
        state = json.loads(
            re.search(r'id="page-state-data">(.*?)</script>', body, re.S).group(1)
        )
        assert state["filter_operators"]["country"] == ["is", "is_not"]
        assert "page__not_contains" in state["filter_keys"]
        assert "country__contains" not in state["filter_keys"]
        assert state["filter_suffixes"]["contains"] == "__contains"

    def test_a_typed_value_reaches_the_page_escaped(self, owner_client, website, traffic):
        hostile = '"><img src=x onerror=alert(1)>'

        response = owner_client.get(
            f"/dashboard/website/{website['id']}", params={"page__contains": hostile}
        )

        assert response.status_code == 200
        assert "<img src=x" not in response.text
        state = json.loads(
            re.search(r'id="page-state-data">(.*?)</script>', response.text, re.S).group(1)
        )
        assert state["filters"]["page__contains"] == hostile

    @pytest.mark.parametrize("properties", ["[1]", '"x"', '{"a": {"b": 1}}', "{"])
    def test_a_malformed_property_filter_is_ignored_not_an_error(
        self, owner_client, website, traffic, properties
    ):
        response = owner_client.get(
            f"/dashboard/website/{website['id']}", params={"properties": properties}
        )
        assert response.status_code == 200
        assert not _chips(response.text)

    def test_the_tables_under_the_cards_follow_the_filter(
        self, owner_client, db, website, traffic
    ):
        for visitor in ("a", "c"):
            db.execute(
                text(
                    "INSERT INTO custom_events (website_id, event_name, visitor_hash, timestamp) "
                    "VALUES (:w, :n, :v, now() - interval '30 minutes')"
                ),
                {"w": website["id"], "n": f"signup_by_{visitor}", "v": visitor},
            )
        db.commit()
        page = f"/dashboard/website/{website['id']}"

        assert "signup_by_c" in owner_client.get(page).text
        filtered = owner_client.get(page + "?country=SE").text
        assert "signup_by_a" in filtered
        assert "signup_by_c" not in filtered


class TestTheExport:
    def test_the_file_is_the_filtered_report_and_says_so(self, owner_client, website, traffic):
        export = f"/dashboard/website/{website['id']}/export-csv"

        rows = list(csv.reader(io.StringIO(
            owner_client.get(export + "?page__contains=/blog&country__not=NO").text
        )))

        assert ["Total Pageviews", "2"] in rows
        assert ["Filter:", "Page contains", "/blog"] in rows
        assert ["Filter:", "Country is not", "NO"] in rows
        assert not any(row and row[0] == "/pricing" for row in rows)

    def test_an_unfiltered_export_is_the_file_it_always_was(self, owner_client, website, traffic):
        rows = list(csv.reader(io.StringIO(
            owner_client.get(f"/dashboard/website/{website['id']}/export-csv").text
        )))
        assert ["Total Pageviews", "3"] in rows
        assert not any(row and row[0] == "Filter:" for row in rows)


class TestTheJsonApi:
    def test_statistics_take_the_same_parameters(self, owner_client, website, traffic):
        url = f"/api/v1/analytics/stats/{website['id']}"

        def pageviews(query=""):
            response = owner_client.get(url + query)
            assert response.status_code == 200, response.text[:300]
            return response.json()["total_pageviews"]

        assert pageviews() == 3
        assert pageviews("?country=SE") == 2
        assert pageviews("?country__not=SE") == 1
        assert pageviews("?page__contains=BLOG&referrer__contains=google") == 1
        assert pageviews("?properties=%7B%22plan%22%3A%22pro%22%7D") == 1

    def test_goals_and_events_take_them_too(self, owner_client, db, website, goal, traffic):
        for visitor in ("a", "c"):
            db.execute(
                text(
                    "INSERT INTO goal_conversions (goal_id, website_id, visitor_hash, timestamp) "
                    "VALUES (:g, :w, :v, now() - interval '30 minutes')"
                ),
                {"g": goal["id"], "w": website["id"], "v": visitor},
            )
            db.execute(
                text(
                    "INSERT INTO custom_events (website_id, event_name, visitor_hash, timestamp) "
                    "VALUES (:w, 'signup', :v, now() - interval '30 minutes')"
                ),
                {"w": website["id"], "v": visitor},
            )
        db.commit()

        goals = f"/api/v1/analytics/goals/{website['id']}"
        assert owner_client.get(goals).json()["goals"][0]["conversions"] == 2
        narrowed = owner_client.get(goals + "?country=SE").json()
        assert narrowed["goals"][0]["conversions"] == 1
        assert narrowed["total_visitors"] == 2

        events = f"/api/v1/analytics/custom-events/{website['id']}"
        assert owner_client.get(events).json()["total_events"] == 2
        assert owner_client.get(events + "?page__contains=pricing").json()["total_events"] == 1
        assert owner_client.get(events + "/signup").json()["total_count"] == 2
        assert owner_client.get(events + "/signup?country__not=SE").json()["total_count"] == 1

    def test_funnel_and_revenue_take_them_too(self, owner_client, db, website, traffic):
        funnel = Funnel(
            website_id=website["id"], name="F", is_active=True,
            steps=[{"step": 1, "name": "Blog", "path": "/blog"}],
        )
        db.add(funnel)
        db.commit()
        for visitor in ("a", "c"):
            db.execute(
                text(
                    'INSERT INTO funnel_events (funnel_id, visitor_id, step_number, step_name, path, "timestamp", completed) '
                    "VALUES (:f, :v, 1, 'x', '/', now() - interval '30 minutes', false)"
                ),
                {"f": funnel.id, "v": visitor},
            )
            db.execute(
                text(
                    "INSERT INTO ecommerce_events (website_id, event_type, event_name, "
                    " transaction_id, revenue, currency, product_id, product_name, quantity, "
                    " visitor_hash, timestamp) "
                    "VALUES (:w, 'purchase', 'purchase', :v, 50, 'SEK', :v, :v, 1, :v, "
                    "        now() - interval '30 minutes')"
                ),
                {"w": website["id"], "v": visitor},
            )
        db.commit()

        stats = f"/api/v1/funnels/{funnel.id}/stats"
        assert owner_client.get(stats).json()["total_visitors"] == 2
        assert owner_client.get(stats + "?country=SE").json()["total_visitors"] == 1

        revenue = f"/api/v1/revenue/{website['id']}"
        assert float(owner_client.get(revenue + "?currency=SEK").json()["total_revenue"]) == 100
        assert float(
            owner_client.get(revenue + "?currency=SEK&country=SE").json()["total_revenue"]
        ) == 50
        products = owner_client.get(revenue + "/products?currency=SEK&country__not=SE").json()
        assert [p["product_name"] for p in products["products"]] == ["c"]
        chart = owner_client.get(revenue + "/chart?currency=SEK&page__contains=pricing").json()
        assert chart["total_revenue"] == 50


class TestTheSharedDashboardHasNoFilters:
    """A share link shows the lists its owner chose to publish, and no more.
    A filter in its address would let a stranger ask what the lists do not
    say: whether an unlisted page exists, or what a custom property holds."""

    def test_a_filter_in_the_address_changes_nothing(self, client, shared_website, traffic):
        public = f"/public/{shared_website['share_token']}"

        plain = client.get(public)
        assert plain.status_code == 200
        for query in ("?country=NO", "?page__contains=pricing", "?country__not=SE",
                      "?properties=%7B%22plan%22%3A%22pro%22%7D"):
            filtered = client.get(public + query).text
            assert "/blog/first" in filtered, query
            assert 'data-dimension-chip' not in filtered
            assert "data-filter-dialog" not in filtered
            assert _stat_numbers(filtered) == _stat_numbers(plain.text), query

    def test_the_pulse_ignores_them_too(self, client, shared_website, traffic):
        pulse = f"/public/{shared_website['share_token']}/pulse.json"
        assert client.get(pulse + "?country=NO").json()["month"]["pageviews"] == 3


def _stat_numbers(body):
    """Every number shown in a headline tile, in order."""
    return re.findall(r'class="stat-value[^"]*"[^>]*>\s*([^<\s]+)', body)
