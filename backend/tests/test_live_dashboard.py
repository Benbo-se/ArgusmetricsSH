"""/ws/live carries pageviews and conversions as they are recorded.

The socket existed, authenticated and access-checked, and nothing ever sent to
it. The first-visit guide listens for the first pageview and every dashboard
page for conversions, so these read what actually arrives.
"""
import uuid

from sqlalchemy import text

from tests.conftest import ws_headers
from tests.test_auth_context import _make_api_token

BROWSER = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"


def _next(ws, kind):
    """The next message of this kind, or a failure, never a hang (see
    test_debug_console._next_debug_event for why a ping)."""
    ws.send_text('{"type": "ping"}')
    for _ in range(10):
        message = ws.receive_json()
        if message.get("type") == kind:
            return message["data"]
        if message.get("type") == "pong":
            raise AssertionError(f"no {kind} message reached the dashboard")
    raise AssertionError("neither the message nor a pong arrived")


def _live(client, db, website):
    token = _make_api_token(db, website["id"])
    return client.websocket_connect(
        f"/ws/live/{website['id']}?api_token={token}", headers=ws_headers()
    )


def test_a_recorded_pageview_reaches_the_dashboard(client, db, website):
    with _live(client, db, website) as ws:
        client.post(
            "/api/v1/analytics/track",
            json={"tracking_code": website["tracking_code"], "path": "/first"},
            headers={"User-Agent": BROWSER},
        )
        data = _next(ws, "pageview")

    assert data["path"] == "/first"


def test_a_conversion_arrives_with_the_goals_own_name(client, db, website):
    db.execute(
        text(
            "INSERT INTO goals (website_id, name, event_name, created_at) "
            "VALUES (:w, 'Order placed', 'order_placed', now())"
        ),
        {"w": website["id"]},
    )
    db.commit()

    with _live(client, db, website) as ws:
        client.post(
            "/api/v1/analytics/track-event",
            json={"tracking_code": website["tracking_code"], "event_name": "order_placed"},
            headers={"User-Agent": BROWSER},
        )
        data = _next(ws, "conversion")

    assert data["goal_name"] == "Order placed"
    assert data["event_name"] == "order_placed"


def test_an_event_without_a_goal_announces_nothing(client, db, website):
    """A toast for every custom event would be noise: only goals convert."""
    with _live(client, db, website) as ws:
        client.post(
            "/api/v1/analytics/track-event",
            json={
                "tracking_code": website["tracking_code"],
                "event_name": f"no_goal_{uuid.uuid4().hex[:6]}",
                "properties": {"button": "cta"},
            },
            headers={"User-Agent": BROWSER},
        )
        try:
            _next(ws, "conversion")
        except AssertionError:
            return
    raise AssertionError("a conversion was announced for an event with no goal")
