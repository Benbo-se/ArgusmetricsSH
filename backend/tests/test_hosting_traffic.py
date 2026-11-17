"""Traffic from hosting providers is labelled, stored and not counted (#103).

Crawlers that run JavaScript behind an ordinary Chrome user agent were counted
as visitors, and no user-agent filter can see them. What is checked here is
the whole of what replaces that:

  at collection   a pageview from a listed network gets a label and nothing
                  follows from it; an event, a purchase or a scroll depth from
                  there is not recorded; and the client is answered exactly as
                  a visitor is, so a crawler cannot tell
  in reports      a labelled row is in no number anywhere
  per website     with the switch off it is in all of them again

The reports are compared as one dictionary of everything the product shows,
taken once with the switch on and once with it off, so a report added later
and forgotten here shows up as a missing key in a review and not as a crawler
on somebody's dashboard.

The addresses are real public ones because the code under test refuses to
look up a private or documentation address: 5.9.1.1 and 2a01:4f8::1 are in
Hetzner's ranges in the fixture file, 81.224.1.1 is a Swedish broadband
address in no range at all.
"""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from tests.conftest import count
from tests.test_debug_console import _console, _next_debug_event
from tests.test_live_dashboard import _live, _next

BROWSER = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
HOSTING = "5.9.1.1"
HOSTING_V6 = "2a01:4f8::1"
HOME = "81.224.1.1"


@pytest.fixture
def ranges(db):
    """Hetzner's two ranges and nothing else, replacing whatever is loaded."""
    db.execute(text("DELETE FROM hosting_network_ranges"))
    db.execute(
        text(
            "INSERT INTO hosting_network_ranges (start_ip, end_ip) VALUES "
            "('5.9.0.0', '5.9.255.255'),"
            "('2a01:4f8::', '2a01:4f8:ffff:ffff:ffff:ffff:ffff:ffff')"
        )
    )
    db.commit()


@pytest.fixture
def from_address(monkeypatch):
    """Make the tracking endpoints see a request as coming from an address.

    The test client has no address of its own, and trusting a forwarded
    header takes a configured proxy. This replaces the one function every
    tracking endpoint asks.
    """
    def use(address):
        monkeypatch.setattr(
            "app.routers.analytics.get_client_ip", lambda request: address
        )
    return use


def switch_off(db, website):
    db.execute(
        text("UPDATE websites SET exclude_datacenter = false WHERE id = :w"),
        {"w": website["id"]},
    )
    db.commit()
    # The test's one session outlives the request that would have loaded the
    # website afresh, so forget what it remembers of the row.
    db.expire_all()


def track(client, website, path="/", **extra):
    return client.post(
        "/api/v1/analytics/track",
        json={"tracking_code": website["tracking_code"], "path": path, **extra},
        headers={"User-Agent": BROWSER},
    )


def label_of(db, website, path):
    return db.execute(
        text("SELECT traffic_class FROM pageviews WHERE website_id = :w AND path = :p"),
        {"w": website["id"], "p": path},
    ).scalars().all()


def usage(db, website):
    return db.execute(
        text(
            "SELECT events FROM account_usage WHERE owner_email = :e "
            "AND period_start = date_trunc('month', now())::date"
        ),
        {"e": website["email"]},
    ).scalar() or 0


def funnel(db, website):
    funnel_id = db.execute(
        text(
            "INSERT INTO funnels (website_id, name, steps, is_active, created_at) "
            "VALUES (:w, 'Signup', CAST(:s AS json), true, now()) RETURNING id"
        ),
        {
            "w": website["id"],
            "s": '[{"step":1,"name":"Pricing","path":"/pricing"},'
                 '{"step":2,"name":"Signup","path":"/signup"}]',
        },
    ).scalar()
    db.commit()
    return funnel_id


