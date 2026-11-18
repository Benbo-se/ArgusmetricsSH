"""The MCP endpoint reads what its token may read, and does nothing else.

Three promises, each tested against behaviour:

- A token reaches one website. Not another account's, and not another website
  of the same owner, through any tool.
- No tool writes. The list of tools is held here by name, so adding one is a
  decision somebody made in this file as well.
- The numbers are the REST API's numbers, because the tools call its handlers.

The calls go through the SDK's own client, speaking HTTP to the application in
process. That is deliberate. A test that called the tool functions directly
would skip authentication, the protocol and the route, which are the parts
that can be wrong. Both protocol eras are driven: the initialize handshake
that clients released before mid-2026 open with, and the handshake-free
2026-07-28.

The conftest client is not entered as a context manager, so the application's
lifespan never runs here, and with it neither does the session manager. Each
call below starts one for itself, the way the lifespan does.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import anyio
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import text

from app.config import settings
from app.database import RLS_INFO_KEY
from app.main import app
from app.middleware.rate_limit import rate_limiter
from app.routers import mcp_endpoint
from app.services.token_service import TokenService

MCP_PATH = "/api/mcp"
# https, whatever BASE_URL says: the conftest client does the same, and for
# the same reason. This is where requests are addressed.
ORIGIN = f"https://{urlparse(settings.BASE_URL).netloc}"
#: What a browser on this instance's own pages sends as its Origin header.
#: That one does follow BASE_URL's scheme, which is http in CI.
OWN_ORIGIN = "{0.scheme}://{0.netloc}".format(urlparse(settings.BASE_URL))

#: Every tool the endpoint offers. All of them read. A tool added to the
#: endpoint without being added here fails test_the_tools_are_exactly_these,
#: and that is the moment to ask whether a pasted token should be able to do
#: what the new tool does.
READ_TOOLS = {
    "list_sites",
    "get_overview",
    "get_top_pages",
    "get_sources",
    "get_countries",
    "get_devices",
    "get_goals",
    "get_realtime",
}

#: The tools that take a website_id, which is every one that returns
#: statistics. Each is tried against a website the token does not belong to.
SITE_TOOLS = sorted(READ_TOOLS - {"list_sites"})

#: What each of those returns for a website seeded by seed_traffic. Used as
#: the control in the isolation tests: the website's own token has to read
#: real data, or a refusal for the other token would prove nothing.
HOLDS_DATA = {
    "get_overview": lambda s: s["total_pageviews"] == 3,
    "get_top_pages": lambda s: len(s["pages"]) == 2,
    "get_sources": lambda s: len(s["referrers"]) == 1,
    "get_countries": lambda s: len(s["countries"]) == 2,
    "get_devices": lambda s: s["devices"] == {"desktop": 2, "mobile": 1},
    "get_goals": lambda s: len(s["goals"]) == 1,
    "get_realtime": lambda s: s["recent_pageviews"] == 3,
}

#: Both ways a client can open the conversation.
ERAS = ["legacy", "auto"]

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


@pytest.fixture(autouse=True)
def _fresh_limiter():
    """Every test here calls from one address. Without this they would
    throttle each other, and which one failed would depend on the order."""
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture
def mcp_on(monkeypatch):
    """Turn the endpoint on. It is off by default, and a test that forgot
    this would be asserting on a 404."""
    monkeypatch.setattr(settings, "MCP_ENABLED", True)


def make_token(db, website_id):
    """A real API token for a website, hashed the way the app stores it."""
    raw = f"t-{uuid.uuid4().hex}"
    db.execute(
        text(
            "INSERT INTO api_tokens (website_id, name, token, created_at) "
            "VALUES (:w, 'mcp test', :t, now())"
        ),
        {"w": website_id, "t": TokenService.hash_token(raw)},
    )
    db.commit()
    return raw


def make_site(db, owner_email=None):
    """A verified website. With no owner given, a new account owns it."""
    suffix = uuid.uuid4().hex[:8]
    email = owner_email or f"other-{suffix}@example.com"
    db.execute(
        text(
            "INSERT INTO users (email, is_verified, created_at) "
            "VALUES (:e, true, now()) ON CONFLICT (email) DO NOTHING"
        ),
        {"e": email},
    )
    site_id = db.execute(
        text(
            "INSERT INTO websites (name, domain, user_email, tracking_code,"
            "                      verification_token, is_verified, is_active,"
            "                      email_reports_enabled, is_public,"
            "                      public_password_enabled, created_at) "
            "VALUES (:n, :d, :e, :tc, :vt, true, true, false, false, false, now()) "
            "RETURNING id"
        ),
        {
            "n": f"Site {suffix}",
            "d": f"https://{suffix}.example.com",
            "e": email,
            "tc": uuid.uuid4().hex[:8],
            "vt": f"tok-{suffix}",
        },
    ).scalar()
    db.commit()
    return {"id": site_id, "email": email}


def seed_traffic(db, website_id, marker):
    """A few pageviews half an hour ago, so every report has something in it.

    `marker` goes into the paths, the referrer and the goal, which lets an
    isolation test look for it in an answer that should not contain it.
    """
    when = datetime.now(timezone.utc) - timedelta(minutes=30)
    rows = [
        (f"/{marker}/pricing", "v1", "SE", "desktop", "Firefox", f"https://{marker}.example.org/"),
        (f"/{marker}/pricing", "v2", "SE", "mobile", "Safari", None),
        (f"/{marker}/blog", "v1", "NO", "desktop", "Firefox", None),
    ]
    for path, visitor, country, device, browser, referrer in rows:
        db.execute(
            text(
                "INSERT INTO pageviews (website_id, path, visitor_hash, timestamp,"
                "                       country, device_type, browser, referrer) "
                "VALUES (:w, :p, :v, :t, :c, :d, :b, :r)"
            ),
            {
                "w": website_id, "p": path, "v": f"{marker}-{visitor}", "t": when,
                "c": country, "d": device, "b": browser, "r": referrer,
            },
        )
    db.execute(
        text(
            "INSERT INTO goals (website_id, name, event_name, created_at) "
            "VALUES (:w, :n, :e, now())"
        ),
        {"w": website_id, "n": f"Goal {marker}", "e": f"signup_{marker}"},
    )
    db.commit()


def ask(token, conversation, era="auto", query=""):
    """Run `conversation(client)` against the application as an MCP client.

    The SDK client, over HTTP, to the real route: the token travels in the
    Authorization header exactly as an assistant would send it. `query` is
    put on the endpoint's own address.
    """

    async def main():
        async with mcp_endpoint.mcp_runtime():
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                headers={"Authorization": f"Bearer {token}"},
            ) as http:
                transport = streamable_http_client(f"{ORIGIN}{MCP_PATH}{query}", http_client=http)
                async with Client(transport, mode=era) as client:
                    return await conversation(client)

    return anyio.run(main)


def call(token, tool, arguments=None, era="auto"):
    """One tool call. Returns the SDK's CallToolResult."""

    async def conversation(client):
        return await client.call_tool(tool, arguments or {})

    return ask(token, conversation, era)


