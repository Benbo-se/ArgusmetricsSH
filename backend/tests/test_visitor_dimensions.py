"""Operating system, versions, language, hostname and screen size (#204).

Three things can go wrong here and none of them shows on the screen:

  - a value finer than it should be reaches the table (a full version, a raw
    user agent, a whole Accept-Language list), which is a privacy regression
    nobody sees until someone reads the rows
  - pageviews from before the columns existed, which have NULL in all of
    them, crash a report or silently drop out of it
  - a filter is accepted, shown as a chip, and narrows nothing

So the tracking tests read the row back, and the report tests always include
rows without values.

The cases are tables walked inside a test rather than parametrised: the
README and the home page state a test count, and forty cases of one function
are one thing checked, not forty.
"""
import csv
import io
import pathlib
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services import visitor_dimensions as vd
from app.services.analytics_query_service import AnalyticsQueryService

CHROME_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.6478.127 Safari/537.36"
)
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 "
    "Safari/604.1"
)
FIREFOX_UBUNTU = (
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:128.0) Gecko/20100101 "
    "Firefox/128.0"
)
CHROME_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.6422.165 Mobile Safari/537.36"
)
SAFARI_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15"
)
CHROME_OS = (
    "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
FREEBSD = (
    "Mozilla/5.0 (X11; FreeBSD amd64; rv:120.0) Gecko/20100101 Firefox/120.0"
)


class TestWhatARequestIsReducedTo:
    def test_user_agent_gives_a_family_and_major_versions_only(self):
        cases = [
            (CHROME_WINDOWS, ("Windows", "10", "126")),
            (SAFARI_IPHONE, ("iOS", "17", "17")),
            (CHROME_ANDROID, ("Android", "14", "125")),
            (SAFARI_MAC, ("macOS", "10", "17")),
            # A distribution is one visitor's choice, not an audience.
            (FIREFOX_UBUNTU, ("Linux", None, "128")),
            # The Chrome OS "version" is a build number.
            (CHROME_OS, ("Chrome OS", None, "124")),
            # Recognised and rare: counted, not named.
            (FREEBSD, ("Other", None, "120")),
        ]
        for user_agent, expected in cases:
            got = vd.from_user_agent(user_agent)
            assert (got["os"], got["os_version"], got["browser_version"]) == expected, user_agent
            for key in ("os_version", "browser_version"):
                assert got[key] is None or got[key].isdigit(), (
                    f"{key} is {got[key]!r}: a minor or build number is leaking"
                )

        # Unreadable is unknown, not an error.
        for user_agent in ("", None, "curl/8.5.0", "\x00\x01 nonsense"):
            got = vd.from_user_agent(user_agent)
            assert got["os"] is None and got["os_version"] is None, repr(user_agent)

    def test_language_is_one_tag_as_language_and_region(self):
        cases = [
            ("sv-SE", "sv-SE"),
            ("sv-se", "sv-SE"),
            ("EN", "en"),
            ("en_US", "en-US"),
            ("zh-Hans-CN", "zh-CN"),
            ("sr-Latn", "sr"),
            ("de-DE-u-co-phonebk", "de-DE"),
            ("fil-PH", "fil-PH"),
            # A whole list where one tag belongs: the first, and no more.
            ("en-US,en;q=0.9,sv;q=0.8", "en-US"),
            ("sv;q=0.5", "sv"),
            ("*", None),
            ("", None),
            ("12-34", None),
            ("x" * 40, None),
            (None, None),
            (42, None),
            (["sv"], None),
        ]
        for raw, expected in cases:
            assert vd.normalise_language(raw) == expected, repr(raw)

        header = "en-GB,en;q=0.9,sv;q=0.8,de-CH;q=0.7"
        assert vd.language_from_accept_language(header) == "en-GB"
        assert vd.language_from_accept_language(None) is None
        assert vd.language_from_accept_language("*") is None

    def test_hostname_is_normalised_or_refused(self):
        cases = [
            ("Blog.Example.com", "blog.example.com"),
            ("example.com.", "example.com"),
            ("xn--rksmrgs-5wao1o.se", "xn--rksmrgs-5wao1o.se"),
            ("localhost", "localhost"),
            ("example.com:8080", None),
            ("exa mple.com", None),
            ("<script>", None),
            ("a" * 300 + ".com", None),
            ("", None),
            (None, None),
            (7, None),
        ]
        for raw, expected in cases:
            assert vd.normalise_hostname(raw) == expected, repr(raw)

        assert vd.hostname_from_origin("https://Shop.Example.com:8443") == "shop.example.com"
        assert vd.hostname_from_origin("null") is None
        assert vd.hostname_from_origin(None) is None


def _last_pageview(db, website_id):
    return db.execute(
        text(
            "SELECT * FROM pageviews WHERE website_id = :w ORDER BY id DESC LIMIT 1"
        ),
        {"w": website_id},
    ).mappings().one()


class TestTrackingWritesTheDimensions:
    def _track(self, client, website, body=None, **headers):
        return client.post(
            "/api/v1/analytics/track",
            json={"tracking_code": website["tracking_code"], "path": "/dims", **(body or {})},
            headers={"User-Agent": CHROME_WINDOWS, **headers},
        )

    def test_what_the_tracker_sends_is_stored_reduced(self, client, db, website):
        response = self._track(
            client, website,
            {"language": "sv-se", "hostname": "Blog.Example.com", "screen_width": 1536},
        )

        assert response.status_code == 200, response.text
        row = _last_pageview(db, website["id"])
        assert row["os"] == "Windows"
        assert row["os_version"] == "10"
        assert row["browser"] == "Chrome"
        assert row["browser_version"] == "126"
        assert row["language"] == "sv-SE"
        assert row["hostname"] == "blog.example.com"

        # And the user agent itself is in no column.
        stored = " ".join(str(v) for v in row.values() if v is not None)
        for fragment in ("Mozilla", "AppleWebKit", "6478", "Win64"):
            assert fragment not in stored, f"{fragment!r} from the user agent was stored"

    def test_headers_fill_in_only_what_the_tracker_did_not_send(self, client, db, website):
        """A browser running a cached tracker from before these fields."""
        headers = {
            "Accept-Language": "en-GB,en;q=0.9,sv;q=0.8",
            "Origin": "https://docs.example.com",
        }

        response = self._track(client, website, **headers)

        assert response.status_code == 200, response.text
        row = _last_pageview(db, website["id"])
        assert row["language"] == "en-GB", "only the first preference, reduced"
        assert row["hostname"] == "docs.example.com"

        self._track(
            client, website, {"language": "fi-FI", "hostname": "a.example.com"}, **headers
        )

        row = _last_pageview(db, website["id"])
        assert (row["language"], row["hostname"]) == ("fi-FI", "a.example.com"), (
            "what the tracker sent must win over the header"
        )

    def test_nonsense_costs_the_dimension_and_not_the_pageview(self, client, db, website):
        bodies = [
            {"language": "x" * 500, "hostname": "y" * 5000},
            {"language": 17, "hostname": ["a"]},
            {"language": "!!", "hostname": "evil.example.com/<script>"},
        ]
        for n, body in enumerate(bodies):
            response = client.post(
                "/api/v1/analytics/track",
                json={"tracking_code": website["tracking_code"], "path": f"/n{n}", **body},
                headers={"User-Agent": CHROME_WINDOWS},
            )

            assert response.status_code == 200, (body, response.text)
            row = _last_pageview(db, website["id"])
            assert row["path"] == f"/n{n}", body
            assert row["language"] is None, body
            assert row["hostname"] is None, body

    def test_the_service_reduces_what_a_caller_passes_it_unreduced(self, db, website):
        """The request schema normalises first, and is not the only way in."""
        from app.services.analytics_recording_service import AnalyticsRecordingService

        ok, message = AnalyticsRecordingService(db).record_pageview(
            tracking_code=website["tracking_code"],
            path="/direct",
            referrer=None,
            screen_width=None,
            ip_address="198.51.100.7",
            user_agent=CHROME_WINDOWS,
            language="EN-us,en;q=0.9,sv;q=0.8",
            hostname="Not A Hostname",
        )

        assert ok, message
        row = _last_pageview(db, website["id"])
        assert row["path"] == "/direct"
        assert row["language"] == "en-US"
        assert row["hostname"] is None


ANCHOR = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

COLUMNS = (
    "os", "os_version", "browser", "browser_version", "language", "hostname",
    "screen_width",
)


def _insert(db, website_id, when, visitor, values):
    unknown = set(values) - set(COLUMNS)
    assert not unknown, unknown
    names = "".join(f", {name}" for name in values)
    binds = "".join(f", :{name}" for name in values)
    db.execute(
        text(
            'INSERT INTO pageviews (website_id, path, visitor_hash, "timestamp"'
            f"{names}) VALUES (:w, '/', :h, :t{binds})"
        ),
        {"w": website_id, "h": visitor, "t": when, **values},
    )
    db.commit()


@pytest.fixture
def record(db, website):
    """Insert a pageview with exactly the dimension columns given."""
    counter = {"n": 0}

    def _record(days_ago: int = 0, **values):
        counter["n"] += 1
        _insert(db, website["id"], ANCHOR - timedelta(days=days_ago),
                f"v{counter['n']}", values)
    return _record


@pytest.fixture
def traffic(record):
    """Seven pageviews: five with values, two from before the columns."""
    for _ in range(3):
        record(os="Windows", os_version="10", browser="Chrome", browser_version="126",
               language="sv-SE", hostname="example.com", screen_width=1920)
    record(os="macOS", os_version="10", browser="Safari", browser_version="17",
           language="en-US", hostname="blog.example.com", screen_width=1440)
    record(os="Linux", browser="Firefox", browser_version="128",
           language="sv-SE", hostname="blog.example.com", screen_width=390)
    # Recorded before #204: a browser family and nothing else.
    record(browser="Chrome")
    record(browser="Chrome")


@pytest.fixture
def stats(db, website):
    def _stats(compare=False, **filters):
        return AnalyticsQueryService(db).get_dashboard_stats(
            website_id=website["id"],
            start_date=ANCHOR - timedelta(days=1),
            end_date=ANCHOR + timedelta(days=1),
            compare=compare,
            **({"filter_dimensions": filters} if filters else {}),
        )
    return _stats


def _as_counts(report):
    return {row["value"]: row["views"] for row in report}


class TestReports:
    def test_every_dimension_is_reported_with_older_rows_as_unknown(self, stats, traffic):
        result = stats()
        dimensions = result["dimensions"]

        assert list(dimensions) == list(vd.DIMENSION_NAMES)
        assert _as_counts(dimensions["os"]) == {
            "Windows": 3, "Unknown": 2, "macOS": 1, "Linux": 1,
        }
        assert _as_counts(dimensions["os_version"]) == {
            "Windows 10": 3, "Unknown": 2, "macOS 10": 1, "Linux Unknown": 1,
        }
        assert _as_counts(dimensions["browser_version"]) == {
            "Chrome 126": 3, "Chrome Unknown": 2, "Safari 17": 1, "Firefox 128": 1,
        }
        assert _as_counts(dimensions["language"]) == {
            "sv-SE": 4, "Unknown": 2, "en-US": 1,
        }
        assert _as_counts(dimensions["hostname"]) == {
            "example.com": 3, "blog.example.com": 2, "Unknown": 2,
        }
        assert _as_counts(dimensions["screen"]) == {
            "1920": 3, "Unknown": 2, "1440": 1, "0": 1,
        }

        for name, report in dimensions.items():
            views = [r["views"] for r in report]
            # Leaving the rows without a value out would break exactly this.
            assert sum(views) == result["total_pageviews"] == 7, name
            assert views == sorted(views, reverse=True), f"{name} is not largest first"

        # Screen sizes are ranges and never a pixel count.
        assert {r["value"]: r["label"] for r in dimensions["screen"]} == {
            "1920": "1920 to 2559 px",
            "1440": "1440 to 1919 px",
            "0": "Under 576 px",
            "Unknown": "Unknown",
        }
        labels = {r["value"]: r["label"] for r in dimensions["os_version"]}
        assert labels["Linux Unknown"] == "Linux (unknown version)"

    def test_the_edges_of_a_report(self, stats, record, db, second_website):
        assert stats()["dimensions"] == {name: [] for name in vd.DIMENSION_NAMES}, (
            "an empty range gives empty reports"
        )

        # A width on a boundary belongs to the range it starts, in the report
        # and in the filter alike.
        record(screen_width=767)
        record(screen_width=768)
        record(screen_width=5120)
        labels = {r["label"] for r in stats()["dimensions"]["screen"]}
        assert labels == {"576 to 767 px", "768 to 1023 px", "2560 px and wider"}
        assert stats(screen="576")["total_pageviews"] == 1
        assert stats(screen="768")["total_pageviews"] == 1
        assert stats(screen="2560")["total_pageviews"] == 1

        # No report lists more than ten.
        for i in range(14):
            record(hostname=f"h{i}.example.com")
        assert len(stats()["dimensions"]["hostname"]) == 10

        # Another website's rows stay out.
        _insert(db, second_website["id"], ANCHOR, "x", {"os": "Android"})
        assert "Android" not in _as_counts(stats()["dimensions"]["os"])


class TestFilters:
    def test_a_filter_narrows_to_what_its_report_row_counted(self, stats, traffic):
        cases = [
            ("os", "Windows", 3),
            ("os", "Unknown", 2),
            ("os_version", "Windows 10", 3),
            ("os_version", "macOS 10", 1),
            ("os_version", "Linux Unknown", 1),
            ("os_version", "Unknown", 2),
            ("browser_version", "Chrome 126", 3),
            ("browser_version", "Chrome Unknown", 2),
            ("language", "sv-SE", 4),
            ("language", "Unknown", 2),
            ("hostname", "blog.example.com", 2),
            ("hostname", "Unknown", 2),
            ("screen", "1920", 3),
            ("screen", "0", 1),
            ("screen", "Unknown", 2),
            # Not the start of a range: nothing, rather than everything.
            ("screen", "1921", 0),
            ("screen", "wide", 0),
            ("os", "Solaris", 0),
            # An unset filter is no filter.
            ("os", "", 7),
        ]
        for name, value, expected in cases:
            assert stats(**{name: value})["total_pageviews"] == expected, (name, value)

        # The value a row carries is the value its filter understands.
        for name, report in stats()["dimensions"].items():
            for row in report:
                got = stats(**{name: row["value"]})["total_pageviews"]
                assert got == row["views"], (name, row)

    def test_everything_on_the_page_follows_the_filter(self, stats, traffic, record):
        both = stats(language="sv-SE", hostname="blog.example.com")
        assert both["total_pageviews"] == 1, "filters combine"
        assert _as_counts(both["dimensions"]["os"]) == {"Linux": 1}

        # Three days back, so inside the previous two-day window.
        record(days_ago=3, os="Windows")
        record(days_ago=3, os="macOS")
        record(days_ago=3, os="macOS")

        result = stats(compare=True, os="Windows")

        assert sum(day["views"] for day in result["timeseries"]) == 3, "the graph"
        assert result["comparison"]["prev_pageviews"] == 1, "the previous period"
        assert sum(d["views"] for d in result["timeseries_previous"]) == 1, (
            "the previous period's graph"
        )


def _now_row(db, website_id, **values):
    _insert(db, website_id, datetime.now(timezone.utc) - timedelta(hours=1), "p", values)


class TestDashboardPage:
    def test_it_renders_with_rows_from_before_the_columns(self, owner_client, db, website):
        _now_row(db, website["id"], browser="Chrome")
        _now_row(db, website["id"], os="Windows", os_version="10", browser="Chrome",
                 browser_version="126", language="sv-SE", hostname="example.com",
                 screen_width=1920)
        # A hostname is normalised on the way in; the page must not rely on it.
        _now_row(db, website["id"], hostname='"><img src=x onerror=alert(1)>')

        response = owner_client.get(f"/dashboard/website/{website['id']}")

        assert response.status_code == 200, response.text[:500]
        body = response.text
        for _, title in vd.DIMENSIONS:
            assert title in body
        assert 'data-filter="os" data-value="Windows"' in body
        assert 'data-filter="os" data-value="Unknown"' in body
        assert 'data-filter="os_version" data-value="Windows 10"' in body
        assert 'data-filter="browser_version" data-value="Chrome 126"' in body
        assert 'data-filter="language" data-value="sv-SE"' in body
        assert 'data-filter="hostname" data-value="example.com"' in body
        assert 'data-filter="screen" data-value="1920"' in body
        assert "1920 to 2559 px" in body
        assert "<img src=x" not in body, "a stored value reached the page unescaped"

    def test_a_filter_in_the_address_narrows_the_page_and_its_refresh(
        self, owner_client, db, website
    ):
        for _ in range(3):
            _now_row(db, website["id"], os="Windows", language="sv-SE")
        _now_row(db, website["id"], os="macOS", language="en-US")
        page = f"/dashboard/website/{website['id']}"

        response = owner_client.get(page + "?os=macOS")

        assert response.status_code == 200
        body = response.text
        assert 'data-dimension-chip="os"' in body
        assert 'data-filter="language" data-value="en-US"' in body
        assert 'data-filter="language" data-value="sv-SE"' not in body
        # The ten-second refresh must ask for the same filtered numbers,
        refresh = body.split('id="stats-basic"')[1].split(">")[0]
        assert "os=macOS" in refresh
        # and the partial it asks must answer with them.
        everything = owner_client.get(page + "/stats-basic")
        filtered = owner_client.get(page + "/stats-basic?os=macOS")
        assert everything.status_code == filtered.status_code == 200
        assert everything.text != filtered.text


class TestExportsAndApi:
    def test_the_exports_carry_the_dimensions(self, owner_client, db, website):
        _now_row(db, website["id"], os="Windows", os_version="10", browser="Chrome",
                 browser_version="126", language="sv-SE", hostname="example.com")
        _now_row(db, website["id"])
        wid = website["id"]

        # The dashboard's summary export: a section per dimension.
        response = owner_client.get(f"/dashboard/website/{wid}/export-csv?range=7d")
        assert response.status_code == 200, response.text
        rows = list(csv.reader(io.StringIO(response.text)))
        for _, title in vd.DIMENSIONS:
            assert [title.upper()] in rows, title
        assert ["Windows", "1"] in rows
        assert ["Windows 10", "1"] in rows
        assert ["sv-SE", "1"] in rows
        assert ["Unknown", "1"] in rows

        # The row export: new columns after the old ones.
        response = owner_client.get(f"/api/v1/analytics/export/{wid}/csv")
        assert response.status_code == 200, response.text
        header, *lines = list(csv.reader(io.StringIO(response.text)))
        assert header[:7] == [
            "Timestamp", "Path", "Referrer", "Country", "Device", "Browser", "Visitor Hash",
        ], "existing columns moved; a script reading by position now reads the wrong thing"
        exported = [dict(zip(header, line)) for line in lines]
        got = next(r for r in exported if r["OS"])
        assert got["Browser Version"] == "126"
        assert got["OS"] == "Windows"
        assert got["OS Version"] == "10"
        assert got["Language"] == "sv-SE"
        assert got["Hostname"] == "example.com"

        # The JSON export: the same, and null for the older row.
        response = owner_client.get(f"/api/v1/analytics/export/{wid}/json")
        assert response.status_code == 200, response.text
        older = next(p for p in response.json()["pageviews"] if p["browser"] is None)
        for key in ("os", "os_version", "browser_version", "language", "hostname"):
            assert key in older and older[key] is None, key

    def test_the_stats_api_returns_the_reports(self, owner_client, db, website):
        _now_row(db, website["id"], os="Windows", language="sv-SE", screen_width=800)
        _now_row(db, website["id"])

        response = owner_client.get(f"/api/v1/analytics/stats/{website['id']}")

        assert response.status_code == 200, response.text
        dimensions = response.json()["dimensions"]
        assert set(dimensions) == set(vd.DIMENSION_NAMES)
        assert {"value": "Windows", "label": "Windows", "views": 1} in dimensions["os"]
        assert {"value": "Unknown", "label": "Unknown", "views": 1} in dimensions["os"]
        assert {"value": "768", "label": "768 to 1023 px", "views": 1} in dimensions["screen"]


NEW_COLUMNS = ("os", "os_version", "browser_version", "language", "hostname")


def test_the_columns_are_cheap_to_add_to_a_table_with_data_in_it(db):
    """What makes the migration safe on a hypertable in production.

    A default would be written into every chunk and NOT NULL would scan them;
    nullable without a default is a catalogue change. An index would be a
    write tax on the busiest table for columns of a handful of values.
    """
    rows = db.execute(
        text(
            "SELECT column_name, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'pageviews' "
            "AND column_name = ANY(:names)"
        ),
        {"names": list(NEW_COLUMNS)},
    ).all()

    assert {r.column_name for r in rows} == set(NEW_COLUMNS)
    for row in rows:
        assert row.is_nullable == "YES", row.column_name
        assert row.column_default is None, row.column_name

    indexes = db.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = 'pageviews'"
        )
    ).all()
    for name, definition in indexes:
        columns = definition.split("(", 1)[1]
        for column in NEW_COLUMNS:
            assert not re.search(rf"\b{column}\b", columns), (
                f"{name} indexes {column} on an insert-heavy table"
            )


def test_the_tracker_sends_one_language_and_never_the_list():
    """Read from the file that is served. CI proves it matches the source."""
    served = pathlib.Path(__file__).resolve().parents[1] / "app" / "static" / "tracker.min.js"
    source = served.read_text()
    assert "navigator.language" in source
    assert "navigator.languages" not in source, (
        "the full language list is a fingerprint and must not be sent"
    )
    assert "hostname:" in source