class TestLabellingAtCollection:
    def test_a_hosting_address_is_labelled(self, client, db, website, ranges, from_address):
        from_address(HOSTING)
        assert track(client, website, "/crawled").status_code == 200

        assert label_of(db, website, "/crawled") == ["datacenter"]

    def test_an_ipv6_hosting_address_is_labelled(self, client, db, website, ranges, from_address):
        from_address(HOSTING_V6)
        track(client, website, "/crawled")

        assert label_of(db, website, "/crawled") == ["datacenter"]

    def test_an_ordinary_address_is_not(self, client, db, website, ranges, from_address):
        from_address(HOME)
        track(client, website, "/read")

        assert label_of(db, website, "/read") == [None]

    @pytest.mark.parametrize("address", ["5.8.255.255", "5.10.0.0", "2a01:4f9::"])
    def test_the_address_next_to_a_range_is_not(self, client, db, website, ranges, from_address, address):
        from_address(address)
        track(client, website, "/neighbour")

        assert label_of(db, website, "/neighbour") == [None]

    def test_only_the_label_is_stored(self, client, db, website, ranges, from_address):
        """Not the address, not the network and not the provider: the promise
        is that the address is never kept, and one word is the least that
        does the job."""
        from_address(HOSTING)
        track(client, website, "/crawled")

        row = db.execute(
            text("SELECT to_jsonb(p)::text FROM pageviews p WHERE website_id = :w"),
            {"w": website["id"]},
        ).scalar()
        assert '"traffic_class": "datacenter"' in row
        for kept in (HOSTING, "5.9.1", "24940", "Hetzner", "hetzner"):
            assert kept not in row, f"{kept} was stored with the pageview"

    def test_with_nothing_loaded_nothing_is_labelled(self, client, db, website, from_address):
        """An instance that never fetched the file behaves as it always did."""
        db.execute(text("DELETE FROM hosting_network_ranges"))
        db.commit()
        from_address(HOSTING)
        track(client, website, "/as-before")

        assert label_of(db, website, "/as-before") == [None]

    def test_switched_off_for_the_instance_nothing_is_labelled(
        self, client, db, website, ranges, from_address, monkeypatch
    ):
        from app.config import settings

        monkeypatch.setattr(settings, "DATACENTER_FILTER", False)
        from_address(HOSTING)
        track(client, website, "/as-before")

        assert label_of(db, website, "/as-before") == [None]

    def test_an_address_that_is_not_one_still_records_the_pageview(
        self, client, db, website, ranges, from_address
    ):
        from_address("unknown")
        assert track(client, website, "/odd").status_code == 200

        assert label_of(db, website, "/odd") == [None]


class TestTheClientCannotTell:
    def test_the_answer_is_the_same_either_way(self, client, db, website, ranges, from_address):
        from_address(HOME)
        visitor = track(client, website, "/")
        from_address(HOSTING)
        crawler = track(client, website, "/")

        assert label_of(db, website, "/").count("datacenter") == 1, (
            "the second request was not labelled, so this compares nothing"
        )
        assert crawler.status_code == visitor.status_code == 200
        assert crawler.content == visitor.content
        # Per-request values: an id, a timing, and the nonce inside the policy.
        ignore = {"x-request-id", "x-process-time", "date", "content-security-policy"}
        assert {k: v for k, v in crawler.headers.items() if k not in ignore} == {
            k: v for k, v in visitor.headers.items() if k not in ignore
        }

    def test_over_the_limit_it_is_refused_like_anyone_else(
        self, client, db, website, ranges, from_address, monkeypatch
    ):
        """The other answer a client can get. A full account refuses a
        crawler with the same 429, and stores nothing for it."""
        from app.config import settings

        from_address(HOME)
        track(client, website, "/fills-it")
        monkeypatch.setattr(settings, "MONTHLY_EVENT_LIMIT", 1)

        visitor = track(client, website, "/over")
        from_address(HOSTING)
        crawler = track(client, website, "/over")

        assert crawler.status_code == visitor.status_code == 429
        assert crawler.content == visitor.content
        assert label_of(db, website, "/over") == []