def post(client, token=None, body=INITIALIZE, headers=None):
    """A raw POST to the endpoint, for what happens before any protocol."""
    sent = dict(JSON_HEADERS)
    if token is not None:
        sent["Authorization"] = f"Bearer {token}"
    sent.update(headers or {})
    return client.post(MCP_PATH, content=json.dumps(body), headers=sent)


def said(result):
    """Everything a tool answered, as one lowercased string."""
    parts = [getattr(block, "text", "") for block in result.content]
    parts.append(json.dumps(result.structured_content or {}))
    return " ".join(parts).lower()


class TestItIsOffUntilTurnedOn:
    def test_off_by_default(self):
        """Turning it on has to be a decision somebody made."""
        assert settings.MCP_ENABLED is False

    def test_a_valid_token_gets_404_while_it_is_off(self, client, db, website):
        token = make_token(db, website["id"])

        response = post(client, token)

        assert response.status_code == 404

    def test_the_same_request_is_let_in_once_it_is_on(self, client, db, website, mcp_on):
        """The control for the test above: the 404 was the setting, not the
        path or the token. 503 here is the route saying the session manager
        is not running, which means authentication let the request through."""
        token = make_token(db, website["id"])

        response = post(client, token)

        assert response.status_code == 503, response.text[:200]


