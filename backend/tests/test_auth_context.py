"""Every authenticated request must declare a row-level security context.

A request that declares none matches no policy, so it reads nothing from the
five policied traffic tables. That failure is silent: the endpoint returns
200 with empty data rather than an error, and it is invisible in development,
where the app connects as the table owner and policies never apply.

That is exactly how the API-token path shipped broken. These tests assert on
the context the request declared, not on the rows it read, so they catch the
omission even when running as the owner.
"""
import uuid

import pytest
from sqlalchemy import text

from app.database import RLS_INFO_KEY
from app.services.token_service import TokenService
from tests.conftest import ws_headers


def _make_api_token(db, website_id):
    """A real API token for the fixture website, hashed the way the app does."""
    raw = f"t-{uuid.uuid4().hex}"
    db.execute(
        text(
            "INSERT INTO api_tokens (website_id, name, token, created_at) "
            "VALUES (:w, 'test token', :t, now())"
        ),
        {"w": website_id, "t": TokenService.hash_token(raw)},
    )
    db.commit()
    return raw


class TestUnauthenticatedCredentials:
    """Paths whose credential is a token in a URL, with nobody logged in.

    A tracking code, a share token and an invitation token all identify the
    request without identifying a user, so there is no context to declare.
    Each resolves through a SECURITY DEFINER function instead.
    """

    def test_an_invitation_link_resolves_without_a_context(self, client, db, website):
        """Broken by the website_members policies until this was fixed.

        Whoever opens the link is not logged in and may have no account, so
        the lookup matched no policy and every invitation reported "not found
        or already accepted".
        """
        from app.services.website_lookup import resolve_invite_token

        token = f"inv-{uuid.uuid4().hex}"
        db.execute(
            text(
                "INSERT INTO website_members "
                "  (website_id, user_email, role, invited_at, status, invite_token) "
                "VALUES (:w, :e, 'viewer', now(), 'pending'::memberstatus, :t)"
            ),
            {"w": website["id"], "e": "invitee@example.invalid", "t": token},
        )
        db.commit()

        invite = resolve_invite_token(db, token)

        assert invite is not None, "the invitation link resolved to nothing"
        assert invite.website_name.startswith("Test site")
        assert invite.role == "viewer"
        assert invite.invitee_email == "invitee@example.invalid"

    def test_an_accepted_invitation_cannot_be_replayed(self, client, db, website):
        """Only pending invitations resolve, so a used link reveals nothing."""
        from app.services.website_lookup import resolve_invite_token

        token = f"inv-{uuid.uuid4().hex}"
        db.execute(
            text(
                "INSERT INTO website_members "
                "  (website_id, user_email, role, invited_at, status, invite_token) "
                "VALUES (:w, :e, 'viewer', now(), 'active'::memberstatus, :t)"
            ),
            {"w": website["id"], "e": "accepted@example.invalid", "t": token},
        )
        db.commit()

        assert resolve_invite_token(db, token) is None

    def test_an_unknown_invitation_token_resolves_to_nothing(self, db):
        from app.services.website_lookup import resolve_invite_token

        assert resolve_invite_token(db, "inv-nope") is None