class TestNothingFollowsFromALabelledPageview:
    def test_no_funnel_step(self, client, db, website, ranges, from_address):
        funnel_id = funnel(db, website)

        from_address(HOSTING)
        track(client, website, "/pricing")
        assert count(db, "funnel_events", funnel_id=funnel_id) == 0

        from_address(HOME)
        track(client, website, "/pricing")
        assert count(db, "funnel_events", funnel_id=funnel_id) == 1, (
            "the control: a visitor on the same page reaches the step"
        )

    def test_nothing_is_charged_to_the_monthly_limit(self, client, db, website, ranges, from_address):
        before = usage(db, website)

        from_address(HOSTING)
        track(client, website, "/crawled")
        assert label_of(db, website, "/crawled") == ["datacenter"]
        assert usage(db, website) == before

        from_address(HOME)
        track(client, website, "/read")
        assert usage(db, website) == before + 1, "the control: a visitor is counted"

    def test_the_live_view_is_not_told(self, client, db, website, ranges, from_address):
        with _live(client, db, website) as ws:
            from_address(HOSTING)
            track(client, website, "/crawled")
            with pytest.raises(AssertionError, match="no pageview message"):
                _next(ws, "pageview")

            from_address(HOME)
            track(client, website, "/read")
            assert _next(ws, "pageview")["path"] == "/read"

    def test_the_debug_console_says_what_happened_to_it(self, client, db, website, ranges, from_address):
        """Stored, not counted, and why: the console is where the owner asks
        why a visit is not on the dashboard."""
        with _console(client, db, website) as ws:
            from_address(HOSTING)
            track(client, website, "/crawled")
            line = _next_debug_event(ws)

        assert line["outcome"] == "recorded"
        assert line["detail"] == "Hosting provider address: stored, not counted"
        assert line["metadata"]["ip"] == "5.9.1.0", "the console gets the truncated address, as always"


class TestOtherEndpointsRecordNothing:
    def test_no_custom_event_and_no_goal(self, client, db, website, goal, ranges, from_address):
        body = {
            "tracking_code": website["tracking_code"],
            "event_name": goal["event_name"],
            "properties": {"plan": "pro"},
        }

        from_address(HOSTING)
        response = client.post("/api/v1/analytics/track-event", json=body, headers={"User-Agent": BROWSER})
        assert response.status_code == 200
        assert response.json()["message"] == "Tracking skipped (Bot)", (
            "answered the way a user-agent bot is answered on this endpoint"
        )
        assert count(db, "custom_events", website_id=website["id"]) == 0
        assert count(db, "goal_conversions", website_id=website["id"]) == 0

        from_address(HOME)
        client.post("/api/v1/analytics/track-event", json=body, headers={"User-Agent": BROWSER})
        assert count(db, "custom_events", website_id=website["id"]) == 1
        assert count(db, "goal_conversions", website_id=website["id"]) == 1

    def test_no_purchase(self, client, db, website, ranges, from_address):
        body = {
            "tracking_code": website["tracking_code"],
            "event_type": "purchase",
            "transaction_id": f"order-{uuid.uuid4().hex[:8]}",
            "revenue": 100,
            "currency": "SEK",
        }

        from_address(HOSTING)
        response = client.post("/api/v1/analytics/track-ecommerce", json=body, headers={"User-Agent": BROWSER})
        assert response.status_code == 200
        assert response.json()["message"] == "Tracking skipped (Bot)"
        assert count(db, "ecommerce_events", website_id=website["id"]) == 0

        from_address(HOME)
        client.post("/api/v1/analytics/track-ecommerce", json=body, headers={"User-Agent": BROWSER})
        assert count(db, "ecommerce_events", website_id=website["id"]) == 1

    def test_no_scroll_depth(self, client, db, website, ranges, from_address):
        from_address(HOSTING)
        track(client, website, "/long-read")
        response = client.post(
            "/api/v1/analytics/track-scroll",
            json={"tracking_code": website["tracking_code"], "path": "/long-read", "depth": 80},
            headers={"User-Agent": BROWSER},
        )

        assert response.json()["message"] == "Tracking skipped (Bot)"
        depth = db.execute(
            text("SELECT scroll_depth FROM pageviews WHERE website_id = :w"),
            {"w": website["id"]},
        ).scalar()
        assert depth is None

    def test_the_debug_console_says_why_an_event_was_skipped(
        self, client, db, website, ranges, from_address
    ):
        with _console(client, db, website) as ws:
            from_address(HOSTING)
            client.post(
                "/api/v1/analytics/track-event",
                json={"tracking_code": website["tracking_code"], "event_name": "signup"},
                headers={"User-Agent": BROWSER},
            )
            line = _next_debug_event(ws)

        assert line["outcome"] == "skipped"
        assert line["detail"] == "Hosting provider address"

    def test_an_unknown_tracking_code_is_still_reported_as_one(
        self, client, db, ranges, from_address
    ):
        from_address(HOSTING)
        response = client.post(
            "/api/v1/analytics/track-event",
            json={"tracking_code": "zzzzzzzz", "event_name": "signup"},
            headers={"User-Agent": BROWSER},
        )
        assert response.status_code == 400
        assert "invalid tracking code" in str(response.json()).lower()


