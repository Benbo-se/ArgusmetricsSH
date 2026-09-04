"""Per-account limits: the monthly event limit and the website cap.

Two things are worth testing here and they pull in opposite directions.

The limit has to actually refuse, or it is decoration. And it has to be off by
default and fail open, or a self-hosted instance that never asked for a limit
loses its owner's traffic because of a counter it does not care about.

The counter itself is maintained by a database trigger, so these tests write
real rows through the real recording path rather than setting the count by
hand. A test that fakes the counter would pass while the trigger was dropped.
"""
import pytest
from sqlalchemy import text

from app.config import settings
from app.services.usage_service import get_usage, may_record


def _usage_row(db, email):
    return db.execute(
        text(
            "SELECT events FROM account_usage "
            " WHERE owner_email = :e "
            "   AND period_start = date_trunc('month', now())::date"
        ),
        {"e": email},
    ).scalar()


class TestTheCounter:
    """The trigger, which everything else rests on."""

    def test_recording_a_pageview_increments_the_account(self, client, website, db):
        before = _usage_row(db, website["email"]) or 0

        response = client.post(
            "/api/v1/analytics/track",
            json={"tracking_code": website["tracking_code"], "path": "/counted"},
        )
        assert response.status_code == 200

        assert _usage_row(db, website["email"]) == before + 1

    def test_custom_events_count_too(self, client, website, db):
        before = _usage_row(db, website["email"]) or 0

        client.post(
            "/api/v1/analytics/track-event",
            # Properties are what makes this a custom event rather than only
            # a goal lookup, which is what the counter counts.
            json={
                "tracking_code": website["tracking_code"],
                "event_name": "signup",
                "properties": {"plan": "free"},
            },
        )

        assert _usage_row(db, website["email"]) == before + 1

    def test_two_websites_share_one_account_counter(
        self, client, website, second_website, db
    ):
        """The whole point of counting per account rather than per website."""
        before = _usage_row(db, website["email"]) or 0

        for code in (website["tracking_code"], second_website["tracking_code"]):
            client.post(
                "/api/v1/analytics/track",
                json={"tracking_code": code, "path": "/shared"},
            )

        assert _usage_row(db, website["email"]) == before + 2


class TestTheMonthlyLimit:
    def test_off_by_default(self, db, website):
        """A self-hosted instance has no limit unless one is configured."""
        assert settings.MONTHLY_EVENT_LIMIT == 0
        usage = get_usage(db, website["email"])
        assert usage.limited is False
        assert usage.exceeded is False
        assert may_record(db, website["email"]) is True

    def test_refuses_once_reached(self, client, website, db, monkeypatch):
        used = _usage_row(db, website["email"]) or 0
        monkeypatch.setattr(settings, "MONTHLY_EVENT_LIMIT", used + 1)

        first = client.post(
            "/api/v1/analytics/track",
            json={"tracking_code": website["tracking_code"], "path": "/last-one"},
        )
        assert first.status_code == 200
        assert _usage_row(db, website["email"]) == used + 1

        # The account is now exactly at the limit.
        blocked = client.post(
            "/api/v1/analytics/track",
            json={"tracking_code": website["tracking_code"], "path": "/over"},
        )

        # No row was written, whatever the endpoint chose to answer.
        assert (
            db.execute(
                text("SELECT count(*) FROM pageviews WHERE path = '/over'")
            ).scalar()
            == 0
        )
        assert _usage_row(db, website["email"]) == used + 1

        # 429, not 400: the request was fine, the account is full.
        assert blocked.status_code == 429

    def test_every_recording_path_is_covered(self, client, website, db, monkeypatch):
        """A limit one endpoint honours and another ignores is not a limit."""
        # Record one event with no limit, then set the limit below that, so
        # the account is already over it when each path is tried.
        client.post(
            "/api/v1/analytics/track",
            json={"tracking_code": website["tracking_code"], "path": "/before"},
        )
        before = _usage_row(db, website["email"]) or 0
        assert before >= 1
        monkeypatch.setattr(settings, "MONTHLY_EVENT_LIMIT", 1)

        payloads = [
            ("/api/v1/analytics/track", {"path": "/p"}),
            (
                "/api/v1/analytics/track-event",
                {"event_name": "e", "properties": {"k": "v"}},
            ),
            (
                "/api/v1/analytics/track-ecommerce",
                {
                    "event_type": "purchase",
                    "transaction_id": "over-limit-1",
                    "revenue": 10.0,
                },
            ),
        ]

        for url, body in payloads:
            client.post(url, json={"tracking_code": website["tracking_code"], **body})

        # Already over the limit before any of these, so none may be stored.
        assert _usage_row(db, website["email"]) == before

    def test_fails_open_when_the_counter_cannot_be_read(
        self, db, website, monkeypatch
    ):
        """Losing traffic is worse than letting a few extra events through."""
        monkeypatch.setattr(settings, "MONTHLY_EVENT_LIMIT", 1)

        def broken(*args, **kwargs):
            raise RuntimeError("counter unavailable")

        monkeypatch.setattr("app.services.usage_service.get_usage", broken)

        assert may_record(db, website["email"]) is True


