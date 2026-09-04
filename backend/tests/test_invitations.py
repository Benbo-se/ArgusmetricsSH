"""Joining an instance whose registration is closed.

Closed registration is the normal configuration: an instance run for its
owner's own sites and their clients' sites, not a signup page on the internet.
People still have to get in, and the way they do is an invitation, which is
also the approval. There is deliberately no queue of pending sign-ups for
somebody to review.

That combination was broken. ENABLE_REGISTRATION=false made /signup answer 403,
and the invitation page's only route for a new person was a link to /signup.
An owner could invite a client and the client could not get in, with no error
anywhere that said so: the invitation email arrived, the link worked, and the
page offered a door that was locked.
"""
import uuid

import pytest
from sqlalchemy import text

from app.config import settings

PASSWORD = "Str0ng-Passw0rd!x"


def _invite(owner_client, db, website, role="viewer"):
    """Invite a fresh address and return it with its token."""
    email = f"client-{uuid.uuid4().hex[:8]}@example.com"

    response = owner_client.post(
        f"/api/v1/websites/{website['id']}/members",
        json={"email": email, "role": role},
    )
    assert response.status_code in (200, 201), response.text[:300]

    token = db.execute(
        text("SELECT invite_token FROM website_members WHERE user_email = :e"),
        {"e": email},
    ).scalar()
    assert token, "the invitation has no token"
    return email, token


class TestAnInvitedPersonCanGetIn:
    def test_with_registration_closed(self, client, owner_client, db, website, monkeypatch):
        """The case the whole feature exists for."""
        email, token = _invite(owner_client, db, website)
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)

        response = client.post(
            "/api/v1/auth/accept-invite", json={"token": token, "password": PASSWORD}
        )

        assert response.status_code == 201, (
            f"an invited person was refused on a closed instance: {response.text[:300]}"
        )

    def test_the_account_works_immediately(
        self, client, owner_client, db, website, monkeypatch
    ):
        """No second verification email.

        The token arrived at that address, which is the same thing a
        verification email asks. Asking twice would only mean an instance with
        no email configured can invite nobody.
        """
        email, token = _invite(owner_client, db, website)
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)

        client.post(
            "/api/v1/auth/accept-invite", json={"token": token, "password": PASSWORD}
        )

        verified = db.execute(
            text("SELECT is_verified FROM users WHERE email = :e"), {"e": email}
        ).scalar()
        assert verified is True

        login = client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert login.status_code == 200

    def test_the_membership_is_accepted_not_left_pending(
        self, client, owner_client, db, website, monkeypatch
    ):
        email, token = _invite(owner_client, db, website)
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)

        client.post(
            "/api/v1/auth/accept-invite", json={"token": token, "password": PASSWORD}
        )

        status = db.execute(
            text("SELECT status FROM website_members WHERE user_email = :e"),
            {"e": email},
        ).scalar()
        assert str(status).lower().endswith("active"), (
            f"membership left as {status}; the account exists but sees nothing"
        )

    def test_the_page_offers_a_way_in(self, client, owner_client, db, website, monkeypatch):
        """The page, not just the endpoint. A door nobody can find is shut."""
        email, token = _invite(owner_client, db, website)
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)

        page = client.get(f"/accept-invite?token={token}")

        assert page.status_code == 200
        assert "Choose a password" in page.text, (
            "the invitation page offers no way for a new person to get in"
        )
        assert "/signup" not in page.text, (
            "the page still points at signup, which is closed"
        )