class TestAWebsiteThatTurnedItOff:
    """For a site whose real audience reaches it through a cloud proxy."""

    def test_the_pageview_is_still_labelled(self, client, db, website, ranges, from_address):
        """So that turning it back on leaves the history out again."""
        switch_off(db, website)
        from_address(HOSTING)
        track(client, website, "/intranet")

        assert label_of(db, website, "/intranet") == ["datacenter"]

    def test_everything_follows_from_it_as_from_any_visit(
        self, client, db, website, goal, ranges, from_address
    ):
        switch_off(db, website)
        funnel_id = funnel(db, website)
        from_address(HOSTING)

        with _live(client, db, website) as ws:
            track(client, website, "/pricing")
            assert _next(ws, "pageview")["path"] == "/pricing"
        client.post(
            "/api/v1/analytics/track-event",
            json={"tracking_code": website["tracking_code"], "event_name": goal["event_name"]},
            headers={"User-Agent": BROWSER},
        )
        client.post(
            "/api/v1/analytics/track-scroll",
            json={"tracking_code": website["tracking_code"], "path": "/pricing", "depth": 70},
            headers={"User-Agent": BROWSER},
        )

        assert count(db, "funnel_events", funnel_id=funnel_id) == 1
        assert count(db, "custom_events", website_id=website["id"]) == 1
        assert count(db, "goal_conversions", website_id=website["id"]) == 1
        assert db.execute(
            text("SELECT scroll_depth FROM pageviews WHERE website_id = :w"),
            {"w": website["id"]},
        ).scalar() == 70

    def test_the_resolver_hands_recording_the_switch(self, db, website):
        from app.services.website_lookup import resolve_tracking_code

        assert resolve_tracking_code(db, website["tracking_code"]).exclude_datacenter is True
        switch_off(db, website)
        assert resolve_tracking_code(db, website["tracking_code"]).exclude_datacenter is False


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------

def _pageview(db, website_id, visitor, path, minutes_ago, label=None, country="SE",
              referrer="https://news.example.org/", properties=None):
    db.execute(
        text(
            'INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp", browser,'
            "  device_type, country, referrer, traffic_class, properties) "
            "VALUES (:w, :p, :h, now() - make_interval(mins => :m), 'Chrome', 'desktop',"
            "        :c, :r, :label, CAST(:props AS jsonb))"
        ),
        {"w": website_id, "p": path, "h": visitor, "m": minutes_ago, "c": country,
         "r": referrer, "label": label, "props": properties},
    )


