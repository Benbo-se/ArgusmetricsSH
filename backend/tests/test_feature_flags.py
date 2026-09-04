"""The feature flags have to do what their names say.

All three of them were read by nothing. ENABLE_REGISTRATION was the dangerous
one: an operator could set it to false, believe signup was closed, and have it
stay wide open. A setting that lies about a security control is worse than no
setting, because it stops anyone from looking.

So these test the flags against behaviour, not against configuration. Reading
settings.ENABLE_REGISTRATION back and asserting it is false would have passed
the whole time it did nothing.
"""
import pytest

from app.config import settings


class TestRegistrationCanBeClosed:
    def test_open_by_default(self, client):
        """Closing it must be a decision somebody made, not a surprise."""
        assert settings.ENABLE_REGISTRATION is True

    def test_the_endpoint_refuses_when_closed(self, client, monkeypatch):
        """The endpoint, not the page. Hiding a form closes nothing."""
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)

        response = client.post(
            "/api/v1/auth/signup",
            json={"email": "nobody@example.com", "password": "Str0ng-Passw0rd!x"},
        )

        assert response.status_code == 403
        # The app reshapes HTTPException bodies into {error, message, status_code}.
        assert "closed" in response.json()["message"].lower()

    def test_no_account_is_created_when_closed(self, client, db, monkeypatch):
        from sqlalchemy import text

        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)
        email = "definitely-not-created@example.com"

        client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "Str0ng-Passw0rd!x"},
        )

        count = db.execute(
            text("SELECT count(*) FROM users WHERE email = :e"), {"e": email}
        ).scalar()
        assert count == 0

    def test_the_page_does_not_offer_a_form_that_cannot_work(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)

        response = client.get("/signup", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/login"

    def test_signup_still_works_when_open(self, client, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", True)

        response = client.post(
            "/api/v1/auth/signup",
            json={"email": "someone-new@example.com", "password": "Str0ng-Passw0rd!x"},
        )

        assert response.status_code == 201


class TestVerificationCanBeTurnedOff:
    """An instance with no email configured has to be usable by its owner.

    With verification required and no way to send it, signup creates an account
    that can never be verified and therefore can never log in.
    """

    def test_an_account_is_usable_immediately_when_off(
        self, client, db, monkeypatch
    ):
        from sqlalchemy import text

        monkeypatch.setattr(settings, "ENABLE_EMAIL_VERIFICATION", False)
        email = "no-email-configured@example.com"

        response = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "Str0ng-Passw0rd!x"},
        )
        assert response.status_code == 201

        verified = db.execute(
            text("SELECT is_verified FROM users WHERE email = :e"), {"e": email}
        ).scalar()
        assert verified is True

        # The part that actually matters: they can get in.
        login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "Str0ng-Passw0rd!x"},
        )
        assert login.status_code == 200

    def test_an_account_is_not_usable_until_verified_when_on(
        self, client, db, monkeypatch
    ):
        from sqlalchemy import text

        monkeypatch.setattr(settings, "ENABLE_EMAIL_VERIFICATION", True)
        email = "must-verify@example.com"

        client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "Str0ng-Passw0rd!x"},
        )

        verified = db.execute(
            text("SELECT is_verified FROM users WHERE email = :e"), {"e": email}
        ).scalar()
        assert verified is False

        login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "Str0ng-Passw0rd!x"},
        )
        assert login.status_code != 200


class TestTheOpenDoorCombination:
    """Open registration with no verification lets anyone claim any address.

    Each setting is defensible alone. Together they are the one combination
    that must never serve real users, so the process refuses to start.
    """

    def test_production_refuses_to_start(self, monkeypatch):
        import app.main as main

        monkeypatch.setattr(type(settings), "is_production", property(lambda _: True))
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", True)
        monkeypatch.setattr(settings, "ENABLE_EMAIL_VERIFICATION", False)

        with pytest.raises(RuntimeError) as caught:
            import asyncio

            async def start():
                async with main.lifespan(main.app):
                    pass

            asyncio.run(start())

        message = str(caught.value)
        assert "ENABLE_REGISTRATION" in message
        assert "ENABLE_EMAIL_VERIFICATION" in message

    def test_development_is_left_alone(self, monkeypatch):
        """Refusing to boot in development would only get in the way."""
        monkeypatch.setattr(type(settings), "is_production", property(lambda _: False))
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", True)
        monkeypatch.setattr(settings, "ENABLE_EMAIL_VERIFICATION", False)

        import asyncio

        import app.main as main

        async def start():
            async with main.lifespan(main.app):
                pass

        asyncio.run(start())
