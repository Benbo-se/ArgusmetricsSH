"""Crawlers are refused on every tracking endpoint, by name (#103).

Pageviews and ecommerce events checked the user agent; custom events, goals
and scroll depth did not, so a crawler that clicked through a page converted
goals. And the largest crawler seen in production, Meta's meta-externalagent,
was only refused because its user agent links to a page with "crawler" in the
URL. These use a version of its user agent without that link.
"""
from sqlalchemy import text

PERSON = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
META = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36 (compatible; meta-externalagent/1.1)"
GPT = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)"


def _pageviews(db, website, path):
    return db.execute(
        text("SELECT count(*) FROM pageviews WHERE website_id = :w AND path = :p"),
        {"w": website["id"], "p": path},
    ).scalar()


def _conversions(db, website):
    return db.execute(
        text("SELECT count(*) FROM goal_conversions WHERE website_id = :w"),
        {"w": website["id"]},
    ).scalar()


def _goal(db, website):
    db.execute(
        text(
            "INSERT INTO goals (website_id, name, event_name, created_at) "
            "VALUES (:w, 'Order placed', 'order_placed', now())"
        ),
        {"w": website["id"]},
    )
    db.commit()


def test_meta_externalagent_is_refused_by_name(client, db, website):
    response = client.post(
        "/api/v1/analytics/track",
        json={"tracking_code": website["tracking_code"], "path": "/meta"},
        headers={"User-Agent": META},
    )
    assert response.json()["message"] == "Tracking skipped (Bot)"
    assert _pageviews(db, website, "/meta") == 0


def test_a_person_with_the_same_browser_is_still_counted(client, db, website):
    """The control: the same Chrome without the crawler's token records."""
    client.post(
        "/api/v1/analytics/track",
        json={"tracking_code": website["tracking_code"], "path": "/person"},
        headers={"User-Agent": PERSON},
    )
    assert _pageviews(db, website, "/person") == 1


def test_a_crawler_does_not_convert_a_goal(client, db, website):
    _goal(db, website)

    bot = client.post(
        "/api/v1/analytics/track-event",
        json={"tracking_code": website["tracking_code"], "event_name": "order_placed"},
        headers={"User-Agent": GPT},
    )
    assert bot.json()["message"] == "Tracking skipped (Bot)"
    assert _conversions(db, website) == 0

    client.post(
        "/api/v1/analytics/track-event",
        json={"tracking_code": website["tracking_code"], "event_name": "order_placed"},
        headers={"User-Agent": PERSON},
    )
    assert _conversions(db, website) == 1, "the control: a person still converts"


def test_a_crawler_does_not_report_scroll_depth(client, db, website):
    client.post(
        "/api/v1/analytics/track",
        json={"tracking_code": website["tracking_code"], "path": "/read"},
        headers={"User-Agent": PERSON},
    )
    response = client.post(
        "/api/v1/analytics/track-scroll",
        json={"tracking_code": website["tracking_code"], "path": "/read", "depth": 80},
        headers={"User-Agent": META},
    )
    assert response.json()["message"] == "Tracking skipped (Bot)"
    depth = db.execute(
        text("SELECT scroll_depth FROM pageviews WHERE website_id = :w AND path = '/read'"),
        {"w": website["id"]},
    ).scalar()
    assert depth is None
