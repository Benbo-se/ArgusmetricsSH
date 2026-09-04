"""Does each feature actually write what its interface promises?

This project has shipped features whose page rendered, whose endpoint returned
200, and which recorded nothing at all. Funnels, the delete button, traffic
alerts and goal conversions were each found that way, one at a time, by
driving them by hand and then looking in the database.

So every test here asserts on rows, never on a status code alone. A 200 is not
evidence.

Coverage is deliberately breadth-first over the mutating routes rather than
depth on any one of them: the failure being hunted is a feature that does
nothing, not an edge case in a feature that works.
"""
import pathlib
import uuid

from sqlalchemy import text

from tests.conftest import count


class TestGoals:
    def test_creating_a_goal_stores_it(self, owner_client, db, website):
        response = owner_client.post(
            f"/api/v1/analytics/goals?website_id={website['id']}",
            json={"name": "Signup", "event_name": "signup_done"},
        )

        assert response.status_code == 201, response.text
        assert count(db, "goals", website_id=website["id"]) == 1

    def test_deleting_a_goal_removes_it(self, owner_client, db, website):
        created = owner_client.post(
            f"/api/v1/analytics/goals?website_id={website['id']}",
            json={"name": "Signup", "event_name": "signup_done"},
        ).json()

        response = owner_client.delete(
            f"/api/v1/analytics/goals/{created['id']}?website_id={website['id']}"
        )

        assert response.status_code == 200, response.text
        assert count(db, "goals", website_id=website["id"]) == 0


class TestFunnels:
    def test_creating_a_funnel_stores_its_steps(self, owner_client, db, website):
        response = owner_client.post(
            f"/api/v1/funnels?website_id={website['id']}",
            json={
                "name": "Checkout",
                "steps": [
                    {"step": 1, "name": "Landing", "path": "/"},
                    {"step": 2, "name": "Checkout", "path": "/checkout"},
                ],
            },
        )

        assert response.status_code == 200, response.text
        stored = db.execute(
            text("SELECT steps FROM funnels WHERE website_id = :w"),
            {"w": website["id"]},
        ).scalar()
        assert stored is not None, "the funnel was not stored"
        assert len(stored) == 2, "the steps were dropped on the way in"

    def test_deleting_a_funnel_removes_it(self, owner_client, db, website):
        created = owner_client.post(
            f"/api/v1/funnels?website_id={website['id']}",
            json={
                "name": "Checkout",
                "steps": [
                    {"step": 1, "name": "L", "path": "/"},
                    {"step": 2, "name": "C", "path": "/checkout"},
                ],
            },
        ).json()

        response = owner_client.delete(f"/api/v1/funnels/{created['id']}")

        assert response.status_code == 200, response.text

        # A soft delete, deliberately: the row stays so historical funnel
        # events keep resolving, and is_active is what takes it out of the
        # dashboard and out of the tracking path.
        active = db.execute(
            text("SELECT is_active FROM funnels WHERE id = :i"),
            {"i": created["id"]},
        ).scalar()
        assert active is False, "the delete button returned 200 and changed nothing"

        listed = owner_client.get(f"/api/v1/funnels?website_id={website['id']}").json()
        assert not any(f["id"] == created["id"] for f in listed), (
            "a deleted funnel is still listed"
        )


class TestApiTokens:
    def test_creating_a_token_stores_a_hash_not_the_token(self, owner_client, db, website):
        response = owner_client.post(
            f"/api/v1/analytics/tokens?website_id={website['id']}",
            json={"name": "CI"},
        )

        assert response.status_code == 201, response.text
        raw = response.json()["token"]

        stored = db.execute(
            text("SELECT token FROM api_tokens WHERE website_id = :w"),
            {"w": website["id"]},
        ).scalar()
        assert stored is not None, "no token row was written"
        assert stored != raw, "the raw token is stored, so a database leak hands them out"

    def test_deleting_a_token_removes_it(self, owner_client, db, website):
        created = owner_client.post(
            f"/api/v1/analytics/tokens?website_id={website['id']}",
            json={"name": "CI"},
        ).json()

        response = owner_client.delete(
            f"/api/v1/analytics/tokens/{created['id']}?website_id={website['id']}"
        )

        assert response.status_code == 200, response.text
        assert count(db, "api_tokens", website_id=website["id"]) == 0