@pytest.fixture
def traffic(db, shared_website):
    """One reader with two pageviews, and three crawlers with one each.

    Everything about the crawlers is unlike the reader, so wherever one of
    them is counted it shows: another page, another country, another
    referrer, a property of their own, and a custom event that could only be
    theirs.
    """
    wid = shared_website["id"]
    _pageview(db, wid, "reader", "/", 4)
    _pageview(db, wid, "reader", "/pricing", 3)
    for n in (1, 2, 3):
        _pageview(
            db, wid, f"crawler-{n}", "/crawled", 2, label="datacenter", country="SG",
            referrer="https://crawl.example.net/", properties='{"seen_by": "crawler"}',
        )
    db.execute(
        text(
            "INSERT INTO custom_events (website_id, event_name, visitor_hash, timestamp) "
            "VALUES (:w, 'signup', 'crawler-1', now() - interval '2 minutes')"
        ),
        {"w": wid},
    )
    db.commit()
    return shared_website


def everything_shown(db, client, owner_client, website):
    """Every number and list the product derives from pageviews, in one place."""
    from app.models.custom_event import CustomEvent
    from app.services.analytics_service import AnalyticsService
    from app.services.anomaly_detection_service import AnomalyDetectionService
    from app.services.email_reports_service import EmailReportsService
    from app.services.filters import FilterSet
    from app.services.goals_service import goal_conversion_stats
    from app.services.site_activity import recent_activity

    wid = website["id"]
    now = datetime.now(timezone.utc)
    start, end = now - timedelta(days=1), now + timedelta(minutes=1)
    service = AnalyticsService(db)
    shown = {}

    # The dashboard: headline numbers, the graph, and every list on the page.
    stats = service.get_dashboard_stats(website_id=wid, start_date=start, end_date=end)
    shown["pageviews"] = stats["total_pageviews"]
    shown["visitors"] = stats["unique_visitors"]
    shown["visits"] = stats["total_visits"]
    shown["series by day"] = sum(point["views"] for point in stats["timeseries"])
    shown["top pages"] = sorted(p["path"] for p in stats["top_pages"])
    shown["entry pages"] = sorted(p["path"] for p in stats["entry_pages"])
    shown["exit pages"] = sorted(p["path"] for p in stats["exit_pages"])
    shown["referrers"] = sorted(r["referrer"] for r in stats["top_referrers"])
    shown["countries"] = sorted(c["country"] for c in stats["top_countries"])
    shown["channels"] = sum(c["views"] for c in stats["traffic_channels"])
    shown["devices"] = sum(stats["devices"].values())
    shown["browsers"] = sum(b["views"] for b in stats["top_browsers"])
    shown["goal visitors"] = stats["total_visitors"]

    hourly = service.get_dashboard_stats(
        website_id=wid, start_date=start, end_date=end, bucket="hour"
    )
    shown["series by hour"] = sum(point["views"] for point in hourly["timeseries"])

    # The comparison's previous period, by asking for the day after as the
    # current one.
    later = service.get_dashboard_stats(
        website_id=wid, start_date=end + timedelta(seconds=1),
        end_date=end + (end - start) + timedelta(seconds=1), compare=True,
    )
    shown["previous period"] = later["comparison"]["prev_pageviews"]

    # Realtime.
    live = service.get_realtime_stats(website_id=wid)
    shown["online now"] = live["current_visitors"]
    shown["last hour"] = live["recent_pageviews"]
    shown["live list"] = sorted({v["path"] for v in live["live_visitors"]})

    # Conversion rates are a share of these, and a filtered report on events,
    # goals, funnels or revenue picks its visitors through these.
    shown["rate denominator"] = goal_conversion_stats(db, wid, start)["visitors"]
    shown["events of visitors on /crawled"] = db.execute(
        select(func.count()).select_from(CustomEvent).where(
            CustomEvent.website_id == wid,
            *FilterSet.of(page="/crawled").visitor_conditions(
                CustomEvent.visitor_hash, wid, start
            ),
        )
    ).scalar()
    shown["property keys"] = sorted(service.get_available_properties(wid, start, end))

    # The card on the list of websites.
    card = recent_activity(db, [wid])[wid]
    shown["card week"] = card["week"]
    shown["card online"] = card["online"]

    # The emailed report, and what the alert and anomaly checks measure.
    report = EmailReportsService(db).generate_report_data(wid, "weekly")
    shown["report pageviews"] = report["total_pageviews"]
    shown["report visitors"] = report["unique_visitors"]
    shown["report pages"] = sorted(p["path"] for p in report["top_pages"])
    shown["report countries"] = sorted(c["country"] for c in report["top_countries"])
    shown["anomaly baseline"] = round(
        AnomalyDetectionService(db)._get_baseline_metrics(wid, hours=24)["avg_pageviews_per_hour"] * 24
    )

    # The exports.
    day = now.strftime("%Y-%m-%d")
    window = f"start_date={(now - timedelta(days=1)).strftime('%Y-%m-%d')}&end_date={day}"
    rows = list(csv.reader(io.StringIO(
        owner_client.get(f"/api/v1/analytics/export/{wid}/csv?{window}").text
    )))
    shown["csv rows"] = len(rows) - 1
    shown["json rows"] = len(
        owner_client.get(f"/api/v1/analytics/export/{wid}/json?{window}").json()["pageviews"]
    )
    report_csv = owner_client.get(f"/dashboard/website/{wid}/export-csv?range=7d").text
    shown["dashboard csv"] = "/crawled" in report_csv
    shown["api stats"] = owner_client.get(
        f"/api/v1/analytics/stats/{wid}?{window}"
    ).json()["total_pageviews"]

    # The pages themselves.
    shown["dashboard page"] = "/crawled" in owner_client.get(f"/dashboard/website/{wid}?range=7d").text
    shown["public page"] = "/crawled" in client.get(f"/public/{website['share_token']}?range=7d").text
    pulse = client.get(f"/public/{website['share_token']}/pulse.json").json()
    shown["pulse pageviews"] = pulse["month"]["pageviews"]
    shown["pulse online"] = pulse["online"]
    shown["pulse pages"] = sorted(p["path"] for p in pulse["top_pages"])
    return shown