class TestApiTokenAuthentication:
    def test_it_declares_a_user_context(self, client, db, website):
        """The bug this file exists for.

        The token path resolved a user and returned without calling
        set_rls_context, so the request ran with no context and read nothing
        from any policied table.
        """
        token = _make_api_token(db, website["id"])

        response = client.get(
            f"/api/v1/analytics/stats/{website['id']}"
            "?start_date=2026-01-01&end_date=2026-12-31",
            headers={"X-API-Token": token},
        )

        assert response.status_code == 200

        declared = db.info.get(RLS_INFO_KEY)
        assert declared is not None, "the request declared no context at all"
        assert declared["context"] == "user"
        assert declared["user_email"] == website["email"]

    def test_websocket_endpoints_declare_one_too(self, client, db, website):
        """The websocket router is a separate entry point, and it was missed.

        Neither /ws/live nor /ws/debug declared a context, so once websites
        and website_members were policied the access check read nothing and
        refused everyone. As argus_app, check_website_access returned None
        without a context and OWNER with one.
        """
        token = _make_api_token(db, website["id"])

        for path in ("/ws/live", "/ws/debug"):
            db.info.pop(RLS_INFO_KEY, None)

            with client.websocket_connect(
                f"{path}/{website['id']}?api_token={token}",
                headers=ws_headers(),
            ):
                pass

            declared = db.info.get(RLS_INFO_KEY)
            assert declared is not None, f"{path} declared no context"
            assert declared["context"] == "user"
            assert declared["user_email"] == website["email"]

    def test_a_websocket_with_a_bad_token_is_refused(self, client, db, website):
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"/ws/live/{website['id']}?api_token=t-not-a-real-token",
                headers=ws_headers(),
            ) as ws:
                ws.receive_text()

    def test_an_invalid_token_is_rejected(self, client, db, website):
        response = client.get(
            f"/api/v1/analytics/stats/{website['id']}"
            "?start_date=2026-01-01&end_date=2026-12-31",
            headers={"X-API-Token": "t-not-a-real-token"},
        )

        assert response.status_code == 401

    def test_the_token_stays_scoped_to_its_own_website(self, client, db, website):
        """A token is minted for one website and must not unlock the others.

        Both the ownership check and the scope check answer 404 with the same
        wording, so a bare "404" here would not say which one refused. The
        test pins it down by showing the same user reaching the same website
        with session authentication, where only the scope marker is absent.
        """
        from app.main import app
        from app.models.user import User
        from app.routers.analytics import get_current_user_or_token

        other_id = db.execute(
            text(
                "INSERT INTO websites (name, domain, user_email, tracking_code,"
                "                      verification_token, is_verified, is_active,"
                "                      email_reports_enabled, is_public,"
                "                      public_password_enabled, created_at) "
                "VALUES ('other', :d, :e, :tc, :vt, true, true, false, false, false, now()) "
                "RETURNING id"
            ),
            {
                "d": f"https://other-{uuid.uuid4().hex[:8]}.example.invalid",
                "e": website["email"],
                "tc": uuid.uuid4().hex[:8],
                "vt": uuid.uuid4().hex,
            },
        ).scalar()
        db.commit()

        token = _make_api_token(db, website["id"])
        stats_url = (
            f"/api/v1/analytics/stats/{other_id}"
            "?start_date=2026-01-01&end_date=2026-12-31"
        )

        # Session authentication: the same person, no token scope. This has to
        # succeed, or the assertion below would prove nothing.
        user = db.query(User).filter(User.email == website["email"]).first()
        app.dependency_overrides[get_current_user_or_token] = lambda: user
        try:
            with_session = client.get(stats_url)
        finally:
            del app.dependency_overrides[get_current_user_or_token]

        assert with_session.status_code == 200, (
            "the owner cannot reach this website even with a session, so the "
            "refusal below would not be about token scope"
        )

        with_token = client.get(stats_url, headers={"X-API-Token": token})

        # 404 rather than 403, deliberately: refusing without confirming that
        # the website exists.
        assert with_token.status_code == 404


