"""The outbound links report, fed the way the tracker feeds it.

The tracker sends event_name 'Outbound Link' with the address in properties.
The report once looked for the address inside the name, so it was always empty.
"""
from datetime import datetime, timedelta, timezone

from app.services.analytics_service import AnalyticsService


def _click(client, website, url, text="Read more", from_page="/blog"):
    response = client.post(
        "/api/v1/analytics/track-event",
        json={
            "tracking_code": website["tracking_code"],
            "event_name": "Outbound Link",
            "properties": {"url": url, "text": text, "from_page": from_page},
        },
    )
    assert response.status_code == 200, response.text


def _report(db, website):
    now = datetime.now(timezone.utc)
    return AnalyticsService(db).get_outbound_links(
        website["id"], now - timedelta(days=1), now + timedelta(days=1)
    )


def test_clicks_sent_by_the_tracker_are_reported(client, db, website):
    _click(client, website, "https://example.org/a", text="Docs")
    _click(client, website, "https://example.org/a", text="Docs")
    _click(client, website, "https://other.example.net/b", text="Other")

    report = {row["url"]: row for row in _report(db, website)}

    assert set(report) == {"https://example.org/a", "https://other.example.net/b"}
    assert report["https://example.org/a"]["clicks"] == 2
    assert report["https://example.org/a"]["text"] == "Docs"
    assert report["https://example.org/a"]["from_page"] == "/blog"
    assert report["https://example.org/a"]["percentage"] == 66.7


def test_other_events_are_not_outbound_links(client, db, website):
    client.post(
        "/api/v1/analytics/track-event",
        json={
            "tracking_code": website["tracking_code"],
            "event_name": "file_download",
            "properties": {"url": "https://example.org/f.pdf"},
        },
    )

    assert _report(db, website) == []
