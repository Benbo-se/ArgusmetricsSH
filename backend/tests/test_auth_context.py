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

from sqlalchemy import text

from app.database import RLS_INFO_KEY
from app.services.token_service import TokenService


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