class TestTheWarning:
    """Warning before the cap, since after it the data is already gone."""

    def test_nearly_exceeded_at_eighty_percent(self, db, website, monkeypatch):
        used = _usage_row(db, website["email"]) or 0
        monkeypatch.setattr(settings, "MONTHLY_EVENT_LIMIT", max(2, int(used / 0.8) + 1))

        usage = get_usage(db, website["email"])
        assert usage.nearly_exceeded is (0.8 <= (usage.fraction or 0) < 1)
        assert usage.exceeded is False

    def test_shown_on_the_dashboard(self, owner_client, website, db):
        """Configured limits appear where the customer will see them."""
        used = _usage_row(db, website["email"]) or 0
        from app.config import settings as live

        original = live.MONTHLY_EVENT_LIMIT
        live.MONTHLY_EVENT_LIMIT = used + 100
        try:
            body = owner_client.get("/dashboard").text
        finally:
            live.MONTHLY_EVENT_LIMIT = original

        assert "Events this month" in body
        assert f"{used + 100:,}" in body

    def test_absent_when_there_is_no_limit(self, owner_client, website):
        assert settings.MONTHLY_EVENT_LIMIT == 0
        body = owner_client.get("/dashboard").text
        assert "Events this month" not in body


class TestTheWebsiteCap:
    def test_generous_by_default(self):
        """A limit against abuse, not against having several sites."""
        assert settings.MAX_WEBSITES_PER_ACCOUNT >= 50

    def test_refuses_past_the_cap_and_says_why(self, db, website, monkeypatch):
        from app.services.website_service import WebsiteService

        monkeypatch.setattr(settings, "MAX_WEBSITES_PER_ACCOUNT", 1)
        service = WebsiteService(db)

        with pytest.raises(ValueError) as caught:
            service.create_website(
                user_email=website["email"],
                name="One too many",
                domain="https://one-too-many.example",
            )

        message = str(caught.value)
        assert "maximum" in message.lower()
        assert "1" in message

    def test_the_cap_is_per_account(self, db, website, monkeypatch):
        """Another account is not affected by this one being full."""
        from app.services.website_service import WebsiteService

        monkeypatch.setattr(settings, "MAX_WEBSITES_PER_ACCOUNT", 1)
        db.execute(
            text(
                "INSERT INTO users (email, is_verified, created_at) "
                "VALUES ('somebody-else@example.com', true, now()) "
                "ON CONFLICT (email) DO NOTHING"
            )
        )

        created = WebsiteService(db).create_website(
            user_email="somebody-else@example.com",
            name="Theirs",
            domain="https://somebody-else.example",
        )
        assert created.id is not None