class TestTheTokenIsTheAuthority:
    def test_the_address_comes_from_the_invitation(
        self, client, owner_client, db, website, monkeypatch
    ):
        """A caller cannot choose which address the account is created for.

        The request carries no email at all, so a stolen token grants exactly
        what it already granted: joining as the invited address.
        """
        email, token = _invite(owner_client, db, website)
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)
        # Unique per run: this database is shared and has history, so a fixed
        # address would be asserting about somebody else's leftovers.
        chosen = f"chosen-{uuid.uuid4().hex[:8]}@example.com"

        client.post(
            "/api/v1/auth/accept-invite",
            json={
                "token": token,
                "password": PASSWORD,
                # Ignored: the schema has no email field.
                "email": chosen,
            },
        )

        assert db.execute(
            text("SELECT count(*) FROM users WHERE email = :e"), {"e": chosen}
        ).scalar() == 0
        assert db.execute(
            text("SELECT count(*) FROM users WHERE email = :e"), {"e": email}
        ).scalar() == 1

    def test_an_invalid_token_creates_nothing(self, client, db, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)
        before = db.execute(text("SELECT count(*) FROM users")).scalar()

        response = client.post(
            "/api/v1/auth/accept-invite",
            json={"token": "not-a-real-token", "password": PASSWORD},
        )

        assert response.status_code == 400
        assert db.execute(text("SELECT count(*) FROM users")).scalar() == before

    def test_a_token_cannot_be_used_twice(
        self, client, owner_client, db, website, monkeypatch
    ):
        _, token = _invite(owner_client, db, website)
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)

        first = client.post(
            "/api/v1/auth/accept-invite", json={"token": token, "password": PASSWORD}
        )
        assert first.status_code == 201

        second = client.post(
            "/api/v1/auth/accept-invite", json={"token": token, "password": PASSWORD}
        )
        assert second.status_code == 400

    def test_a_weak_password_is_refused(
        self, client, owner_client, db, website, monkeypatch
    ):
        """The same rules as anywhere else. An invitation is not a shortcut."""
        email, token = _invite(owner_client, db, website)
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)

        response = client.post(
            "/api/v1/auth/accept-invite", json={"token": token, "password": "abc"}
        )

        assert response.status_code == 400
        assert db.execute(
            text("SELECT count(*) FROM users WHERE email = :e"), {"e": email}
        ).scalar() == 0


class TestSomebodyWhoAlreadyHasAnAccount:
    """A second invitation, to a person who joined earlier.

    Uses a second website because a person can only be invited once per
    website: idx_website_user_unique says so, and it is right to.
    """

    def _join_then_invite_again(self, client, owner_client, db, website, second_website):
        email, token = _invite(owner_client, db, website)
        client.post(
            "/api/v1/auth/accept-invite", json={"token": token, "password": PASSWORD}
        )

        response = owner_client.post(
            f"/api/v1/websites/{second_website['id']}/members",
            json={"email": email, "role": "viewer"},
        )
        assert response.status_code in (200, 201), response.text[:300]

        second_token = db.execute(
            text(
                "SELECT invite_token FROM website_members "
                " WHERE user_email = :e AND website_id = :w"
            ),
            {"e": email, "w": second_website["id"]},
        ).scalar()
        return email, second_token

    def test_is_asked_to_sign_in_rather_than_offered_a_password(
        self, client, owner_client, db, website, second_website, monkeypatch
    ):
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)
        _, second_token = self._join_then_invite_again(
            client, owner_client, db, website, second_website
        )

        # Joining logged them in. The case being tested is the one where they
        # come back later on a different device, so drop the session first:
        # a logged-in invitee is auto-accepted and never sees a form at all.
        client.cookies.clear()

        page = client.get(f"/accept-invite?token={second_token}")

        assert page.status_code == 200
        assert "Sign in" in page.text
        assert "Choose a password" not in page.text, (
            "offered to create an account for an address that already has one"
        )

    def test_creating_a_second_account_is_refused(
        self, client, owner_client, db, website, second_website, monkeypatch
    ):
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)
        email, second_token = self._join_then_invite_again(
            client, owner_client, db, website, second_website
        )

        client.cookies.clear()

        response = client.post(
            "/api/v1/auth/accept-invite",
            json={"token": second_token, "password": PASSWORD},
        )

        assert response.status_code == 400
        assert "already exists" in response.text.lower()
        assert db.execute(
            text("SELECT count(*) FROM users WHERE email = :e"), {"e": email}
        ).scalar() == 1
