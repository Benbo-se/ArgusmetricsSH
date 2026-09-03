"""The tracking endpoints, tested by what they write rather than what they return.

Every assertion here checks the database. This project has repeatedly shipped
features whose UI rendered and whose endpoint returned 200 while nothing was
recorded, so a status code on its own proves nothing.
"""
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