READER_ONLY = {
    "pageviews": 2, "visitors": 1, "visits": 1,
    "series by day": 2, "series by hour": 2, "previous period": 2,
    "top pages": ["/", "/pricing"], "entry pages": ["/"], "exit pages": ["/pricing"],
    "referrers": ["https://news.example.org/"], "countries": ["SE"],
    "channels": 2, "devices": 2, "browsers": 2, "goal visitors": 1,
    "online now": 1, "last hour": 2, "live list": ["/", "/pricing"],
    "rate denominator": 1, "events of visitors on /crawled": 0, "property keys": [],
    "card week": 1, "card online": 1,
    "report pageviews": 2, "report visitors": 1, "report pages": ["/", "/pricing"],
    "report countries": ["SE"], "anomaly baseline": 2,
    "csv rows": 2, "json rows": 2, "dashboard csv": False, "api stats": 2,
    "dashboard page": False, "public page": False,
    "pulse pageviews": 2, "pulse online": 1, "pulse pages": ["/", "/pricing"],
}

WITH_THE_CRAWLERS = {
    "pageviews": 5, "visitors": 4, "visits": 4,
    "series by day": 5, "series by hour": 5, "previous period": 5,
    "top pages": ["/", "/crawled", "/pricing"],
    "entry pages": ["/", "/crawled"], "exit pages": ["/crawled", "/pricing"],
    "referrers": ["https://crawl.example.net/", "https://news.example.org/"],
    "countries": ["SE", "SG"],
    "channels": 5, "devices": 5, "browsers": 5, "goal visitors": 4,
    "online now": 4, "last hour": 5, "live list": ["/", "/crawled", "/pricing"],
    "rate denominator": 4, "events of visitors on /crawled": 1,
    "property keys": ["seen_by"],
    "card week": 4, "card online": 4,
    "report pageviews": 5, "report visitors": 4,
    "report pages": ["/", "/crawled", "/pricing"],
    "report countries": ["SE", "SG"], "anomaly baseline": 5,
    "csv rows": 5, "json rows": 5, "dashboard csv": True, "api stats": 5,
    "dashboard page": True, "public page": True,
    "pulse pageviews": 5, "pulse online": 4, "pulse pages": ["/", "/crawled", "/pricing"],
}


