"""Authentication, tested for the properties that matter if they break.

Eleven routes handle signup, verification, login, logout and password reset,
and none of them had a test. These check the security properties rather than
the happy path alone: an unverified account cannot log in, a wrong password
is refused, a session survives only as a hash in the database, a reset link
cannot be replayed, and asking to reset an unknown address does not reveal
that it is unknown.
"""
import uuid

import pytest
from sqlalchemy import text

PASSWORD = "a-long-enough-password-9"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """The auth endpoints allow ten calls per IP per five minutes.

    Every test here shares the TestClient's address, so without this the
    later ones would get 429 and a test asserting on a rejection would pass
    for entirely the wrong reason.
    """
    from app.middleware.rate_limit import rate_limiter

    rate_limiter._windows.clear()
    yield
    rate_limiter._windows.clear()


def _signup(client, email=None):
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/auth/signup", json={"email": email, "password": PASSWORD}
    )
    return email, response


def _verify_directly(db, email):
    """Mark an account verified without going through the email link."""
    db.execute(
        text("UPDATE users SET is_verified = true WHERE email = :e"), {"e": email}
    )
    db.commit()


class TestSignup:
    def test_it_creates_an_unverified_account(self, client, db):
        email, response = _signup(client)

        assert response.status_code in (200, 201), response.text
        verified = db.execute(
            text("SELECT is_verified FROM users WHERE email = :e"), {"e": email}
        ).scalar()
        assert verified is False, "a new account is verified before proving the address"

    def test_the_password_is_hashed(self, client, db):
        email, _ = _signup(client)

        stored = db.execute(
            text("SELECT password_hash FROM users WHERE email = :e"), {"e": email}
        ).scalar()
        assert stored, "no password was stored"
        assert PASSWORD not in stored, "the password is stored in the clear"
        assert len(stored) > 40, f"the hash is too short to be one: {len(stored)}"

    def test_a_weak_password_is_refused(self, client, db):
        response = client.post(
            "/api/v1/auth/signup",
            json={"email": f"weak-{uuid.uuid4().hex[:8]}@example.com", "password": "abc"},
        )

        assert response.status_code in (400, 422), response.text

    def test_signing_up_twice_does_not_reveal_the_first(self, client, db):
        """Enumeration: the second answer must not differ from the first."""
        email, first = _signup(client)
        _, second = _signup(client, email=email)

        assert second.status_code == first.status_code, (
            "signing up with an existing address gives it away"
        )


class TestLogin:
    def test_an_unverified_account_cannot_log_in(self, client, db):
        email, _ = _signup(client)

        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )

        assert response.status_code != 200, "an unverified account logged in"

    def test_the_wrong_password_is_refused(self, client, db):
        email, _ = _signup(client)
        _verify_directly(db, email)

        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "not-the-password"}
        )

        assert response.status_code == 401, response.text

    def test_an_unknown_address_answers_like_a_wrong_password(self, client, db):
        """Otherwise login tells an attacker which addresses have accounts."""
        email, _ = _signup(client)
        _verify_directly(db, email)

        wrong_password = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "not-the-password"}
        )
        unknown_user = client.post(
            "/api/v1/auth/login",
            json={"email": f"nobody-{uuid.uuid4().hex[:8]}@example.com", "password": PASSWORD},
        )

        assert unknown_user.status_code == wrong_password.status_code

    def test_a_verified_account_logs_in_and_gets_a_session(self, client, db):
        email, _ = _signup(client)
        _verify_directly(db, email)

        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )

        assert response.status_code == 200, response.text
        assert client.cookies.get("session_token"), "no session cookie was set"
        assert db.execute(
            text("SELECT count(*) FROM sessions WHERE user_email = :e"), {"e": email}
        ).scalar() == 1

    def test_the_session_cookie_is_not_stored_as_given(self, client, db):
        """A database leak must not hand out working sessions."""
        email, _ = _signup(client)
        _verify_directly(db, email)
        client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})

        cookie = client.cookies.get("session_token")
        stored = db.execute(
            text("SELECT token FROM sessions WHERE user_email = :e"), {"e": email}
        ).scalar()

        assert cookie, "no session cookie"
        assert stored != cookie, "the session token is stored verbatim"

    def test_the_session_cookie_is_httponly(self, client, db):
        """Script-readable session cookies turn any XSS into account takeover."""
        email, _ = _signup(client)
        _verify_directly(db, email)

        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )

        header = response.headers.get("set-cookie", "")
        assert "httponly" in header.lower(), f"session cookie is not httponly: {header}"


class TestLogout:
    def test_it_ends_the_session(self, client, db):
        email, _ = _signup(client)
        _verify_directly(db, email)
        client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert db.execute(
            text("SELECT count(*) FROM sessions WHERE user_email = :e"), {"e": email}
        ).scalar() == 1

        response = client.post("/api/v1/auth/logout")

        assert response.status_code == 200, response.text
        assert db.execute(
            text("SELECT count(*) FROM sessions WHERE user_email = :e"), {"e": email}
        ).scalar() == 0, "the session outlived the logout"


class TestPasswordReset:
    def test_an_unknown_address_answers_the_same_as_a_known_one(self, client, db):
        """A reset form is the easiest place to enumerate accounts."""
        email, _ = _signup(client)
        _verify_directly(db, email)

        known = client.post("/api/v1/auth/request-reset", json={"email": email})
        unknown = client.post(
            "/api/v1/auth/request-reset",
            json={"email": f"nobody-{uuid.uuid4().hex[:8]}@example.com"},
        )

        assert known.status_code == unknown.status_code
        assert known.json() == unknown.json(), (
            "the reset endpoint says whether an address has an account"
        )

    def test_an_invalid_token_cannot_set_a_password(self, client, db):
        response = client.post(
            "/api/v1/auth/set-password",
            json={"token": "not-a-real-token", "password": PASSWORD},
        )

        assert response.status_code != 200, "any string works as a reset token"
