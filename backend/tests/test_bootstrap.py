"""Getting into a brand new instance.

Registration is closed by default, which is right, and it means a fresh
database has no way in: the only path that creates accounts is an invitation,
and there is nobody to send one. Without app.bootstrap the default is not
merely inconvenient, it is unusable, and the person who finds that out is
somebody who has just finished setting up a server.

The refusal after the first account matters as much as the creation. A command
that could add accounts at any time would be a way around invitations, which
are what record who granted access to whom.
"""
import uuid

import pytest
from sqlalchemy import text

from app.bootstrap import create_first_account

PASSWORD = "Str0ng-Passw0rd!x"


@pytest.fixture
def empty_users(db):
    """A database with no accounts, restored afterwards.

    The development database has history, and this command's whole behaviour
    turns on whether any account exists, so the count has to be zero for real
    rather than assumed. Everything happens inside the test transaction, which
    is rolled back.

    TRUNCATE rather than DELETE, and cascading rather than three statements:
    on a development database that has been running a while this is the
    difference between a second and a minute, because DELETE walks every
    dependent row including the traffic tables.
    """
    db.execute(text("TRUNCATE users, websites, website_members CASCADE"))
    assert db.execute(text("SELECT count(*) FROM users")).scalar() == 0
    return db


class TestTheFirstAccount:
    def test_it_is_created_and_can_sign_in(self, empty_users, client):
        email = f"owner-{uuid.uuid4().hex[:8]}@example.com"

        create_first_account(empty_users, email, PASSWORD)

        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert response.status_code == 200, (
            f"the bootstrapped account cannot sign in: {response.text[:200]}"
        )

    def test_it_is_verified(self, empty_users):
        """There is no inbox to check against and no invitation to prove the
        address. Leaving it unverified would create an account that can never
        log in, which is the failure this command exists to prevent."""
        email = f"owner-{uuid.uuid4().hex[:8]}@example.com"

        create_first_account(empty_users, email, PASSWORD)

        assert empty_users.execute(
            text("SELECT is_verified FROM users WHERE email = :e"), {"e": email}
        ).scalar() is True

    def test_the_password_is_hashed(self, empty_users):
        email = f"owner-{uuid.uuid4().hex[:8]}@example.com"

        create_first_account(empty_users, email, PASSWORD)

        stored = empty_users.execute(
            text("SELECT password_hash FROM users WHERE email = :e"), {"e": email}
        ).scalar()
        assert stored and PASSWORD not in stored

    def test_it_works_with_registration_closed(self, empty_users, monkeypatch):
        """The configuration it exists for. Not gated on that setting at all."""
        from app.config import settings

        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)
        email = f"owner-{uuid.uuid4().hex[:8]}@example.com"

        create_first_account(empty_users, email, PASSWORD)

        assert empty_users.execute(
            text("SELECT count(*) FROM users WHERE email = :e"), {"e": email}
        ).scalar() == 1


class TestItIsNotAWayAroundInvitations:
    def test_it_refuses_once_an_account_exists(self, empty_users):
        create_first_account(empty_users, "first@example.com", PASSWORD)

        with pytest.raises(ValueError) as caught:
            create_first_account(empty_users, "second@example.com", PASSWORD)

        message = str(caught.value)
        assert "already has" in message
        assert "invit" in message.lower(), (
            "the refusal should say how to add people instead"
        )

    def test_the_second_account_is_not_created(self, empty_users):
        create_first_account(empty_users, "first@example.com", PASSWORD)

        with pytest.raises(ValueError):
            create_first_account(empty_users, "second@example.com", PASSWORD)

        assert empty_users.execute(
            text("SELECT count(*) FROM users")
        ).scalar() == 1


class TestItRefusesBadInput:
    def test_a_weak_password(self, empty_users):
        with pytest.raises(ValueError) as caught:
            create_first_account(empty_users, "owner@example.com", "abc")

        assert "requirements" in str(caught.value)
        assert empty_users.execute(text("SELECT count(*) FROM users")).scalar() == 0

    def test_an_invalid_address(self, empty_users):
        with pytest.raises(ValueError) as caught:
            create_first_account(empty_users, "not-an-address", PASSWORD)

        assert "valid email" in str(caught.value)
        assert empty_users.execute(text("SELECT count(*) FROM users")).scalar() == 0