class TestReports:
    def test_a_labelled_pageview_is_in_no_report(self, db, client, owner_client, traffic):
        assert everything_shown(db, client, owner_client, traffic) == READER_ONLY

    def test_with_the_switch_off_it_is_in_all_of_them(self, db, client, owner_client, traffic):
        switch_off(db, traffic)

        assert everything_shown(db, client, owner_client, traffic) == WITH_THE_CRAWLERS

    def test_turning_it_back_on_takes_them_out_again(self, db, client, owner_client, traffic):
        """The label was written either way, so the switch works on history."""
        switch_off(db, traffic)
        db.execute(
            text("UPDATE websites SET exclude_datacenter = true WHERE id = :w"),
            {"w": traffic["id"]},
        )
        db.commit()

        assert everything_shown(db, client, owner_client, traffic) == READER_ONLY

    def test_one_websites_switch_is_not_anothers(self, db, traffic, second_website):
        from app.services.site_activity import recent_activity

        _pageview(db, second_website["id"], "crawler-9", "/crawled", 2, label="datacenter")
        _pageview(db, second_website["id"], "reader", "/", 2)
        db.commit()
        switch_off(db, second_website)

        cards = recent_activity(db, [traffic["id"], second_website["id"]])

        assert cards[traffic["id"]]["week"] == 1
        assert cards[second_website["id"]]["week"] == 2

    def test_a_spike_made_of_crawlers_sends_no_alert(self, db, website):
        """The hourly alert compares this hour with the same hour on the
        seven days before. Fifty crawlers in an hour that usually sees one
        reader is the upturn #103 was opened about."""
        from app.database import set_rls_context
        from app.services.alert_service import AlertService

        wid = website["id"]
        set_rls_context(db, context="job")
        db.execute(
            text(
                "INSERT INTO alert_settings (website_id, spike_threshold, email_enabled, alert_email) "
                "VALUES (:w, 3.0, true, :e)"
            ),
            {"w": wid, "e": website["email"]},
        )
        for day in range(1, 8):
            _pageview(db, wid, f"reader-{day}", "/", day * 24 * 60 + 30)
        _pageview(db, wid, "reader", "/", 5)
        for n in range(50):
            _pageview(db, wid, f"crawler-{n}", "/crawled", 4, label="datacenter")
        db.commit()

        assert AlertService(db).check_traffic_spike(wid) is None

        switch_off(db, website)
        spike = AlertService(db).check_traffic_spike(wid)
        assert spike and spike["current_hour_views"] == 51, (
            "the control: counted, the same hour is a spike"
        )


