"""The live debug console shows real traffic, and what happened to it.

It used to show only its own test pings. The tracking endpoints never sent it
anything, although the websocket's own welcome message promised "all tracking
events will appear here". These drive the real endpoints with a console open
and read what arrives.
"""
import uuid

from sqlalchemy import text

from tests.conftest import ws_headers
from tests.test_auth_context import _make_api_token

BROWSER = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"


def _next_debug_event(ws):
    """The debug line the last request sent, or a failure, never a hang.

    The tracking endpoint broadcasts before it answers, so by the time the
    request has returned the line is already queued. A ping sent now is
    answered after it: reaching the pong without a debug line means none was
    sent. Reading until a line arrives would wait forever instead, and hang
    CI rather than fail it.
    """
    ws.send_text('{"type": "ping"}')
    for _ in range(10):
        message = ws.receive_json()
        if message.get("type") == "debug_event":
            return message["data"]
        if message.get("type") == "pong":
            raise AssertionError("the request reached no debug console")
    raise AssertionError("neither a debug line nor a pong arrived")


def _console(client, db, website):
    token = _make_api_token(db, website["id"])
    return client.websocket_connect(
        f"/ws/debug/{website['id']}?api_token={token}", headers=ws_headers()
    )


class TestRealTrafficReachesTheConsole:
    def test_a_recorded_pageview(self, client, db, website):
        with _console(client, db, website) as ws:
            client.post(
                "/api/v1/analytics/track",
                json={"tracking_code": website["tracking_code"], "path": "/from-a-visitor"},
                headers={"User-Agent": BROWSER},
            )
            line = _next_debug_event(ws)

        assert line["event_type"] == "pageview"
        assert line["path"] == "/from-a-visitor"
        assert line["outcome"] == "recorded"
        assert line["metadata"]["user_agent"].startswith("Chrome"), (
            "the console must get the browser family, never the raw user agent"
        )

    def test_do_not_track_shows_as_skipped_and_why(self, client, db, website):
        with _console(client, db, website) as ws:
            client.post(
                "/api/v1/analytics/track",
                json={"tracking_code": website["tracking_code"], "path": "/dnt"},
                headers={"User-Agent": BROWSER, "DNT": "1"},
            )
            line = _next_debug_event(ws)

        assert line["outcome"] == "skipped"
        assert line["detail"] == "Do Not Track"

    def test_an_event_that_matches_a_goal(self, client, db, website):
        db.execute(
            text(
                "INSERT INTO goals (website_id, name, event_name, created_at) "
                "VALUES (:w, 'Order placed', 'order_placed', now())"
            ),
            {"w": website["id"]},
        )
        db.commit()

        with _console(client, db, website) as ws:
            client.post(
                "/api/v1/analytics/track-event",
                json={"tracking_code": website["tracking_code"], "event_name": "order_placed"},
                headers={"User-Agent": BROWSER},
            )
            line = _next_debug_event(ws)

        assert line["event_type"] == "event"
        assert line["metadata"]["event_name"] == "order_placed"
        assert line["outcome"] == "recorded"
        assert line["detail"] == "Recorded goal conversion"

    def test_an_event_nothing_matches_says_so(self, client, db, website):
        """The usual reason a goal shows nothing: the name the site sends is
        not the name the goal waits for."""
        with _console(client, db, website) as ws:
            client.post(
                "/api/v1/analytics/track-event",
                json={"tracking_code": website["tracking_code"], "event_name": f"typo_{uuid.uuid4().hex[:6]}"},
                headers={"User-Agent": BROWSER},
            )
            line = _next_debug_event(ws)

        assert line["outcome"] == "refused"
        assert line["detail"], "a refusal has to say why"

    def test_an_ecommerce_event_with_revenue_arrives(self, client, db, website):
        """revenue is a Decimal, which JSON cannot carry. Unconverted, every
        ecommerce line failed to send and the failure was swallowed."""
        with _console(client, db, website) as ws:
            client.post(
                "/api/v1/analytics/track-ecommerce",
                json={
                    "tracking_code": website["tracking_code"],
                    "event_type": "purchase",
                    "transaction_id": f"t-{uuid.uuid4().hex[:8]}",
                    "revenue": 99.5,
                },
                headers={"User-Agent": BROWSER},
            )
            line = _next_debug_event(ws)

        assert line["event_type"] == "ecommerce"
        assert line["metadata"]["revenue"] in ("99.5", "99.50")


class TestNobodyWatching:
    def test_nothing_is_sent_without_an_open_console(self, client, db, website, monkeypatch):
        """The broadcast path must cost nothing on ordinary traffic."""
        from app.routers import websocket

        sent = []

        async def record(website_id, data):
            sent.append(data)

        monkeypatch.setattr(websocket, "broadcast_debug_event", record)

        response = client.post(
            "/api/v1/analytics/track",
            json={"tracking_code": website["tracking_code"], "path": "/unwatched"},
            headers={"User-Agent": BROWSER},
        )

        assert response.status_code == 200
        assert sent == [], "a debug line was sent with no console open"
