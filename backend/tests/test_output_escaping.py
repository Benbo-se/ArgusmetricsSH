"""Hostile strings, driven through the pages that render them.

The Content-Security-Policy here keeps 'unsafe-inline' and 'unsafe-eval',
because Alpine evaluates its x-* attributes as strings, so CSP is not the
defence against script injection in this application. Output escaping is.
That makes it worth testing directly rather than trusting a header to catch a
mistake it cannot see.

Three places take text from someone else and put it on a page:

  a website name and domain, which a customer types
  an event or product name, which arrives from the tracking API and so is
      controlled by whoever can reach a public endpoint
  a path, likewise

The subtle one is `| tojson | safe` inside a <script> block, used eight times
for chart data. It looks like escaping switched off. It is not: Jinja's tojson
escapes < > and ' as unicode escapes, so a "</script>" in the data cannot
close the tag. That is a property of the filter rather than of this code, so
it deserves a test that fails if the filter is ever swapped for json.dumps.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

# Each of these escapes a different context if escaping is missing.
HOSTILE = [
    "</script><script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "'; alert(1); //",
    "<svg/onload=alert(1)>",
    "{{ 7*7 }}",
]


def _assert_not_executable(body: str, payload: str):
    """The payload may appear. It must not appear as live markup.

    The distinction matters and cost me a false alarm: inside a JSON script
    island the string `onerror=alert(1)` shows up verbatim while the
    surrounding angle brackets are escaped to \\u003c, so no tag can form.
    Searching for the handler alone flags that as an injection. Searching for
    an actual unescaped tag does not.
    """
    dangerous = [
        "<script>alert(1)</script>",
        "<img src=x onerror=",
        "<svg/onload=",
        '"><img',
    ]
    for form in dangerous:
        assert form not in body, (
            f"{form!r} rendered as live markup, from payload {payload!r}"
        )


class TestContentSecurityPolicy:
    """What the header promises, and that a page can satisfy it."""

    def test_it_has_no_unsafe_inline(self, client):
        """Dropped in favour of a per-request nonce.

        Without it, an injected <script> or onerror= handler cannot run even
        if the escaping that should have stopped it fails. That is the whole
        value of the header here, and it is one careless edit away from being
        given back.
        """
        header = client.get("/login").headers["content-security-policy"]

        assert "'unsafe-inline'" not in header, (
            "script-src allows inline scripts again, so an injected <script> "
            "or onerror= would execute"
        )
        assert "'nonce-" in header, "no nonce, so the page's own scripts cannot run"

    def test_the_page_nonce_matches_the_header(self, client):
        """They come from the same request or nothing on the page runs."""
        import re

        response = client.get("/login")
        header_nonce = re.search(
            r"'nonce-([^']+)'", response.headers["content-security-policy"]
        ).group(1)
        page_nonces = set(re.findall(r'nonce="([^"]+)"', response.text))

        assert page_nonces, "no inline script carries a nonce"
        assert page_nonces == {header_nonce}, (
            f"page nonces {page_nonces} do not match the header's {header_nonce!r}"
        )

    def test_a_second_request_gets_a_different_nonce(self, client):
        """A reused nonce is barely better than 'unsafe-inline'."""
        import re

        def nonce_of(response):
            return re.search(
                r"'nonce-([^']+)'", response.headers["content-security-policy"]
            ).group(1)

        assert nonce_of(client.get("/login")) != nonce_of(client.get("/login"))

    def test_no_template_still_uses_an_inline_handler(self):
        """onclick="" and friends are silently dead under this policy.

        Silently is the problem: the button renders, the page looks right, and
        nothing happens when it is pressed.
        """
        import pathlib
        import re

        offenders = []
        for path in pathlib.Path("app/templates").rglob("*.html"):
            for line_no, line in enumerate(path.read_text().splitlines(), 1):
                # Escaped example code shown to customers is not a handler.
                if "&lt;" in line or "<code>" in line:
                    continue
                if re.search(r'\son(click|submit|input|change|load)="', line):
                    offenders.append(f"{path}:{line_no}")

        assert not offenders, (
            "inline event handlers do nothing under this CSP:\n  "
            + "\n  ".join(offenders)
        )


class TestScriptIslands:
    def test_tojson_cannot_close_the_script_tag(self):
        """The property the eight chart-data blocks rely on."""
        from app.routers.dashboard import templates

        template = templates.env.from_string(
            "<script>const d = {{ v | tojson | safe }};</script>"
        )
        rendered = template.render(v={"name": "</script><script>alert(1)</script>"})

        assert "</script><script>" not in rendered, (
            "tojson no longer escapes a script-tag breakout, so every chart "
            "data block on the dashboard is an injection point"
        )
        assert "\\u003c" in rendered, "tojson is not escaping angle brackets at all"

    def test_tojson_escapes_quotes_too(self):
        from app.routers.dashboard import templates

        rendered = templates.env.from_string("{{ v | tojson | safe }}").render(
            v={"k": "a'b\"c"}
        )

        assert "\\u0027" in rendered, "single quotes are not escaped"


class TestCustomerControlledText:
    def test_a_hostile_website_name_does_not_execute(self, owner_client, db, website):
        """A customer names their own site, and their team sees the name."""
        for payload in HOSTILE:
            db.execute(
                text("UPDATE websites SET name = :n WHERE id = :w"),
                {"n": payload, "w": website["id"]},
            )
            db.commit()

            body = owner_client.get(f"/dashboard/website/{website['id']}").text
            _assert_not_executable(body, payload)

            body = owner_client.get("/dashboard").text
            _assert_not_executable(body, payload)


class TestVisitorControlledText:
    def _pageview(self, db, website_id, path):
        db.execute(
            text(
                "INSERT INTO pageviews "
                "  (website_id, path, visitor_hash, timestamp, browser, device_type) "
                "VALUES (:w, :p, :h, :t, 'Chrome', 'desktop')"
            ),
            {
                "w": website_id,
                "p": path,
                "h": uuid.uuid4().hex[:16],
                "t": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
        )
        db.commit()

    def test_a_hostile_path_does_not_execute(self, owner_client, db, website):
        """Paths arrive from the tracking endpoint, which anyone can call."""
        for payload in HOSTILE:
            self._pageview(db, website["id"], f"/{payload}")

        for page in ("", "/live-list", "/stats"):
            body = owner_client.get(f"/dashboard/website/{website['id']}{page}").text
            for payload in HOSTILE:
                _assert_not_executable(body, payload)

    def test_a_hostile_event_name_does_not_execute(self, owner_client, db, website):
        """Event names come from the public tracking API."""
        for payload in HOSTILE:
            db.execute(
                text(
                    "INSERT INTO custom_events "
                    "  (website_id, event_name, visitor_hash, timestamp) "
                    "VALUES (:w, :e, :h, now())"
                ),
                {"w": website["id"], "e": payload, "h": uuid.uuid4().hex[:16]},
            )
        db.commit()

        body = owner_client.get(f"/dashboard/website/{website['id']}").text
        for payload in HOSTILE:
            _assert_not_executable(body, payload)

    def test_a_hostile_product_name_does_not_execute(self, owner_client, db, website):
        """Product names reach the revenue chart's tojson island."""
        for payload in HOSTILE:
            db.execute(
                text(
                    "INSERT INTO ecommerce_events "
                    "  (website_id, event_type, event_name, visitor_hash,"
                    "   product_name, revenue, currency, timestamp) "
                    "VALUES (:w, 'purchase', 'Purchase', :h, :p, 10, 'SEK', now())"
                ),
                {"w": website["id"], "h": uuid.uuid4().hex[:16], "p": payload},
            )
        db.commit()

        body = owner_client.get(f"/dashboard/website/{website['id']}/revenue").text
        for payload in HOSTILE:
            _assert_not_executable(body, payload)


class TestPublicDashboard:
    def test_hostile_data_does_not_execute_for_an_anonymous_viewer(
        self, client, db, shared_website
    ):
        """The one page a stranger sees, so the one where it matters most."""
        db.execute(
            text("UPDATE websites SET name = :n WHERE id = :w"),
            {"n": "</script><script>alert(1)</script>", "w": shared_website["id"]},
        )
        db.execute(
            text(
                "INSERT INTO pageviews "
                "  (website_id, path, visitor_hash, timestamp, browser, device_type) "
                "VALUES (:w, :p, :h, now(), 'Chrome', 'desktop')"
            ),
            {
                "w": shared_website["id"],
                "p": "/<svg/onload=alert(1)>",
                "h": uuid.uuid4().hex[:16],
            },
        )
        db.commit()

        body = client.get(f"/public/{shared_website['share_token']}").text

        _assert_not_executable(body, "public dashboard")