class TestOnlyAnApiTokenOpensIt:
    def test_no_token_is_refused(self, client, mcp_on):
        response = post(client)

        assert response.status_code == 401
        assert "api token" in response.json()["message"].lower()

    def test_a_wrong_token_is_refused(self, client, db, website, mcp_on):
        make_token(db, website["id"])

        response = post(client, "t-not-a-real-token")

        assert response.status_code == 401
        assert "invalid api token" in response.json()["message"].lower()

    def test_a_wrong_token_never_reaches_a_tool(self, client, db, website, mcp_on):
        """Refused by the route, before the protocol: an MCP client gets an
        HTTP error and no session, not a polite tool error."""
        seed_traffic(db, website["id"], "secret")

        with pytest.raises(Exception) as refused:
            call("t-not-a-real-token", "get_top_pages")

        assert "secret" not in str(refused.value).lower()

    def test_a_session_is_not_a_token(self, client, db, website, mcp_on):
        """A session bearer opens the REST API and must not open this.

        A session sees every website its user can; a token sees one. The
        function underneath would accept either, so the route has to be the
        one that says no.
        """
        from app.utils.security import hash_token

        session_token = f"s-{uuid.uuid4().hex}"
        db.execute(
            text(
                "INSERT INTO sessions (token, user_email, expires_at, created_at) "
                "VALUES (:t, :e, now() + interval '1 day', now())"
            ),
            {"t": hash_token(session_token), "e": website["email"]},
        )
        db.commit()

        # The control: this credential is good where sessions are accepted.
        rest = client.get(
            f"/api/v1/analytics/stats/{website['id']}",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert rest.status_code == 200, rest.text[:200]

        as_bearer = post(client, session_token)
        client.cookies.set("session_token", session_token)
        as_cookie = post(client)

        assert as_bearer.status_code == 401
        assert as_cookie.status_code == 401

    @pytest.mark.parametrize("method", ["GET", "DELETE"])
    def test_there_is_no_stream_and_no_session(self, client, db, website, mcp_on, method):
        """405 is the protocol's answer from a server that offers neither.

        It also must come back at all. Handed to the SDK, a GET opens a
        stream that never ends, and the request would sit there holding a
        database session.
        """
        token = make_token(db, website["id"])

        response = client.request(
            method, MCP_PATH,
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )

        assert response.status_code == 405

    def test_the_x_api_token_header_works_as_it_does_for_rest(self, client, db, website, mcp_on):
        token = make_token(db, website["id"])

        response = post(client, headers={"X-API-Token": token})

        # Past authentication: see test_the_same_request_is_let_in_once_it_is_on.
        assert response.status_code == 503, response.text[:200]

    def test_it_declares_the_same_context_as_the_rest_api(self, client, db, website, mcp_on):
        """Without a context a request reads nothing from a policied table and
        answers 200 while doing it, which no other assertion here would see
        while the suite runs as the table owner."""
        token = make_token(db, website["id"])
        db.info.pop(RLS_INFO_KEY, None)

        call(token, "get_overview")

        declared = db.info.get(RLS_INFO_KEY)
        assert declared is not None, "the request declared no context at all"
        assert declared["context"] == "user"
        assert declared["user_email"] == website["email"]


class TestTheToolsOnlyRead:
    @pytest.mark.parametrize("era", ERAS)
    def test_the_tools_are_exactly_these(self, client, db, website, mcp_on, era):
        token = make_token(db, website["id"])

        async def conversation(mcp):
            return (await mcp.list_tools()).tools

        tools = ask(token, conversation, era)

        assert {tool.name for tool in tools} == READ_TOOLS

    def test_every_tool_says_it_is_read_only(self, client, db, website, mcp_on):
        token = make_token(db, website["id"])

        async def conversation(mcp):
            return (await mcp.list_tools()).tools

        for tool in ask(token, conversation):
            assert tool.annotations is not None, tool.name
            assert tool.annotations.read_only_hint is True, tool.name
            assert tool.annotations.destructive_hint is False, tool.name

    def test_nothing_else_is_offered(self, client, db, website, mcp_on):
        """No resources and no prompts: tools are the whole surface."""
        token = make_token(db, website["id"])

        async def conversation(mcp):
            return (
                (await mcp.list_resources()).resources,
                (await mcp.list_resource_templates()).resource_templates,
                (await mcp.list_prompts()).prompts,
            )

        resources, templates, prompts = ask(token, conversation)

        assert resources == []
        assert templates == []
        assert prompts == []

    def test_calling_every_tool_changes_no_row(self, client, db, website, mcp_on):
        """Counted, because "read-only" in a description is a claim.

        last_used_at on the token is the one write there is, made by
        authentication exactly as the REST API makes it, and it changes no
        count.
        """
        seed_traffic(db, website["id"], "count")
        token = make_token(db, website["id"])
        tables = ["pageviews", "goals", "goal_conversions", "websites",
                  "api_tokens", "custom_events", "website_members", "users"]

        def counts():
            return {
                t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables
            }

        before = counts()

        async def conversation(mcp):
            for name in sorted(READ_TOOLS):
                result = await mcp.call_tool(name, {})
                assert not result.is_error, f"{name}: {said(result)}"

        ask(token, conversation)

        assert counts() == before


class TestTheNumbersAreTheRestApisNumbers:
    """One seeded website, read both ways with the same token."""

    @pytest.fixture
    def seeded(self, client, db, website, mcp_on):
        seed_traffic(db, website["id"], "alpha")
        token = make_token(db, website["id"])
        rest = client.get(
            f"/api/v1/analytics/stats/{website['id']}",
            headers={"X-API-Token": token},
        )
        assert rest.status_code == 200, rest.text[:200]
        stats = rest.json()
        # The seed has to be in the answer, or equal numbers below would be
        # two zeroes agreeing with each other.
        assert stats["total_pageviews"] == 3
        assert stats["unique_visitors"] == 2
        return {"token": token, "stats": stats, "website": website}

    @pytest.mark.parametrize("era", ERAS)
    def test_overview(self, seeded, era):
        result = call(seeded["token"], "get_overview", era=era)

        assert not result.is_error, said(result)
        overview = result.structured_content
        assert overview["total_pageviews"] == seeded["stats"]["total_pageviews"] == 3
        assert overview["unique_visitors"] == seeded["stats"]["unique_visitors"] == 2
        assert overview["timeseries"] == seeded["stats"]["timeseries"]

    def test_the_endpoints_own_address_filters_nothing(self, seeded):
        """The REST handlers read the dashboard's filters from the query
        string of the request they are handed (#205). Handed the POST to
        /api/mcp, a `?country=` on the endpoint's address would filter every
        report without the assistant being told. They get an empty request."""

        async def conversation(client):
            return await client.call_tool("get_overview", {})

        result = ask(seeded["token"], conversation, query="?country=ZZ&page__contains=nowhere")

        assert not result.is_error, said(result)
        assert result.structured_content["total_pageviews"] == seeded["stats"]["total_pageviews"] == 3

    def test_the_breakdowns(self, seeded):
        token, stats = seeded["token"], seeded["stats"]

        pages = call(token, "get_top_pages").structured_content
        sources = call(token, "get_sources").structured_content
        countries = call(token, "get_countries").structured_content
        devices = call(token, "get_devices").structured_content

        assert pages["pages"] == stats["top_pages"]
        assert pages["pages"][0] == {"path": "/alpha/pricing", "views": 2}
        assert sources["referrers"] == stats["top_referrers"]
        assert sources["referrers"][0]["referrer"] == "https://alpha.example.org/"
        assert sources["utm_campaigns"] == stats["utm_campaigns"]
        assert countries["countries"] == stats["top_countries"]
        assert countries["countries"][0] == {"country": "SE", "views": 2}
        assert devices["devices"] == stats["devices"] == {"desktop": 2, "mobile": 1}
        assert devices["browsers"] == stats["top_browsers"]
        assert devices["operating_systems"] == stats["dimensions"]["os"]

    def test_goals_and_realtime(self, client, seeded):
        token, website = seeded["token"], seeded["website"]
        headers = {"X-API-Token": token}
        rest_goals = client.get(f"/api/v1/analytics/goals/{website['id']}", headers=headers).json()
        rest_live = client.get(f"/api/v1/analytics/realtime/{website['id']}", headers=headers).json()

        goals = call(token, "get_goals").structured_content
        live = call(token, "get_realtime").structured_content

        assert goals == rest_goals
        assert [g["name"] for g in goals["goals"]] == ["Goal alpha"]
        assert live == rest_live
        assert live["recent_pageviews"] == 3

    def test_a_date_range_is_the_rest_apis_date_range(self, client, seeded):
        """Yesterday and earlier holds none of the seed, by either route."""
        token, website = seeded["token"], seeded["website"]
        window = {"start_date": "2020-01-01", "end_date": "2020-01-31"}
        rest = client.get(
            f"/api/v1/analytics/stats/{website['id']}",
            params=window, headers={"X-API-Token": token},
        ).json()

        overview = call(token, "get_overview", window).structured_content

        assert overview["total_pageviews"] == rest["total_pageviews"] == 0

    def test_a_bad_date_is_a_message_the_model_can_read(self, seeded):
        result = call(seeded["token"], "get_overview", {"start_date": "last tuesday"})

        assert result.is_error
        assert "invalid date format" in said(result)

    def test_list_sites_is_the_tokens_website(self, seeded):
        website = seeded["website"]

        sites = call(seeded["token"], "list_sites").structured_content["sites"]

        assert [site["id"] for site in sites] == [website["id"]]
        assert sites[0]["domain"] == website["domain"]


class TestATokenReachesOneWebsite:
    """Team A's token against team B's website, through every tool.

    Each refusal is paired with team B's own token succeeding on the same
    call, so a refusal can only be about whose token it is.
    """

    @pytest.fixture
    def teams(self, client, db, website, mcp_on):
        other = make_site(db)
        seed_traffic(db, website["id"], "teama")
        seed_traffic(db, other["id"], "teamb")
        return {
            "a": website["id"], "b": other["id"],
            "token_a": make_token(db, website["id"]),
            "token_b": make_token(db, other["id"]),
        }

    @pytest.mark.parametrize("tool", SITE_TOOLS)
    def test_another_teams_website_is_refused(self, teams, tool):
        theirs = call(teams["token_b"], tool, {"website_id": teams["b"]})
        assert not theirs.is_error, said(theirs)
        assert HOLDS_DATA[tool](theirs.structured_content), (
            "the control read nothing, so the refusal below proves nothing"
        )

        ours = call(teams["token_a"], tool, {"website_id": teams["b"]})

        assert ours.is_error, f"{tool} answered for another team's website"
        assert ours.structured_content is None
        assert "not found or access denied" in said(ours)
        assert "teamb" not in said(ours)

    @pytest.mark.parametrize("era", ERAS)
    def test_refused_in_both_eras(self, teams, era):
        ours = call(teams["token_a"], "get_top_pages", {"website_id": teams["b"]}, era=era)

        assert ours.is_error
        assert "teamb" not in said(ours)

    def test_list_sites_shows_only_the_tokens_own(self, teams):
        sites = call(teams["token_a"], "list_sites").structured_content["sites"]

        assert [site["id"] for site in sites] == [teams["a"]]

    def test_no_website_id_means_the_tokens_own(self, teams):
        pages = said(call(teams["token_a"], "get_top_pages"))

        assert "teama" in pages
        assert "teamb" not in pages

    @pytest.mark.parametrize("tool", SITE_TOOLS)
    def test_the_owners_other_website_is_refused_too(self, client, db, website, mcp_on, tool):
        """The narrower half of the rule, and the one a shortcut would break:
        the token's owner owns this website as well, and a session of theirs
        reads it. The token was minted for the first one only."""
        second = make_site(db, owner_email=website["email"])
        seed_traffic(db, second["id"], "second")
        token = make_token(db, website["id"])

        with_its_own = call(make_token(db, second["id"]), tool, {"website_id": second["id"]})
        assert HOLDS_DATA[tool](with_its_own.structured_content)

        result = call(token, tool, {"website_id": second["id"]})

        assert result.is_error, f"{tool} answered for a website outside the token's scope"
        assert result.structured_content is None
        assert "second" not in said(result)

    def test_a_website_that_does_not_exist_answers_the_same(self, teams):
        """Indistinguishable from one that exists and belongs to someone
        else, so a token cannot be used to find out which ids are taken."""
        missing = call(teams["token_a"], "get_overview", {"website_id": 2_000_000_000})
        foreign = call(teams["token_a"], "get_overview", {"website_id": teams["b"]})

        assert missing.is_error and foreign.is_error
        assert said(missing) == said(foreign)


class TestTheLimits:
    def test_requests_are_rate_limited_per_address(self, client, mcp_on):
        """Counted before the token is looked at, so guessing is throttled."""
        allowed = mcp_endpoint.RATE_LIMIT_PER_MINUTE

        statuses = {post(client, "t-guess").status_code for _ in range(allowed)}
        over = post(client, "t-guess")

        assert statuses == {401}
        assert over.status_code == 429

    def test_a_large_body_is_refused(self, client, db, website, mcp_on):
        token = make_token(db, website["id"])
        oversized = dict(INITIALIZE, padding="x" * (mcp_endpoint.MAX_BODY_BYTES + 1))

        async def main():
            async with mcp_endpoint.mcp_runtime():
                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=app), base_url=ORIGIN
                ) as http:
                    headers = dict(JSON_HEADERS, Authorization=f"Bearer {token}")
                    small = await http.post(MCP_PATH, json=INITIALIZE, headers=headers)
                    large = await http.post(MCP_PATH, json=oversized, headers=headers)
                    return small.status_code, large.status_code

        small, large = anyio.run(main)

        assert small == 200, "the control request failed, so the 413 proves nothing"
        assert large == 413

    def test_another_sites_page_cannot_drive_it(self, client, db, website, mcp_on):
        """A browser on some other origin, even holding a token."""
        token = make_token(db, website["id"])

        async def main():
            async with mcp_endpoint.mcp_runtime():
                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=app), base_url=ORIGIN
                ) as http:
                    headers = dict(JSON_HEADERS, Authorization=f"Bearer {token}")
                    own = await http.post(
                        MCP_PATH, json=INITIALIZE, headers=dict(headers, Origin=OWN_ORIGIN))
                    foreign = await http.post(
                        MCP_PATH, json=INITIALIZE,
                        headers=dict(headers, Origin="https://evil.example"))
                    return own.status_code, foreign.status_code

        own, foreign = anyio.run(main)

        assert own == 200
        assert foreign == 403
