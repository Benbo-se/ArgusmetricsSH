"""The tracking endpoints, tested by what they write rather than what they return.

Every assertion here checks the database. This project has repeatedly shipped
features whose UI rendered and whose endpoint returned 200 while nothing was
recorded, so a status code on its own proves nothing.
"""
import uuid

from sqlalchemy import text

from tests.conftest import count, reason


class TestTrackEvent:
    """POST /track-event, which serves both custom events and goals."""

    def test_event_with_properties_also_converts_a_goal(self, client, db, website, goal):
        """Regression: properties used to suppress the goal entirely.

        The route branched on properties, so an event carrying them recorded a
        custom event and returned without ever looking for a goal. Anyone whose
        site already sent properties on that event saw a goals page stuck at
        zero, with no error to explain it.
        """
        before = count(db, "goal_conversions", website_id=website["id"])

        response = client.post(
            "/api/v1/analytics/track-event",
            json={
                "tracking_code": website["tracking_code"],
                "event_name": goal["event_name"],
                "properties": {"plan": "pro"},
            },
        )

        assert response.status_code == 200
        assert count(db, "goal_conversions", website_id=website["id"]) == before + 1
        assert count(db, "custom_events", event_name=goal["event_name"]) == 1

    def test_event_without_properties_converts_a_goal(self, client, db, website, goal):
        before = count(db, "goal_conversions", website_id=website["id"])

        response = client.post(
            "/api/v1/analytics/track-event",
            json={
                "tracking_code": website["tracking_code"],
                "event_name": goal["event_name"],
            },
        )

        assert response.status_code == 200
        assert count(db, "goal_conversions", website_id=website["id"]) == before + 1

    def test_custom_event_without_a_goal_still_succeeds(self, client, db, website):
        """Most events have no goal behind them. That is not an error."""
        response = client.post(
            "/api/v1/analytics/track-event",
            json={
                "tracking_code": website["tracking_code"],
                "event_name": "no_goal_for_this",
                "properties": {"a": 1},
            },
        )

        assert response.status_code == 200
        assert count(db, "custom_events", event_name="no_goal_for_this") == 1

    def test_unknown_event_with_no_properties_is_rejected(self, client, website):
        """Nothing to record: no properties to store and no goal to convert."""
        response = client.post(
            "/api/v1/analytics/track-event",
            json={
                "tracking_code": website["tracking_code"],
                "event_name": "no_goal_for_this",
            },
        )

        assert response.status_code == 400
        assert "goal not found" in reason(response)

    def test_an_invalid_tracking_code_records_nothing(self, client, db):
        before = count(db, "custom_events")

        response = client.post(
            "/api/v1/analytics/track-event",
            json={
                "tracking_code": "zzzzzzzz",
                "event_name": "whatever",
                "properties": {"a": 1},
            },
        )

        assert response.status_code == 400
        assert "tracking code" in reason(response)
        assert count(db, "custom_events") == before


class TestTrackingCodeResolution:
    """The tracking path resolves a code without reading the websites table.

    A policy cannot see a query's WHERE clause, so letting the tracking
    context fetch one website by code would let it read every row, tokens and
    password hash included. The lookup goes through a SECURITY DEFINER
    function that returns four fields instead.
    """

    def test_it_returns_only_the_four_permitted_fields(self, db, website):
        from app.services.website_lookup import resolve_tracking_code

        found = resolve_tracking_code(db, website["tracking_code"])

        assert found is not None
        assert found.id == website["id"]
        assert found.domain == website["domain"]
        assert found.is_verified is True
        assert found.is_active is True
        assert not hasattr(found, "verification_token")
        assert not hasattr(found, "public_share_token")
        assert not hasattr(found, "public_password_hash")

    def test_an_unknown_code_resolves_to_nothing(self, db):
        from app.services.website_lookup import resolve_tracking_code

        assert resolve_tracking_code(db, "zzzzzzzz") is None

    def test_the_collision_check_sees_every_website(self, db, website):
        """Not just the caller's own, or it is not a check.

        Generating a code checks the candidate for collisions. If that check
        only saw the caller's websites it would call someone else's code free,
        and the insert would then fail on the unique constraint.
        """
        from app.services.website_lookup import tracking_code_exists

        assert tracking_code_exists(db, website["tracking_code"]) is True
        assert tracking_code_exists(db, "zzzzzzzz") is False


