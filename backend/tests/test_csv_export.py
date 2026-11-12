"""The dashboard's CSV export, read back and compared with what it exports.

The export once read keys the statistics never had, so three sections came out
empty and the visit duration was always 0s, while the file still looked like a
report. So these tests put real rows in and read the file back.
"""
import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.utils.csv_safe import csv_safe


def _add(db, website_id, visitor, path, seconds_ago, referrer=None, country=None,
         browser="Chrome"):
    when = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    db.execute(
        text(
            "INSERT INTO pageviews (website_id, path, visitor_hash, timestamp, "
            "  browser, device_type, referrer, country) "
            "VALUES (:w, :p, :h, :t, :b, 'desktop', :r, :c)"
        ),
        {"w": website_id, "p": path, "h": visitor, "t": when, "b": browser,
         "r": referrer, "c": country},
    )


def _sections(body):
    sections, current = {}, None
    for row in csv.reader(io.StringIO(body)):
        if len(row) == 1 and row[0].isupper():
            current = sections.setdefault(row[0], [])
        elif current is not None and row:
            current.append(row)
    return sections


class TestDashboardExport:
    def test_every_section_is_filled_and_duration_is_real(self, owner_client, db, website):
        wid = website["id"]
        _add(db, wid, "alice", "/", 3600 + 120, referrer="https://news.example.org/", country="SE")
        _add(db, wid, "alice", "/pricing", 3600, referrer="https://news.example.org/", country="SE")
        _add(db, wid, "bob", "/", 7200, referrer="https://search.example.net/", country="NO", browser="Firefox")
        db.commit()

        response = owner_client.get(f"/dashboard/website/{wid}/export-csv?range=7d")

        assert response.status_code == 200, response.text
        sections = _sections(response.text)
        summary = {r[0]: r[1] for r in sections["SUMMARY"]}
        # alice 120s, bob 0s (a bounce): average 60s
        assert summary["Avg. Visit Duration"] == "60s", summary
        referrers = {r[0]: r[1] for r in sections["TOP REFERRERS"][1:]}
        assert referrers == {
            "https://news.example.org/": "2",
            "https://search.example.net/": "1",
        }
        countries = {r[0]: r[1] for r in sections["TOP COUNTRIES"][1:]}
        assert countries == {"SE": "2", "NO": "1"}
        browsers = {r[0]: r[1] for r in sections["TOP BROWSERS"][1:]}
        assert browsers == {"Chrome": "2", "Firefox": "1"}

    def test_cells_starting_with_a_formula_character_are_protected(self, owner_client, db, website):
        wid = website["id"]
        _add(db, wid, "alice", "/", 600, referrer="@cmd")
        db.commit()

        response = owner_client.get(f"/dashboard/website/{wid}/export-csv?range=7d")

        cells = [c for row in csv.reader(io.StringIO(response.text)) for c in row]
        assert "'@cmd" in cells
        assert "@cmd" not in cells

    def test_api_export_protects_cells_too(self, owner_client, db, website):
        wid = website["id"]
        _add(db, wid, "alice", "/", 600, referrer="=HYPERLINK(\"x\")")
        db.commit()

        response = owner_client.get(
            f"/api/v1/analytics/export/{wid}/csv?start_date=2020-01-01&end_date=2099-01-01"
        )

        cells = [c for row in csv.reader(io.StringIO(response.text)) for c in row]
        assert "'=HYPERLINK(\"x\")" in cells
        assert "=HYPERLINK(\"x\")" not in cells


@pytest.mark.parametrize("raw,expected", [
    ("=1+1", "'=1+1"), ("+1", "'+1"), ("-1", "'-1"), ("@x", "'@x"),
    ("\tx", "'\tx"), ("\rx", "'\rx"),
    ("/path", "/path"), ("", ""), (5, 5), (None, None), ("a=b", "a=b"),
])
def test_csv_safe(raw, expected):
    assert csv_safe(raw) == expected
