"""The public share link, from the outside.

This is the one path where someone with no account reaches a customer's data,
so the questions are narrower than elsewhere: does the link show the right
website and only that one, does turning sharing off actually close it, and
does the password gate hold.

The viewer is anonymous, so there is no session and no user context. The
request declares the public context pinned to a single website id, and the
policies scope every following query to it. These tests drive that from the
outside, through the same URL a stranger would open.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text


def _pageview(db, website_id, path):
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
            "t": datetime.now(timezone.utc) - timedelta(minutes=5),
        },
    )
    db.commit()


class TestSharedLink:
    def test_it_shows_the_website_it_points_at(self, client, db, shared_website):
        _pageview(db, shared_website["id"], "/shared-page")

        response = client.get(f"/public/{shared_website['share_token']}")

        assert response.status_code == 200, response.text[:200]
        assert "/shared-page" in response.text, (
            "the shared dashboard renders without the traffic it is sharing"
        )

    def test_an_unknown_token_is_refused(self, client, db):
        response = client.get(f"/public/{uuid.uuid4().hex}")

        assert response.status_code == 404

    def test_turning_sharing_off_closes_the_link(self, client, db, shared_website):
        """A revoked link has to stop working, not just disappear from the UI."""
        db.execute(
            text("UPDATE websites SET is_public = false WHERE id = :w"),
            {"w": shared_website["id"]},
        )
        db.commit()

        response = client.get(f"/public/{shared_website['share_token']}")

        assert response.status_code == 404, (
            "a link that was turned off still serves the dashboard"
        )

    def test_it_does_not_expose_the_tracking_code_or_tokens(
        self, client, db, shared_website
    ):
        """An anonymous page must not leak the credentials on the website row.

        The lookup goes through a SECURITY DEFINER function returning six
        fields for exactly this reason, but the template is free to be handed
        something else, so it is worth checking what comes out.
        """
        _pageview(db, shared_website["id"], "/")

        body = client.get(f"/public/{shared_website['share_token']}").text

        assert shared_website["tracking_code"] not in body, (
            "the public dashboard leaks the tracking code"
        )

        token = db.execute(
            text("SELECT verification_token FROM websites WHERE id = :w"),
            {"w": shared_website["id"]},
        ).scalar()
        assert token not in body, "the public dashboard leaks the verification token"

    def test_one_link_cannot_reach_another_website(self, client, db, shared_website):
        """The public context is pinned to a single website id."""
        db.execute(
            text(
                "INSERT INTO users (email, is_verified, created_at) "
                "VALUES ('other-owner@example.com', true, now()) "
                "ON CONFLICT (email) DO NOTHING"
            )
        )
        other = db.execute(
            text(
                "INSERT INTO websites (name, domain, user_email, tracking_code,"
                "                      verification_token, is_verified, is_active,"
                "                      email_reports_enabled, is_public,"
                "                      public_password_enabled, created_at) "
                "VALUES ('theirs', :d, 'other-owner@example.com', :tc, :vt,"
                "        true, true, false, false, false, now()) RETURNING id"
            ),
            {
                "d": f"https://theirs-{uuid.uuid4().hex[:8]}.example.com",
                "tc": uuid.uuid4().hex[:8],
                "vt": uuid.uuid4().hex,
            },
        ).scalar()
        _pageview(db, other, "/their-secret-page")
        _pageview(db, shared_website["id"], "/our-page")
        db.commit()

        body = client.get(f"/public/{shared_website['share_token']}").text

        assert "/our-page" in body
        assert "/their-secret-page" not in body, (
            "a share link exposed another customer's traffic"
        )


class TestPasswordGate:
    def _protect(self, db, website_id, password="a-good-password-9"):
        from app.services.password_service import PasswordService

        db.execute(
            text(
                "UPDATE websites SET public_password_enabled = true,"
                "       public_password_hash = :h WHERE id = :w"
            ),
            {"h": PasswordService.hash_password(password), "w": website_id},
        )
        db.commit()
        return password

    def test_a_protected_dashboard_asks_for_the_password(
        self, client, db, shared_website
    ):
        self._protect(db, shared_website["id"])
        _pageview(db, shared_website["id"], "/behind-the-gate")

        response = client.get(f"/public/{shared_website['share_token']}")

        # 401 with the prompt rendered in the body, rather than a redirect:
        # unauthorized is the honest status and the form is what the visitor
        # needs. What matters is which of the two things comes back.
        assert response.status_code == 401
        assert "/behind-the-gate" not in response.text, (
            "the data is served before the password is entered"
        )
        assert "password" in response.text.lower(), (
            "the visitor is refused without being told how to get in"
        )

    def test_the_check_endpoint_reports_that_a_password_is_needed(
        self, client, db, shared_website
    ):
        self._protect(db, shared_website["id"])

        body = client.get(
            f"/api/v1/dashboard-password/check/{shared_website['share_token']}"
        ).json()

        assert body["password_required"] is True

    def test_the_wrong_password_is_refused(self, client, db, shared_website):
        self._protect(db, shared_website["id"])

        response = client.post(
            f"/api/v1/dashboard-password/verify/{shared_website['share_token']}",
            json={"password": "not-it"},
        )

        assert response.json().get("verified") is not True, "any password works"

    def test_the_right_password_is_accepted(self, client, db, shared_website):
        password = self._protect(db, shared_website["id"])

        response = client.post(
            f"/api/v1/dashboard-password/verify/{shared_website['share_token']}",
            json={"password": password},
        )

        assert response.status_code == 200, response.text
        assert response.json().get("verified") is True
