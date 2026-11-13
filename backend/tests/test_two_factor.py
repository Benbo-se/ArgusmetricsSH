"""Two-factor authentication, tested for what breaks if it is wrong.

Two ways to get this wrong, and they pull in opposite directions. One is a
door left open: some path that reaches a session for an enrolled account
without the code. The other is a door that will not open: the owner of a
self-hosted instance locked out of it by a setup they never finished.

Every test here goes through the HTTP routes with a real password and a real
session cookie, because the property under test is what the routes let
through, not what a service function returns. The clock the TOTP code reads
is the one thing replaced, so a test can ask for "the next code" without
sleeping thirty seconds.

Few functions with many assertions each, on purpose: the README and the home
page state a test count.
"""
import hashlib
import html
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.config import settings
from app.models.user import User
from app.services import two_factor
from app.services.auth_service import AuthService, _hash_password
from app.utils import secret_box, totp
from app.utils.security import generate_magic_token
from tests.conftest import count, reason

PASSWORD = "a-long-enough-password-9"
# bcrypt at cost 12 is a third of a second; once is enough for the module.
_PASSWORD_HASH = None


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Every test shares one client address; see test_auth.py."""
    from app.middleware.rate_limit import rate_limiter

    rate_limiter.reset()
    yield
    rate_limiter.reset()


class Clock:
    """Stands in for the `time` module inside app.utils.totp only."""

    def __init__(self):
        # Five seconds into a step, so nothing here straddles a boundary.
        self.now = float(int(time.time()) // 30 * 30 + 5)

    def time(self):
        return self.now

    def tick(self, steps=1):
        self.now += 30 * steps


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(totp, "time", fake)
    return fake


def _code(secret, clock, offset=0):
    """What the authenticator app shows right now."""
    return totp.code_at(secret, totp.step_at(clock.now) + offset)


def _wrong(secret, clock):
    """Six digits that are none of the codes the window would accept."""
    live = {_code(secret, clock, offset) for offset in (-1, 0, 1)}
    return next(
        candidate
        for candidate in (f"{(int(_code(secret, clock)) + n) % 1_000_000:06d}" for n in range(1, 9))
        if candidate not in live
    )


def _account(db):
    """A verified account with a password and no two-factor authentication."""
    global _PASSWORD_HASH
    if _PASSWORD_HASH is None:
        _PASSWORD_HASH = _hash_password(PASSWORD)
    email = f"tfa-{uuid.uuid4().hex[:10]}@example.com"
    db.execute(
        text(
            "INSERT INTO users (email, is_verified, password_hash, created_at) "
            "VALUES (:e, true, :h, now())"
        ),
        {"e": email, "h": _PASSWORD_HASH},
    )
    db.commit()
    return email


def _login(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _second_step(client, code):
    return client.post("/api/v1/auth/login/2fa", json={"code": code})


def _sign_out(client, db, email):
    """Forget the browser and the server side of every session."""
    client.cookies.clear()
    db.execute(text("DELETE FROM sessions WHERE user_email = :e"), {"e": email})
    db.commit()


def _secret_on(page):
    match = re.search(r'id="setup-secret"[^>]*>([A-Z2-7 ]+)<', page)
    assert match, "the setup page shows no secret"
    return match.group(1).replace(" ", "")


def _recovery_codes_on(page):
    match = re.search(r'<pre id="recovery-codes"[^>]*>(.*?)</pre>', page, re.S)
    assert match, "the page shows no recovery codes"
    return match.group(1).split()


def _signed_in(client):
    return client.get("/api/v1/auth/me").status_code == 200


def _is_enabled(db, email):
    return db.execute(
        text("SELECT totp_enabled_at IS NOT NULL FROM users WHERE email = :e"), {"e": email}
    ).scalar()


def _column(db, email, column):
    return db.execute(text(f"SELECT {column} FROM users WHERE email = :e"), {"e": email}).scalar()


def _stored_code_hashes(db, email):
    return {
        row[0] for row in db.execute(
            text("SELECT code_hash FROM two_factor_recovery_codes WHERE user_email = :e"),
            {"e": email},
        )
    }


def _other_session(db, email, second_factor_passed=False):
    """A session for the same account on some other device."""
    user = db.query(User).filter(User.email == email).first()
    return AuthService(db).create_session(
        user, second_factor_passed=second_factor_passed
    )._raw_token


@pytest.fixture
def enrolled(client, db, clock):
    """An account that turned two-factor authentication on through the page,
    then signed out. The clock has moved on, so `_code` is a fresh code."""
    email = _account(db)
    assert _login(client, email).status_code == 200

    start = client.post("/dashboard/account/2fa/start")
    assert start.status_code == 200, start.text
    secret = _secret_on(start.text)

    done = client.post(
        "/dashboard/account/2fa/enable",
        data={"password": PASSWORD, "code": _code(secret, clock)},
    )
    assert done.status_code == 200, done.text
    codes = _recovery_codes_on(done.text)
    assert _is_enabled(db, email), "the enrolment did not turn it on"

    _sign_out(client, db, email)
    clock.tick()
    return {"email": email, "secret": secret, "recovery_codes": codes}


@pytest.fixture
def signed_in(client, enrolled, clock):
    """The enrolled account, signed in with password and code, on a fresh code."""
    _login(client, enrolled["email"])
    assert _second_step(client, _code(enrolled["secret"], clock)).status_code == 200
    clock.tick()
    return enrolled


class TestAccountsWithoutIt:
    """The door that must keep opening."""

    def test_an_account_without_it_signs_in_exactly_as_before(self, client, db):
        email = _account(db)

        response = _login(client, email)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["redirect"] == "/dashboard"
        assert "two_factor_required" not in body
        assert client.cookies.get("session_token"), "no session cookie"
        assert not client.cookies.get(two_factor.PENDING_LOGIN_COOKIE)
        assert count(db, "sessions", user_email=email) == 1
        assert _signed_in(client)

        # And a password reset still signs such an account in, as it did.
        _sign_out(client, db, email)
        link = generate_magic_token(email, settings.SECRET_KEY, expires_in=3600, purpose="reset")
        reset = client.post(
            "/api/v1/auth/set-password",
            json={"token": link, "password": "a-brand-new-password-4"},
        )
        assert reset.status_code == 200, reset.text
        assert reset.json()["redirect"] == "/dashboard"
        assert _signed_in(client), "a reset no longer signs in an account without it"

    def test_starting_and_not_finishing_changes_nothing(self, client, db):
        """Closing the tab on the QR code must not lock anyone out."""
        email = _account(db)
        _login(client, email)
        start = client.post("/dashboard/account/2fa/start")
        assert _secret_on(start.text)
        _sign_out(client, db, email)

        response = _login(client, email)

        assert response.status_code == 200, response.text
        assert "two_factor_required" not in response.json()
        assert _signed_in(client), "a half-finished setup now blocks sign-in"

    def test_turning_it_on_needs_a_matching_code_and_the_password(self, client, db, clock):
        """The code proves the app has the secret. The password proves this is
        the account holder and not a session left open on a shared machine."""
        email = _account(db)
        _login(client, email)
        secret = _secret_on(client.post("/dashboard/account/2fa/start").text)

        wrong_code = client.post(
            "/dashboard/account/2fa/enable",
            data={"password": PASSWORD, "code": _wrong(secret, clock)},
        )
        assert wrong_code.status_code == 400
        assert "did not match" in wrong_code.text
        assert not _is_enabled(db, email), "turned on without proof the app has the secret"
        assert count(db, "two_factor_recovery_codes", user_email=email) == 0
        # And the same secret is still there to try again with.
        assert _secret_on(wrong_code.text) == secret

        wrong_password = client.post(
            "/dashboard/account/2fa/enable",
            data={"password": "not-the-password", "code": _code(secret, clock)},
        )
        assert wrong_password.status_code == 400
        assert "password" in wrong_password.text.lower()
        assert not _is_enabled(db, email), "turned on without the password"

    def test_the_pages_need_a_session(self, client, db):
        for method, path in [
            ("get", "/dashboard/account"),
            ("post", "/dashboard/account/2fa/start"),
            ("post", "/dashboard/account/2fa/enable"),
            ("post", "/dashboard/account/2fa/disable"),
            ("post", "/dashboard/account/2fa/recovery-codes"),
        ]:
            response = getattr(client, method)(path)
            assert response.status_code == 401, f"{method.upper()} {path}: {response.status_code}"


class TestThePasswordIsOnlyHalf:
    def test_a_correct_password_does_not_sign_in(self, client, db, enrolled):
        db.execute(
            text("UPDATE users SET last_login_at = NULL WHERE email = :e"),
            {"e": enrolled["email"]},
        )
        db.commit()

        response = _login(client, enrolled["email"])

        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("two_factor_required") is True
        assert body["redirect"] == "/login/2fa"
        assert not client.cookies.get("session_token"), (
            "the password alone produced a session cookie"
        )
        header = response.headers.get("set-cookie", "")
        assert "session_token" not in header
        assert count(db, "sessions", user_email=enrolled["email"]) == 0, (
            "the password alone produced a session row"
        )
        assert not _signed_in(client)
        assert client.get("/dashboard").status_code == 401
        assert _column(db, enrolled["email"], "last_login_at") is None, (
            "half a sign-in was recorded as a login"
        )

        # What it does get: a cookie script cannot read, good for minutes.
        assert two_factor.PENDING_LOGIN_COOKIE in header
        assert "httponly" in header.lower()
        assert f"max-age={two_factor.PENDING_LOGIN_SECONDS}" in header.lower()
        assert two_factor.PENDING_LOGIN_SECONDS <= 600

    def test_what_the_password_earns_is_not_a_session(self, client, db, enrolled):
        """The cookie between the two steps, offered everywhere a session is read."""
        _login(client, enrolled["email"])
        pending = client.cookies.get(two_factor.PENDING_LOGIN_COOKIE)
        assert pending, "no pending sign-in cookie was set"

        as_bearer = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {pending}"}
        )
        client.cookies.set("session_token", pending)
        as_cookie = client.get("/api/v1/auth/me")
        page = client.get("/dashboard/account")

        assert as_cookie.status_code == 401, "the pending token works as a session cookie"
        assert as_bearer.status_code == 401, "the pending token works as a bearer token"
        assert page.status_code == 401
        assert AuthService(db).validate_session(pending) is None

    def test_a_wrong_password_gets_no_code_step(self, client, db, enrolled):
        """Otherwise the answer says which accounts have it turned on."""
        plain = _account(db)

        with_2fa = _login(client, enrolled["email"], "not-the-password")
        without = _login(client, plain, "not-the-password")

        assert with_2fa.status_code == without.status_code == 401
        assert with_2fa.json() == without.json()
        assert not client.cookies.get(two_factor.PENDING_LOGIN_COOKIE)

    def test_the_right_code_completes_it(self, client, db, enrolled, clock):
        _login(client, enrolled["email"])
        before = _column(db, enrolled["email"], "last_login_at")

        response = _second_step(client, _code(enrolled["secret"], clock))

        assert response.status_code == 200, response.text
        assert response.json()["redirect"] == "/dashboard"
        assert _signed_in(client)
        assert count(db, "sessions", user_email=enrolled["email"]) == 1
        assert not client.cookies.get(two_factor.PENDING_LOGIN_COOKIE), (
            "the pending cookie outlived the sign-in"
        )
        after = _column(db, enrolled["email"], "last_login_at")
        assert after is not None and after != before, "last login was not recorded"

    def test_a_wrong_code_is_refused(self, client, db, enrolled, clock):
        _login(client, enrolled["email"])

        response = _second_step(client, _wrong(enrolled["secret"], clock))

        assert response.status_code == 401, response.text
        assert "not valid" in reason(response)
        assert not _signed_in(client)
        assert count(db, "sessions", user_email=enrolled["email"]) == 0

        # Fewer than the lock allows, so each is refused for what it is.
        for junk in ["12345", "abcdef", "AAAA-AAAA-AAAA-AAAA"]:
            response = _second_step(client, junk)
            assert response.status_code == 401, f"{junk!r}: {response.status_code}"
            assert not _signed_in(client), f"{junk!r} signed in"

    def test_only_a_pending_sign_in_made_here_opens_the_code_step(self, client, db, enrolled, clock):
        """The account comes from the signed cookie, never from the request,
        and the cookie is one this server made for that purpose."""
        from itsdangerous import URLSafeTimedSerializer

        code = _code(enrolled["secret"], clock)

        nothing = client.post(
            "/api/v1/auth/login/2fa", json={"code": code, "email": enrolled["email"]}
        )
        assert nothing.status_code == 401, "the code step works without the password step"
        assert "expired" in reason(nothing)

        forged = URLSafeTimedSerializer("not-the-key", salt="login-second-factor").dumps(
            {"e": enrolled["email"], "p": "x" * 32, "j": "forged"}
        )
        # Same key, different salt: a link from the inbox must not stand in
        # for having typed the password.
        reset_link = generate_magic_token(
            enrolled["email"], settings.SECRET_KEY, expires_in=3600, purpose="reset"
        )
        for name, token in [("forged", forged), ("a reset link", reset_link)]:
            client.cookies.set(two_factor.PENDING_LOGIN_COOKIE, token)
            response = _second_step(client, code)
            assert response.status_code == 401, f"{name} was accepted as a pending sign-in"

        assert not _signed_in(client)
        assert count(db, "sessions", user_email=enrolled["email"]) == 0

    def test_the_pending_sign_in_expires(self, client, db, enrolled, clock, monkeypatch):
        cold = client.get("/login/2fa", follow_redirects=False)
        assert cold.status_code == 302 and cold.headers["location"] == "/login"

        _login(client, enrolled["email"])
        warm = client.get("/login/2fa", follow_redirects=False)
        assert warm.status_code == 200 and "sign-in code" in warm.text

        # Any token is older than a limit of minus one second.
        monkeypatch.setattr(two_factor, "PENDING_LOGIN_SECONDS", -1)
        response = _second_step(client, _code(enrolled["secret"], clock))

        assert response.status_code == 401, response.text
        assert "expired" in reason(response)
        assert not _signed_in(client)
        late = client.get("/login/2fa", follow_redirects=False)
        assert late.status_code == 302, "the code page still shows for an expired sign-in"

    def test_a_pending_sign_in_works_once(self, client, db, enrolled, clock):
        _login(client, enrolled["email"])
        pending = client.cookies.get(two_factor.PENDING_LOGIN_COOKIE)
        assert _second_step(client, _code(enrolled["secret"], clock)).status_code == 200
        _sign_out(client, db, enrolled["email"])
        clock.tick()

        client.cookies.set(two_factor.PENDING_LOGIN_COOKIE, pending)
        again = _second_step(client, _code(enrolled["secret"], clock))

        assert again.status_code == 401, "a spent pending sign-in was accepted again"
        assert not _signed_in(client)

    def test_changing_the_password_ends_a_pending_sign_in(self, client, db, enrolled, clock):
        _login(client, enrolled["email"])
        db.execute(
            text("UPDATE users SET password_hash = :h WHERE email = :e"),
            {"h": _hash_password("another-long-password-7"), "e": enrolled["email"]},
        )
        db.commit()
        # A request in production starts with an empty session. The test's
        # one is shared and still holds the row as it was.
        db.expire_all()

        response = _second_step(client, _code(enrolled["secret"], clock))

        assert response.status_code == 401, response.text
        assert not _signed_in(client)


class TestACodeWorksOnce:
    def test_the_same_code_cannot_sign_in_twice(self, client, db, enrolled, clock):
        """Thirty seconds is long enough to read a code over a shoulder."""
        code = _code(enrolled["secret"], clock)
        _login(client, enrolled["email"])
        assert _second_step(client, code).status_code == 200
        _sign_out(client, db, enrolled["email"])

        _login(client, enrolled["email"])
        replay = _second_step(client, code)

        assert replay.status_code == 401, "a used code was accepted again"
        assert not _signed_in(client)

        # The code that turned it on is spent the same way.
        client.cookies.clear()
        email = _account(db)
        _login(client, email)
        secret = _secret_on(client.post("/dashboard/account/2fa/start").text)
        code = _code(secret, clock)
        client.post("/dashboard/account/2fa/enable", data={"password": PASSWORD, "code": code})
        assert _is_enabled(db, email)
        _sign_out(client, db, email)

        _login(client, email)
        replay = _second_step(client, code)

        assert replay.status_code == 401, "the code that turned it on worked again"

    def test_an_older_code_is_dead_and_the_next_one_works(self, client, db, enrolled, clock):
        older = _code(enrolled["secret"], clock)
        clock.tick()
        _login(client, enrolled["email"])
        assert _second_step(client, _code(enrolled["secret"], clock)).status_code == 200
        _sign_out(client, db, enrolled["email"])

        # Still inside the one-step allowance for a slow clock, were it unused.
        _login(client, enrolled["email"])
        assert _second_step(client, older).status_code == 401, (
            "a code older than the last accepted one was accepted"
        )

        # The other half: refusing replays must not refuse the next sign-in.
        clock.tick()
        response = _second_step(client, _code(enrolled["secret"], clock))
        assert response.status_code == 200, response.text


class TestGuessing:
    def test_five_wrong_codes_close_the_step_even_to_the_right_one(self, client, db, enrolled, clock):
        from app.middleware.rate_limit import rate_limiter

        _login(client, enrolled["email"])
        wrong = _wrong(enrolled["secret"], clock)
        for attempt in range(two_factor.MAX_FAILED_ATTEMPTS):
            assert _second_step(client, wrong).status_code == 401, f"attempt {attempt + 1}"

        # The limit is a row in the database. Clearing the in-process limiter,
        # which is what a restart or another worker amounts to, changes nothing.
        rate_limiter.reset()
        response = _second_step(client, _code(enrolled["secret"], clock))

        assert response.status_code == 429, (
            f"the right code got through after {two_factor.MAX_FAILED_ATTEMPTS} "
            f"wrong ones: {response.status_code}"
        )
        assert not _signed_in(client)
        assert _column(db, enrolled["email"], "totp_locked_until > now()") is True
        by_recovery = _second_step(client, enrolled["recovery_codes"][0])
        assert by_recovery.status_code == 429, "a recovery code got around the lock"
        assert two_factor.recovery_codes_left(db, enrolled["email"]) == 10

        # And it lifts.
        db.execute(
            text("UPDATE users SET totp_locked_until = :t WHERE email = :e"),
            {"t": datetime.now(timezone.utc) - timedelta(seconds=1), "e": enrolled["email"]},
        )
        db.commit()
        assert _second_step(client, _code(enrolled["secret"], clock)).status_code == 200

    def test_four_wrong_then_right_signs_in_and_clears_the_count(self, client, db, enrolled, clock):
        _login(client, enrolled["email"])
        wrong = _wrong(enrolled["secret"], clock)
        for _ in range(two_factor.MAX_FAILED_ATTEMPTS - 1):
            _second_step(client, wrong)
        assert _column(db, enrolled["email"], "totp_failed_attempts") == 4

        assert _second_step(client, _code(enrolled["secret"], clock)).status_code == 200
        assert _column(db, enrolled["email"], "totp_failed_attempts") == 0

        # Wrong recovery codes are guesses too, and count the same.
        _sign_out(client, db, enrolled["email"])
        clock.tick()
        _login(client, enrolled["email"])
        for _ in range(two_factor.MAX_FAILED_ATTEMPTS):
            _second_step(client, "AAAA-BBBB-CCCC-DDDD")

        assert _second_step(client, _code(enrolled["secret"], clock)).status_code == 429, (
            "wrong recovery codes do not count towards the lock"
        )


class TestRecoveryCodes:
    def test_there_are_ten_stored_as_hashes_and_shown_once(self, client, db, signed_in):
        codes = signed_in["recovery_codes"]
        stored = _stored_code_hashes(db, signed_in["email"])

        assert len(codes) == len(set(codes)) == two_factor.RECOVERY_CODE_COUNT
        assert len(stored) == two_factor.RECOVERY_CODE_COUNT
        for code in codes:
            raw = code.replace("-", "")
            assert len(raw) == two_factor.RECOVERY_CODE_LENGTH
            assert code not in stored and raw not in stored, "a recovery code is stored in the clear"
            assert hashlib.sha256(raw.encode()).hexdigest() in stored

        # Shown once: the page does not have them, or the secret, to show again.
        page = client.get("/dashboard/account")

        assert page.status_code == 200
        assert 'id="recovery-codes"' not in page.text
        for code in signed_in["recovery_codes"]:
            assert code not in page.text
        assert signed_in["secret"] not in page.text.replace(" ", "")
        assert "10 of 10 recovery codes unused" in page.text

    def test_one_signs_in_and_then_never_again(self, client, db, enrolled, clock):
        # Not somebody else's, to begin with.
        other = _account(db)
        user = db.query(User).filter(User.email == other).first()
        other_secret = two_factor.begin_enrolment(db, user)
        other_codes = two_factor.confirm_enrolment(db, user, _code(other_secret, clock))
        assert other_codes
        _login(client, enrolled["email"])
        assert _second_step(client, other_codes[0]).status_code == 401, (
            "another account's recovery code was accepted"
        )
        assert two_factor.recovery_codes_left(db, other) == two_factor.RECOVERY_CODE_COUNT

        code = enrolled["recovery_codes"][3]
        # However it is typed: lower case, spaces for dashes, padding.
        first = _second_step(client, "  " + code.lower().replace("-", " ") + " ")
        assert first.status_code == 200, first.text
        assert first.json()["redirect"] == "/dashboard/account?recovery=used"
        assert _signed_in(client)
        assert "9 of 10 remain" in client.get("/dashboard/account?recovery=used").text
        _sign_out(client, db, enrolled["email"])

        _login(client, enrolled["email"])
        second = _second_step(client, code)

        assert second.status_code == 401, "a recovery code worked twice"
        assert not _signed_in(client)
        assert db.execute(
            text(
                "SELECT count(*) FROM two_factor_recovery_codes "
                "WHERE user_email = :e AND used_at IS NOT NULL"
            ),
            {"e": enrolled["email"]},
        ).scalar() == 1

    def test_new_codes_replace_the_old(self, client, db, signed_in, clock):
        response = client.post(
            "/dashboard/account/2fa/recovery-codes",
            data={"password": PASSWORD, "code": _code(signed_in["secret"], clock)},
        )

        assert response.status_code == 200, response.text
        assert response.headers.get("cache-control") == "no-store"
        fresh = _recovery_codes_on(response.text)
        assert len(fresh) == two_factor.RECOVERY_CODE_COUNT
        assert not set(fresh) & set(signed_in["recovery_codes"])
        assert count(db, "two_factor_recovery_codes", user_email=signed_in["email"]) == 10

        _sign_out(client, db, signed_in["email"])
        _login(client, signed_in["email"])
        assert _second_step(client, signed_in["recovery_codes"][0]).status_code == 401, (
            "an old recovery code survived regeneration"
        )
        assert _second_step(client, fresh[0]).status_code == 200

    def test_new_codes_need_fresh_proof(self, client, db, signed_in, clock):
        before = _stored_code_hashes(db, signed_in["email"])
        good = _code(signed_in["secret"], clock)
        attempts = {
            "a wrong password": {"password": "not-the-password", "code": good},
            "a wrong code": {"password": PASSWORD, "code": _wrong(signed_in["secret"], clock)},
            # The code this session signed in with, one step back: inside the
            # window, but spent.
            "a used code": {"password": PASSWORD, "code": _code(signed_in["secret"], clock, -1)},
        }

        for proof, data in attempts.items():
            response = client.post("/dashboard/account/2fa/recovery-codes", data=data)

            assert response.status_code == 400, f"{proof}: {response.status_code}"
            assert 'id="recovery-codes"' not in response.text, f"{proof} was shown codes"
            assert _stored_code_hashes(db, signed_in["email"]) == before, (
                f"the codes changed with {proof}"
            )


class TestTurningItOff:
    def test_it_needs_the_password_and_a_code(self, client, db, signed_in, clock):
        from app.middleware.rate_limit import rate_limiter

        # The password is checked first, and a wrong one does not spend the
        # account's code attempts: otherwise a stolen session could lock the
        # owner out of signing in.
        for _ in range(two_factor.MAX_FAILED_ATTEMPTS + 1):
            client.post(
                "/dashboard/account/2fa/disable",
                data={"password": "not-the-password", "code": "000000"},
            )
        assert _column(db, signed_in["email"], "totp_failed_attempts") == 0
        assert _column(db, signed_in["email"], "totp_locked_until") is None
        assert _is_enabled(db, signed_in["email"])
        rate_limiter.reset()

        good = _code(signed_in["secret"], clock)
        attempts = {
            "a wrong password": {"password": "not-the-password", "code": good},
            "a wrong code": {"password": PASSWORD, "code": _wrong(signed_in["secret"], clock)},
            "no code": {"password": PASSWORD, "code": " "},
        }

        for proof, data in attempts.items():
            response = client.post("/dashboard/account/2fa/disable", data=data)

            assert response.status_code in (400, 422), f"{proof}: {response.status_code}"
            assert _is_enabled(db, signed_in["email"]), f"turned off with {proof}"

    def test_with_both_it_goes_and_takes_everything_with_it(self, client, db, signed_in, clock):
        elsewhere = _other_session(db, signed_in["email"], second_factor_passed=True)

        response = client.post(
            "/dashboard/account/2fa/disable",
            data={"password": PASSWORD, "code": _code(signed_in["secret"], clock)},
        )

        assert response.status_code == 200, response.text
        row = db.execute(
            text(
                "SELECT totp_secret_enc, totp_enabled_at, totp_last_step FROM users "
                "WHERE email = :e"
            ),
            {"e": signed_in["email"]},
        ).one()
        assert tuple(row) == (None, None, None)
        assert count(db, "two_factor_recovery_codes", user_email=signed_in["email"]) == 0

        # Every other session is signed out; the one that did it is not.
        assert AuthService(db).validate_session(elsewhere) is None
        assert count(db, "sessions", user_email=signed_in["email"]) == 1
        assert _signed_in(client), "turning it off signed out the session that did it"

        _sign_out(client, db, signed_in["email"])
        again = _login(client, signed_in["email"])
        assert "two_factor_required" not in again.json()
        assert _signed_in(client)

    def test_a_recovery_code_can_turn_it_off(self, client, db, signed_in):
        """Signed in, phone gone: the way to move to a new device."""
        response = client.post(
            "/dashboard/account/2fa/disable",
            data={"password": PASSWORD, "code": signed_in["recovery_codes"][5]},
        )

        assert response.status_code == 200, response.text
        assert not _is_enabled(db, signed_in["email"])


class TestEveryOtherWayIn:
    """create_session is where every sign-in ends, so that is where the rule
    is. These are the paths that reach it without going through the code."""

    def test_turning_it_on_signs_out_every_other_session(self, client, db, clock):
        """A session opened with the password alone is what turning it on
        says is no longer enough."""
        bystander = _account(db)
        theirs = _other_session(db, bystander)
        email = _account(db)
        elsewhere = _other_session(db, email)
        _login(client, email)
        assert count(db, "sessions", user_email=email) == 2
        secret = _secret_on(client.post("/dashboard/account/2fa/start").text)

        client.post(
            "/dashboard/account/2fa/enable",
            data={"password": PASSWORD, "code": _code(secret, clock)},
        )

        assert _is_enabled(db, email)
        assert AuthService(db).validate_session(elsewhere) is None, (
            "a session opened with the password alone survived turning it on"
        )
        assert count(db, "sessions", user_email=email) == 1
        assert _signed_in(client), "the session that turned it on was signed out too"
        assert AuthService(db).validate_session(theirs) is not None, (
            "another account was signed out"
        )

    def test_a_password_reset_changes_the_password_and_does_not_sign_in(self, client, db, enrolled, clock):
        """The inbox must not be a way around the second factor."""
        elsewhere = _other_session(db, enrolled["email"], second_factor_passed=True)
        link = generate_magic_token(
            enrolled["email"], settings.SECRET_KEY, expires_in=3600, purpose="reset"
        )
        new_password = "a-brand-new-password-4"

        response = client.post(
            "/api/v1/auth/set-password", json={"token": link, "password": new_password}
        )

        assert response.status_code == 200, response.text
        assert response.json()["redirect"] == "/login"
        assert not client.cookies.get("session_token"), "the reset link signed in"
        assert not _signed_in(client)
        assert count(db, "sessions", user_email=enrolled["email"]) == 0, (
            "a reset must still revoke the sessions that were open"
        )
        assert AuthService(db).validate_session(elsewhere) is None
        assert _is_enabled(db, enrolled["email"]), "the reset turned it off"

        # The new password works, and is still only half.
        assert _login(client, enrolled["email"], PASSWORD).status_code == 401
        step_one = _login(client, enrolled["email"], new_password)
        assert step_one.json().get("two_factor_required") is True
        assert _second_step(client, _code(enrolled["secret"], clock)).status_code == 200

    def test_nothing_but_the_code_step_makes_a_session(self, client, db, enrolled):
        """The rule itself, then the routes that would otherwise get past it:
        email verification, in both its shapes, the six-digit code and the link."""
        user = db.query(User).filter(User.email == enrolled["email"]).first()
        with pytest.raises(two_factor.SecondFactorRequired):
            AuthService(db).create_session(user)
        assert count(db, "sessions", user_email=enrolled["email"]) == 0

        code = AuthService(db)._set_pending_code(enrolled["email"])
        by_code = client.post(
            "/api/v1/auth/verify-code", json={"email": enrolled["email"], "code": code}
        )
        assert by_code.status_code == 400, by_code.text
        assert not _signed_in(client)

        for path in ("/api/v1/auth/verify", "/verify"):
            link = generate_magic_token(enrolled["email"], settings.SECRET_KEY, expires_in=900)

            response = client.get(path, params={"token": link})

            assert "session_token" not in response.headers.get("set-cookie", ""), path
            assert "session_token" not in response.text, path
            assert not _signed_in(client), path

        assert count(db, "sessions", user_email=enrolled["email"]) == 0

    def test_an_api_token_still_works_and_is_not_asked_for_a_code(self, client, db, website, clock):
        """By design: a token is a credential for one website's numbers, made
        by someone who was signed in, and a script cannot type a code."""
        from tests.test_auth_context import _make_api_token

        user = db.query(User).filter(User.email == website["email"]).first()
        secret = two_factor.begin_enrolment(db, user)
        assert two_factor.confirm_enrolment(db, user, _code(secret, clock))
        token = _make_api_token(db, website["id"])

        response = client.get(
            f"/api/v1/analytics/stats/{website['id']}"
            "?start_date=2026-01-01&end_date=2026-12-31",
            headers={"X-API-Token": token},
        )

        assert response.status_code == 200, response.text


class TestTheSecretAtRest:
    def test_it_is_sealed_and_the_seal_holds(self, db, enrolled):
        stored = _column(db, enrolled["email"], "totp_secret_enc")

        assert stored and enrolled["secret"] not in stored, "the secret is stored readable"
        assert secret_box.unseal(stored, two_factor.SECRET_PURPOSE) == enrolled["secret"]

        first = secret_box.seal("JBSWY3DPEHPK3PXP", "totp-secret")
        second = secret_box.seal("JBSWY3DPEHPK3PXP", "totp-secret")
        assert first != second, "equal secrets are recognisable in the table"
        tampered = first[:-4] + ("AAAA" if not first.endswith("AAAA") else "BBBB")
        assert secret_box.unseal(first, "something-else") is None
        assert secret_box.unseal(tampered, "totp-secret") is None
        assert secret_box.unseal(None, "totp-secret") is None

    def test_after_the_key_changes_recovery_codes_are_the_way_in(self, client, db, enrolled, clock, monkeypatch):
        """Rotating SECRET_KEY makes the secret unreadable. That must fail
        closed, and must not strand the account."""
        monkeypatch.setattr(settings, "SECRET_KEY", "a-different-secret-key-after-rotation")

        _login(client, enrolled["email"])
        with_app = _second_step(client, _code(enrolled["secret"], clock))
        assert with_app.status_code == 401, "an unreadable secret let a code through"
        assert not _signed_in(client)

        with_recovery = _second_step(client, enrolled["recovery_codes"][0])
        assert with_recovery.status_code == 200, with_recovery.text
        assert _signed_in(client)


class TestTheOperatorCommand:
    def test_it_turns_it_off_and_the_account_signs_in_with_its_password(
        self, client, db, enrolled, clock, capsys, monkeypatch
    ):
        from app import disable_2fa

        bystander = _account(db)
        user = db.query(User).filter(User.email == bystander).first()
        bystander_secret = two_factor.begin_enrolment(db, user)
        assert two_factor.confirm_enrolment(db, user, _code(bystander_secret, clock))

        # Locked as well, which is the state someone asking for this is in.
        _login(client, enrolled["email"])
        for _ in range(two_factor.MAX_FAILED_ATTEMPTS):
            _second_step(client, _wrong(enrolled["secret"], clock))
        open_session = _other_session(db, enrolled["email"], second_factor_passed=True)
        client.cookies.clear()

        result = disable_2fa.run(db, enrolled["email"].upper())

        assert result == {"was_enabled": True, "signed_out": 1}
        row = db.execute(
            text(
                "SELECT totp_secret_enc, totp_enabled_at, totp_locked_until, password_hash "
                "FROM users WHERE email = :e"
            ),
            {"e": enrolled["email"]},
        ).one()
        assert row.totp_secret_enc is None and row.totp_enabled_at is None
        assert row.totp_locked_until is None
        assert row.password_hash, "the password went with it"
        assert count(db, "two_factor_recovery_codes", user_email=enrolled["email"]) == 0
        assert AuthService(db).validate_session(open_session) is None

        response = _login(client, enrolled["email"])
        assert response.status_code == 200 and "two_factor_required" not in response.json()
        assert _signed_in(client)

        assert _is_enabled(db, bystander), "another account lost its second factor"
        assert two_factor.recovery_codes_left(db, bystander) == 10

        # An account without it, and an address that is no account.
        plain = _account(db)
        assert disable_2fa.run(db, plain) == {"was_enabled": False, "signed_out": 0}
        assert disable_2fa.run(db, "nobody@example.com") == {}

        monkeypatch.setattr(disable_2fa, "SessionLocal", lambda: db)
        monkeypatch.setattr(db, "close", lambda: None)
        assert disable_2fa.main(["--email", "nobody@example.com"]) == 1
        assert "No account" in capsys.readouterr().err


class TestTheSetupPage:
    def test_the_secret_goes_to_the_page_and_nowhere_else(self, client, db):
        from app.routers.account import _qr_data_uri

        email = _account(db)
        _login(client, email)

        response = client.post("/dashboard/account/2fa/start")

        secret = _secret_on(response.text)
        assert response.headers.get("cache-control") == "no-store"
        image = re.search(r'<img src="([^"]+)" alt="QR code', response.text)
        assert image, "no QR code on the setup page"
        assert image.group(1).startswith("data:image/svg+xml"), (
            "the QR code is fetched from somewhere, which sends the secret there"
        )
        for url in re.findall(r'(?:src|href|action)="(https?://[^"]+)"', response.text):
            assert secret not in url and "otpauth" not in url, url
        policy = response.headers["Content-Security-Policy"]
        assert "unsafe" not in policy and "img-src 'self' data:" in policy

        # The picture, the text and the database hold one and the same secret:
        # otherwise scanning and typing would enrol two different ones.
        shown = html.unescape(image.group(1))
        assert secret_box.unseal(
            _column(db, email, "totp_secret_enc"), two_factor.SECRET_PURPOSE
        ) == secret
        assert shown == _qr_data_uri(totp.provisioning_uri(secret, email, settings.APP_NAME))
        assert shown != _qr_data_uri(
            totp.provisioning_uri(totp.generate_secret(), email, settings.APP_NAME)
        )

    def test_starting_again_replaces_only_a_secret_that_is_not_in_use(self, client, db, clock):
        email = _account(db)
        _login(client, email)
        first = _secret_on(client.post("/dashboard/account/2fa/start").text)
        second = _secret_on(client.post("/dashboard/account/2fa/start").text)
        assert first != second

        stale = client.post(
            "/dashboard/account/2fa/enable",
            data={"password": PASSWORD, "code": _code(first, clock)},
        )
        assert stale.status_code == 400
        assert not _is_enabled(db, email), "a replaced secret still turned it on"

        client.post(
            "/dashboard/account/2fa/enable",
            data={"password": PASSWORD, "code": _code(second, clock)},
        )
        assert _is_enabled(db, email)
        in_use = _column(db, email, "totp_secret_enc")

        response = client.post("/dashboard/account/2fa/start")

        assert "setup-secret" not in response.text
        assert _column(db, email, "totp_secret_enc") == in_use, (
            "starting again replaced a secret that sign-in depends on"
        )
