"""Do Not Track is honoured by every tracking endpoint, not only pageviews.

/track and /track-scroll refused a DNT request; custom events, goals and
ecommerce recorded it. The tracker has checked DNT itself since #106, but a
browser still running an older cached copy would send them anyway.
"""
import uuid

from sqlalchemy import text

PERSON = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"


def _count(db, table, website):
    return db.execute(
        text(f"SELECT count(*) FROM {table} WHERE website_id = :w"), {"w": website["id"]}
    ).scalar()


def test_a_goal_does_not_convert_for_do_not_track(client, db, website):
    db.execute(
        text("INSERT INTO goals (website_id, name, event_name, created_at) VALUES (:w, 'Signup', 'signup', now())"),
        {"w": website["id"]},
    )
    db.commit()

    dnt = client.post(
        "/api/v1/analytics/track-event",
        json={"tracking_code": website["tracking_code"], "event_name": "signup"},
        headers={"User-Agent": PERSON, "DNT": "1"},
    )
    assert dnt.json()["message"] == "Tracking skipped (DNT)"
    assert _count(db, "goal_conversions", website) == 0

    client.post(
        "/api/v1/analytics/track-event",
        json={"tracking_code": website["tracking_code"], "event_name": "signup"},
        headers={"User-Agent": PERSON},
    )
    assert _count(db, "goal_conversions", website) == 1, "the control: without DNT it converts"


def test_an_ecommerce_event_is_not_recorded_for_do_not_track(client, db, website):
    payload = {"tracking_code": website["tracking_code"], "event_type": "purchase",
               "transaction_id": f"t-{uuid.uuid4().hex[:8]}", "revenue": 10}
    dnt = client.post("/api/v1/analytics/track-ecommerce", json=payload, headers={"User-Agent": PERSON, "DNT": "1"})
    assert dnt.json()["message"] == "Tracking skipped (DNT)"
    assert _count(db, "ecommerce_events", website) == 0

    payload["transaction_id"] = f"t-{uuid.uuid4().hex[:8]}"
    client.post("/api/v1/analytics/track-ecommerce", json=payload, headers={"User-Agent": PERSON})
    assert _count(db, "ecommerce_events", website) == 1, "the control: without DNT it records"