class TestTheLineOnTheDashboard:
    def test_it_says_how_much_was_left_out(self, owner_client, traffic):
        page = owner_client.get(f"/dashboard/website/{traffic['id']}?range=7d").text

        assert "3 pageviews from hosting providers are not counted" in page

    def test_one_is_singular(self, owner_client, db, website):
        _pageview(db, website["id"], "reader", "/", 3)
        _pageview(db, website["id"], "crawler", "/crawled", 2, label="datacenter")
        db.commit()

        page = owner_client.get(f"/dashboard/website/{website['id']}?range=7d").text

        assert "1 pageview from a hosting provider is not counted" in page

    def test_it_follows_the_selected_range(self, owner_client, db, website):
        _pageview(db, website["id"], "reader", "/", 3)
        _pageview(db, website["id"], "crawler", "/crawled", 3 * 24 * 60, label="datacenter")
        db.commit()

        today = owner_client.get(f"/dashboard/website/{website['id']}?range=today").text
        week = owner_client.get(f"/dashboard/website/{website['id']}?range=7d").text

        assert "data-hosting-kept-out" not in today
        assert "1 pageview from a hosting provider is not counted" in week

    def test_it_is_absent_when_nothing_was_left_out(self, owner_client, db, website):
        _pageview(db, website["id"], "reader", "/", 3)
        db.commit()

        page = owner_client.get(f"/dashboard/website/{website['id']}?range=7d").text

        assert "data-hosting-kept-out" not in page
        assert "hosting provider" not in page

    def test_it_is_absent_when_the_website_counts_them(self, owner_client, db, traffic):
        switch_off(db, traffic)

        page = owner_client.get(f"/dashboard/website/{traffic['id']}?range=7d").text

        assert "data-hosting-kept-out" not in page

    def test_the_public_dashboard_does_not_say_it(self, client, traffic):
        page = client.get(f"/public/{traffic['share_token']}?range=7d")

        assert page.status_code == 200
        assert "hosting provider" not in page.text


class TestTheSwitchInSettings:
    def test_it_is_on_for_a_new_website(self, db, website):
        assert db.execute(
            text("SELECT exclude_datacenter FROM websites WHERE id = :w"), {"w": website["id"]}
        ).scalar() is True

    def test_the_owner_turns_it_off_and_on(self, owner_client, db, website):
        off = owner_client.put(f"/api/v1/websites/{website['id']}", json={"exclude_datacenter": False})

        assert off.status_code == 200, off.text
        assert off.json()["exclude_datacenter"] is False
        assert db.execute(
            text("SELECT exclude_datacenter FROM websites WHERE id = :w"), {"w": website["id"]}
        ).scalar() is False

        on = owner_client.put(f"/api/v1/websites/{website['id']}", json={"exclude_datacenter": True})
        assert on.json()["exclude_datacenter"] is True

    def test_changing_something_else_leaves_it_alone(self, owner_client, db, website):
        switch_off(db, website)

        owner_client.put(f"/api/v1/websites/{website['id']}", json={"timezone": "Europe/Stockholm"})

        assert db.execute(
            text("SELECT exclude_datacenter FROM websites WHERE id = :w"), {"w": website["id"]}
        ).scalar() is False

    def test_a_viewer_cannot_change_it(self, owner_client, db, website):
        """Owner and admin only, like the name and the time zone."""
        from app.database import set_rls_context
        from app.main import app
        from app.models.user import User
        from app.routers.auth import get_current_user

        viewer = f"viewer-{uuid.uuid4().hex[:8]}@example.com"
        db.execute(
            text("INSERT INTO users (email, is_verified, created_at) VALUES (:e, true, now())"),
            {"e": viewer},
        )
        db.execute(
            text(
                "INSERT INTO website_members (website_id, user_email, role, status, invited_by, invited_at) "
                "VALUES (:w, :e, 'viewer', 'active', :o, now())"
            ),
            {"w": website["id"], "e": viewer, "o": website["email"]},
        )
        db.commit()
        user = db.query(User).filter(User.email == viewer).first()

        def as_viewer():
            set_rls_context(db, context="user", user_email=viewer)
            return user

        app.dependency_overrides[get_current_user] = as_viewer
        response = owner_client.put(
            f"/api/v1/websites/{website['id']}", json={"exclude_datacenter": False}
        )

        assert response.status_code in (403, 404), response.text
        assert db.execute(
            text("SELECT exclude_datacenter FROM websites WHERE id = :w"), {"w": website["id"]}
        ).scalar() is True

    def test_the_settings_page_shows_the_switch_as_it_is(self, owner_client, db, website):
        page = owner_client.get(f"/dashboard/website/{website['id']}/settings").text
        assert 'id="hosting-traffic"' in page
        assert 'data-excluded="true"' in page

        switch_off(db, website)
        page = owner_client.get(f"/dashboard/website/{website['id']}/settings").text
        assert 'data-excluded="false"' in page