class TestShareTokenResolution:
    """A public dashboard is anonymous, so it sees six fields and no more."""

    def test_it_returns_only_what_a_public_dashboard_needs(self, db, shared_website):
        from app.services.website_lookup import resolve_share_token

        found = resolve_share_token(db, shared_website["share_token"])

        assert found is not None
        assert found.id == shared_website["id"]
        assert found.name.startswith("Test site")
        assert found.is_public is True
        # The reason this goes through a function at all.
        for hidden in (
            "user_email",
            "tracking_code",
            "verification_token",
            "email_reports_recipient",
        ):
            assert not hasattr(found, hidden), f"{hidden} reached an anonymous viewer"

    def test_an_unshared_website_does_not_resolve(self, db, website):
        """A link that was never published, or was revoked, resolves to nothing."""
        from app.services.website_lookup import resolve_share_token

        token = uuid.uuid4().hex[:32]
        db.execute(
            text(
                "UPDATE websites SET is_public = false, public_share_token = :t "
                "WHERE id = :w"
            ),
            {"t": token, "w": website["id"]},
        )
        db.commit()

        assert resolve_share_token(db, token) is None

    def test_an_unknown_token_resolves_to_nothing(self, db):
        from app.services.website_lookup import resolve_share_token

        assert resolve_share_token(db, "nope-not-a-real-token") is None


class TestRevenueTracking:
    """The legacy /revenue/track endpoint, which writes ecommerce events."""

    def test_it_records_a_purchase(self, client, db, website):
        """It was the one tracking endpoint without use_tracking_context.

        Its inserts were therefore refused by policy, while every other
        tracking endpoint worked. Invisible in development, where the app
        connects as the table owner.
        """
        transaction_id = f"txn-{uuid.uuid4().hex[:8]}"

        response = client.post(
            "/api/v1/revenue/track",
            json={
                "tracking_code": website["tracking_code"],
                "transaction_id": transaction_id,
                "amount": 249.0,
                "currency": "SEK",
            },
        )

        assert response.status_code == 200
        assert count(db, "ecommerce_events", transaction_id=transaction_id) == 1

    def test_it_declares_the_tracking_context(self, client, db, website):
        from app.database import RLS_INFO_KEY

        db.info.pop(RLS_INFO_KEY, None)
        client.post(
            "/api/v1/revenue/track",
            json={
                "tracking_code": website["tracking_code"],
                "transaction_id": f"txn-{uuid.uuid4().hex[:8]}",
                "amount": 10.0,
                "currency": "SEK",
            },
        )

        declared = db.info.get(RLS_INFO_KEY)
        assert declared is not None, "the endpoint declared no context"
        assert declared["context"] == "tracking"


class TestTrackPageview:
    def test_a_pageview_is_recorded(self, client, db, website):
        response = client.post(
            "/api/v1/analytics/track",
            json={"tracking_code": website["tracking_code"], "path": "/pricing"},
        )

        assert response.status_code == 200
        assert count(db, "pageviews", website_id=website["id"], path="/pricing") == 1

    def test_owner_email_is_filled_in_by_the_database(self, client, db, website):
        """The column every row-level security policy filters on.

        It is maintained by a trigger rather than by application code, so that
        no insert path can leave it wrong. A NULL here would hide a customer's
        own data from them; a wrong value would show it to someone else.
        """
        client.post(
            "/api/v1/analytics/track",
            json={"tracking_code": website["tracking_code"], "path": "/owner-check"},
        )

        owner = db.execute(
            text(
                "SELECT owner_email FROM pageviews "
                "WHERE website_id = :w AND path = '/owner-check'"
            ),
            {"w": website["id"]},
        ).scalar()

        assert owner == website["email"]

    def test_an_invalid_tracking_code_records_nothing(self, client, db):
        before = count(db, "pageviews")

        response = client.post(
            "/api/v1/analytics/track",
            json={"tracking_code": "zzzzzzzz", "path": "/"},
        )

        assert response.status_code == 400
        assert "tracking code" in reason(response)
        assert count(db, "pageviews") == before
