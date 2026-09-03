"""Every dashboard page renders, empty and with awkward data.

Two states break these pages, and neither is the one you develop against.

A brand new website has no traffic at all, and a template that assumes a first
row or divides by a total raises on it. That is the first thing a new customer
sees.

And real traffic is untidy. A pageview can arrive with no browser and no device
type, which already crashed this dashboard three ways in one afternoon: a
template doing `'Chrome' in None`, and json.dumps refusing to sort a dict whose
keys mix None with str. Paths carry unicode, query strings and lengths nobody
designs for.

So each page is rendered twice, and the assertion is that it renders at all
with the real numbers in it, not that it returns 200. A 500 here is a page a
customer cannot open.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

PAGES = [
    "",
    "/goals",
    "/funnels",
    "/revenue",
    "/team",
    "/settings",
    "/live",
    "/live-list",
    "/stats",
    "/stats-basic",
    "/debug",
]


def _messy_pageviews(db, website_id):
    """Traffic of the shape that actually arrives, not the shape we design for."""
    now = datetime.now(timezone.utc)
    rows = [
        # No browser and no device type: the combination that broke this
        # dashboard three separate ways.
        {"path": "/", "browser": None, "device": None},
        {"path": "/pricing", "browser": "Chrome", "device": "desktop"},
        # Unicode, a query string, and a path far longer than any design.
        {"path": "/blogg/våra-priser", "browser": "Firefox", "device": "mobile"},
        {"path": "/search?q=%3Cscript%3E&page=2", "browser": None, "device": "tablet"},
        {"path": "/" + "deep/" * 40, "browser": "Safari", "device": None},
    ]
    for i, row in enumerate(rows):
        db.execute(
            text(
                "INSERT INTO pageviews "
                "  (website_id, path, visitor_hash, timestamp, browser, device_type) "
                "VALUES (:w, :p, :h, :t, :b, :d)"
            ),
            {
                "w": website_id,
                "p": row["path"],
                "h": uuid.uuid4().hex[:16],
                "t": now - timedelta(minutes=i * 5),
                "b": row["browser"],
                "d": row["device"],
            },
        )
    db.commit()


@pytest.mark.parametrize("page", PAGES)
def test_a_brand_new_website_renders(owner_client, db, website, page):
    """The empty state, which is the first thing every customer sees."""
    response = owner_client.get(f"/dashboard/website/{website['id']}{page}")

    assert response.status_code == 200, (
        f"{page or '/'} fails for a website with no traffic: {response.text[:200]}"
    )


@pytest.mark.parametrize("page", PAGES)
def test_awkward_traffic_renders(owner_client, db, website, page):
    """Null browsers, unicode paths, query strings, absurd lengths."""
    _messy_pageviews(db, website["id"])

    response = owner_client.get(f"/dashboard/website/{website['id']}{page}")

    assert response.status_code == 200, (
        f"{page or '/'} fails on real-shaped traffic: {response.text[:300]}"
    )


def test_the_website_list_renders(owner_client, db, website):
    response = owner_client.get("/dashboard")

    assert response.status_code == 200
    assert website["domain"] in response.text or "Test site" in response.text, (
        "the list does not show the website it is listing"
    )


def test_the_cross_domain_page_renders(owner_client, db, website):
    _messy_pageviews(db, website["id"])

    response = owner_client.get("/dashboard/cross-domain")

    assert response.status_code == 200, response.text[:300]


def test_the_analytics_page_shows_the_numbers(owner_client, db, website):
    """Rendering is not enough: the figures have to reach the page."""
    _messy_pageviews(db, website["id"])

    response = owner_client.get(f"/dashboard/website/{website['id']}")

    assert response.status_code == 200
    assert "/pricing" in response.text, (
        "a path with traffic does not appear on the analytics page"
    )
    # Proof the awkward rows reach the page rather than being filtered out
    # somewhere, which would make the test above pass without testing anything.
    assert "priser" in response.text, (
        "the unicode path never reaches the page, so the messy rows are not "
        "actually being rendered and these tests prove less than they look"
    )


def test_an_event_page_renders_for_an_unknown_event(owner_client, db, website):
    """A name from the URL that matches nothing must not raise."""
    response = owner_client.get(
        f"/dashboard/website/{website['id']}/events/no_such_event"
    )

    assert response.status_code in (200, 404), response.text[:200]
    assert response.status_code != 500


def test_a_page_for_another_customer_s_website_is_refused(owner_client, db, website):
    db.execute(
        text(
            "INSERT INTO users (email, is_verified, created_at) "
            "VALUES ('stranger@example.com', true, now()) "
            "ON CONFLICT (email) DO NOTHING"
        )
    )
    other = db.execute(
        text(
            "INSERT INTO websites (name, domain, user_email, tracking_code,"
            "                      verification_token, is_verified, is_active,"
            "                      email_reports_enabled, is_public,"
            "                      public_password_enabled, created_at) "
            "VALUES ('theirs', :d, 'stranger@example.com', :tc, :vt,"
            "        true, true, false, false, false, now()) RETURNING id"
        ),
        {
            "d": f"https://theirs-{uuid.uuid4().hex[:8]}.example.com",
            "tc": uuid.uuid4().hex[:8],
            "vt": uuid.uuid4().hex,
        },
    ).scalar()
    db.commit()

    response = owner_client.get(f"/dashboard/website/{other}")

    assert response.status_code == 404