class TestApiTokensReadGoalAndFunnelStats:
    """#112: a token reads conversions as well as traffic, and nothing more.

    Goal and funnel stats required a session, so a service reporting for a
    site could read /stats and /export but not the one number it needed.
    Every refusal below is paired with the same owner succeeding by session,
    so a 404 can only be the token's scope and not ownership.
    """

    def _second_site(self, db, owner_email):
        site_id = db.execute(
            text(
                "INSERT INTO websites (name, domain, user_email, tracking_code,"
                "                      verification_token, is_verified, is_active,"
                "                      email_reports_enabled, is_public,"
                "                      public_password_enabled, created_at) "
                "VALUES ('other', :d, :e, :tc, :vt, true, true, false, false, false, now()) "
                "RETURNING id"
            ),
            {
                "d": f"https://other-{uuid.uuid4().hex[:8]}.example.invalid",
                "e": owner_email,
                "tc": uuid.uuid4().hex[:8],
                "vt": uuid.uuid4().hex,
            },
        ).scalar()
        db.commit()
        return site_id

    def _funnel(self, db, website_id):
        funnel_id = db.execute(
            text(
                "INSERT INTO funnels (website_id, name, steps, created_at, is_active) "
                "VALUES (:w, 'Checkout', CAST(:s AS json), now(), true) RETURNING id"
            ),
            {"w": website_id, "s": '[{"step": 1, "name": "Cart", "event_name": "cart"}]'},
        ).scalar()
        db.commit()
        return funnel_id

    def _as_session(self, client, db, email, method, url):
        from app.main import app
        from app.models.user import User
        from app.routers.analytics import get_current_user_or_token

        user = db.query(User).filter(User.email == email).first()
        app.dependency_overrides[get_current_user_or_token] = lambda: user
        try:
            return client.request(method, url)
        finally:
            del app.dependency_overrides[get_current_user_or_token]

    def test_a_token_reads_its_own_sites_goal_and_funnel_stats(self, client, db, website):
        token = _make_api_token(db, website["id"])
        funnel_id = self._funnel(db, website["id"])

        goals = client.get(f"/api/v1/analytics/goals/{website['id']}",
                           headers={"X-API-Token": token})
        funnel = client.get(f"/api/v1/funnels/{funnel_id}/stats",
                            headers={"X-API-Token": token})

        assert goals.status_code == 200, goals.text[:200]
        assert funnel.status_code == 200, funnel.text[:200]

    def test_goal_stats_of_another_site_are_404_with_the_token(self, client, db, website):
        other = self._second_site(db, website["email"])
        token = _make_api_token(db, website["id"])
        url = f"/api/v1/analytics/goals/{other}"

        assert self._as_session(client, db, website["email"], "GET", url).status_code == 200
        assert client.get(url, headers={"X-API-Token": token}).status_code == 404

    def test_a_funnel_on_another_site_is_404_not_403(self, client, db, website):
        """403 would confirm the funnel exists. The route has no website id,
        so the scope is checked after the lookup, and has to answer the same
        as a funnel that is not there."""
        other = self._second_site(db, website["email"])
        funnel_id = self._funnel(db, other)
        token = _make_api_token(db, website["id"])
        url = f"/api/v1/funnels/{funnel_id}/stats"

        assert self._as_session(client, db, website["email"], "GET", url).status_code == 200
        assert client.get(url, headers={"X-API-Token": token}).status_code == 404

    def test_a_token_still_cannot_write(self, client, db, website):
        token = _make_api_token(db, website["id"])
        funnel_id = self._funnel(db, website["id"])
        headers = {"X-API-Token": token}
        wid = website["id"]

        attempts = {
            "create goal": client.post(f"/api/v1/analytics/goals?website_id={wid}",
                                       json={"name": "x", "event_name": "x"}, headers=headers),
            "update goal": client.put(f"/api/v1/analytics/goals/1?website_id={wid}",
                                      json={"name": "x", "event_name": "x"}, headers=headers),
            "delete goal": client.delete(f"/api/v1/analytics/goals/1?website_id={wid}",
                                         headers=headers),
            "create funnel": client.post(f"/api/v1/funnels?website_id={wid}",
                                         json={"name": "x", "steps": []}, headers=headers),
            "delete funnel": client.delete(f"/api/v1/funnels/{funnel_id}", headers=headers),
        }

        allowed = {k: r.status_code for k, r in attempts.items() if r.status_code not in (401, 404, 405)}
        assert not allowed, f"a token was accepted for writing: {allowed}"