class TestAlertSettings:
    def test_updating_the_threshold_persists(self, owner_client, db, website):
        response = owner_client.put(
            f"/api/v1/analytics/alerts/{website['id']}",
            json={"spike_threshold": 4.5, "email_enabled": True},
        )

        assert response.status_code == 200, response.text
        stored = db.execute(
            text("SELECT spike_threshold FROM alert_settings WHERE website_id = :w"),
            {"w": website["id"]},
        ).scalar()
        assert stored == 4.5, "the alert page accepted a threshold it never saved"


    def test_the_settings_page_exposes_the_control(self, owner_client, db, website):
        """The half that was missing.

        The API, the service and the hourly job all existed. Nothing in the
        interface ever called them, so no website had alert settings, and the
        spike check returned None for every site on every run. A feature with
        no way to turn it on is not a feature.
        """
        page = owner_client.get(f"/dashboard/website/{website['id']}/settings")

        assert page.status_code == 200
        assert "Traffic Alerts" in page.text, "no way to configure alerts"
        assert "spike-threshold" in page.text, "no threshold control"

    def test_saving_works_for_a_website_that_has_no_settings_yet(
        self, owner_client, db, website
    ):
        """Which is every website, until someone saves for the first time."""
        assert count(db, "alert_settings", website_id=website["id"]) == 0

        response = owner_client.put(
            f"/api/v1/analytics/alerts/{website['id']}",
            json={"spike_threshold": 3.0, "email_enabled": True},
        )

        assert response.status_code == 200, response.text
        assert count(db, "alert_settings", website_id=website["id"]) == 1

    def test_alerts_are_addressed_to_the_website_owner(self, owner_client, db, website):
        """Not to whoever saved, so an admin cannot redirect someone's alerts."""
        owner_client.put(
            f"/api/v1/analytics/alerts/{website['id']}",
            json={"spike_threshold": 3.0, "email_enabled": True},
        )

        recipient = db.execute(
            text("SELECT alert_email FROM alert_settings WHERE website_id = :w"),
            {"w": website["id"]},
        ).scalar()
        assert recipient == website["email"]


class TestTeam:
    def test_inviting_a_member_creates_a_pending_row(self, owner_client, db, website):
        invitee = f"mate-{uuid.uuid4().hex[:8]}@example.com"

        response = owner_client.post(
            f"/api/v1/websites/{website['id']}/members",
            json={"email": invitee, "role": "viewer"},
        )

        assert response.status_code in (200, 201), response.text
        row = db.execute(
            text(
                "SELECT status::text, invite_token FROM website_members "
                "WHERE website_id = :w AND user_email = :e"
            ),
            {"w": website["id"], "e": invitee},
        ).first()
        assert row is not None, "the invitation was never stored"
        assert row.status == "pending"
        assert row.invite_token, "no invite token, so the link cannot work"

    def test_removing_a_member_revokes_their_access(self, owner_client, db, website):
        invitee = f"mate-{uuid.uuid4().hex[:8]}@example.com"
        owner_client.post(
            f"/api/v1/websites/{website['id']}/members",
            json={"email": invitee, "role": "viewer"},
        )

        response = owner_client.delete(
            f"/api/v1/websites/{website['id']}/members/{invitee}"
        )

        assert response.status_code == 200, response.text
        status = db.execute(
            text(
                "SELECT status::text FROM website_members "
                "WHERE website_id = :w AND user_email = :e"
            ),
            {"w": website["id"], "e": invitee},
        ).scalar()
        assert status == "revoked", f"access was not revoked, status is {status}"


class TestPublicSharing:
    def test_enabling_sharing_mints_a_token(self, owner_client, db, website):
        response = owner_client.put(
            f"/api/v1/websites/{website['id']}/public-access",
            json={"is_public": True},
        )

        assert response.status_code == 200, response.text
        row = db.execute(
            text(
                "SELECT is_public, public_share_token FROM websites WHERE id = :w"
            ),
            {"w": website["id"]},
        ).first()
        assert row.is_public is True
        assert row.public_share_token, "sharing was enabled with no link to share"

    def test_the_settings_page_exposes_password_protection(
        self, owner_client, db, website
    ):
        """The third feature found complete in the backend and absent from the UI.

        Sharing could be switched on from the settings page, but nothing there
        called dashboard-password/set, so a customer could publish a dashboard
        and had no way to put a password on it. The public page has rendered a
        password prompt the whole time, for a password nobody could set.
        """
        page = owner_client.get(f"/dashboard/website/{website['id']}/settings")

        assert page.status_code == 200
        assert "Password protection" in page.text, "no way to protect a shared link"

        # The controls are on the page, and the component behind them calls
        # both endpoints. The calls moved out of the template when the
        # dashboard went to Alpine's CSP build, so looking for the URLs in the
        # HTML would now pass or fail on where the code lives rather than on
        # whether the feature is wired.
        assert 'x-data="publicSharing"' in page.text, (
            "the password controls are rendered but no component drives them"
        )

        component = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app" / "static" / "js" / "alpine-components.js"
        ).read_text()
        assert "dashboard-password/set" in component
        assert "dashboard-password/remove" in component, (
            "a password can be set and never taken off"
        )

    def test_removing_the_password_reopens_the_link(self, owner_client, db, website):
        owner_client.put(
            f"/api/v1/websites/{website['id']}/public-access",
            json={"is_public": True},
        )
        owner_client.post(
            "/api/v1/dashboard-password/set",
            json={"website_id": website["id"], "password": "a-good-password-9"},
        )

        response = owner_client.post(
            "/api/v1/dashboard-password/remove",
            json={"website_id": website["id"]},
        )

        assert response.status_code == 200, response.text
        row = db.execute(
            text(
                "SELECT public_password_enabled, public_password_hash "
                "FROM websites WHERE id = :w"
            ),
            {"w": website["id"]},
        ).first()
        assert row.public_password_enabled is False
        assert not row.public_password_hash, "the old hash is still on the row"

    def test_setting_a_password_stores_a_hash(self, owner_client, db, website):
        owner_client.put(
            f"/api/v1/websites/{website['id']}/public-access",
            json={"is_public": True},
        )

        response = owner_client.post(
            "/api/v1/dashboard-password/set",
            json={"website_id": website["id"], "password": "a-good-password-9"},
        )

        assert response.status_code == 200, response.text
        row = db.execute(
            text(
                "SELECT public_password_enabled, public_password_hash "
                "FROM websites WHERE id = :w"
            ),
            {"w": website["id"]},
        ).first()
        assert row.public_password_enabled is True
        assert row.public_password_hash, "password protection is on with no hash to check"
        assert "a-good-password-9" not in row.public_password_hash, (
            "the password is stored in the clear"
        )


class TestWebsites:
    def test_creating_a_website_generates_a_tracking_code(self, owner_client, db):
        domain = f"https://new-{uuid.uuid4().hex[:8]}.example.invalid"

        response = owner_client.post(
            "/api/v1/websites/", json={"name": "New", "domain": domain}
        )

        assert response.status_code in (200, 201), response.text
        body = response.json()
        assert body["tracking_code"], "a website with no tracking code cannot record anything"
        assert count(db, "websites", domain=domain) == 1

    def test_deleting_a_website_removes_it(self, owner_client, db, website):
        response = owner_client.delete(f"/api/v1/websites/{website['id']}")

        assert response.status_code == 200, response.text
        assert count(db, "websites", id=website["id"]) == 0

    def test_deleting_a_website_takes_its_traffic_with_it(self, owner_client, db, website):
        """The cascade matters: orphaned pageviews would keep counting."""
        db.execute(
            text(
                "INSERT INTO pageviews (website_id, path, visitor_hash, timestamp) "
                "VALUES (:w, '/gone', 'h', now())"
            ),
            {"w": website["id"]},
        )
        db.commit()
        assert count(db, "pageviews", website_id=website["id"]) == 1

        owner_client.delete(f"/api/v1/websites/{website['id']}")

        assert count(db, "pageviews", website_id=website["id"]) == 0


class TestEmailReports:
    def test_configuring_reports_persists_the_schedule(self, owner_client, db, website):
        response = owner_client.post(
            "/api/v1/email-reports/configure",
            json={
                "website_id": website["id"],
                "enabled": True,
                "frequency": "weekly",
                "recipient": "reports@example.com",
                "day": 1,
            },
        )

        assert response.status_code == 200, response.text
        row = db.execute(
            text(
                "SELECT email_reports_enabled, email_reports_frequency,"
                "       email_reports_recipient "
                "FROM websites WHERE id = :w"
            ),
            {"w": website["id"]},
        ).first()
        assert row.email_reports_enabled is True, (
            "the form accepted a schedule the scheduler will never see"
        )
        assert row.email_reports_frequency == "weekly"
        assert row.email_reports_recipient == "reports@example.com"
