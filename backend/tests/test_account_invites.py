"""Account invitations: one named person gets an account while signup is closed.

The operator names an address on the admin page, the link goes there, and
opening it lets that person choose a password. The account is theirs, with no
websites and no access to anybody else's. Everyone else still finds signup
closed.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from app.config import settings
from app.models.account_invitation import AccountInvitation
from app.models.user import User
from app.services import account_invites

PASSWORD = "Str0ng-Passw0rd!x"


@pytest.fixture
def address(db):
    email = f"friend-{uuid.uuid4().hex[:8]}@example.com"
    yield email
    db.rollback()
    db.execute(text("DELETE FROM account_invitations WHERE email = :e"), {"e": email})
    db.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})
    db.commit()


@pytest.fixture
def as_admin(monkeypatch, website):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", website["email"])
    return website["email"]


class TestTheInvitation:
    def test_it_resolves_to_its_address_and_stores_no_token(self, db, address):
        token = account_invites.create(db, address, "operator@example.com")

        assert account_invites.resolve(db, token) == address
        stored = db.query(AccountInvitation).filter(AccountInvitation.email == address).one()
        assert stored.token_hash != token and len(stored.token_hash) == 64

    def test_accepting_creates_a_verified_account_with_no_websites(self, db, address):
        token = account_invites.create(db, address, "operator@example.com")

        session = account_invites.accept(db, token, PASSWORD)

        user = db.query(User).filter(User.email == address).one()
        assert user.is_verified and session.user_email == address
        owned = db.execute(text("SELECT count(*) FROM websites WHERE user_email = :e"), {"e": address}).scalar()
        members = db.execute(text("SELECT count(*) FROM website_members WHERE user_email = :e"), {"e": address}).scalar()
        assert (owned, members) == (0, 0)

    def test_it_works_once(self, db, address):
        token = account_invites.create(db, address, "operator@example.com")
        account_invites.accept(db, token, PASSWORD)

        assert account_invites.resolve(db, token) is None
        with pytest.raises(ValueError, match="no longer valid"):
            account_invites.accept(db, token, PASSWORD)

    def test_an_expired_one_does_not_work(self, db, address):
        token = account_invites.create(db, address, "operator@example.com")
        db.execute(
            text("UPDATE account_invitations SET expires_at = :t WHERE email = :e"),
            {"t": datetime.now(timezone.utc) - timedelta(minutes=1), "e": address},
        )
        db.commit()

        assert account_invites.resolve(db, token) is None
        with pytest.raises(ValueError, match="no longer valid"):
            account_invites.accept(db, token, PASSWORD)

    def test_inviting_again_replaces_the_old_link(self, db, address):
        first = account_invites.create(db, address, "operator@example.com")
        second = account_invites.create(db, address, "operator@example.com")

        assert account_invites.resolve(db, first) is None
        assert account_invites.resolve(db, second) == address

    def test_a_revoked_one_does_not_work(self, db, address):
        token = account_invites.create(db, address, "operator@example.com")
        invite = db.query(AccountInvitation).filter(AccountInvitation.email == address).one()

        account_invites.revoke(db, invite.id)

        assert account_invites.resolve(db, token) is None

    def test_an_address_with_an_account_is_not_invited(self, db, website):
        with pytest.raises(ValueError, match="already has an account"):
            account_invites.create(db, website["email"], "operator@example.com")

    def test_a_weak_password_leaves_the_link_working(self, db, address):
        token = account_invites.create(db, address, "operator@example.com")

        with pytest.raises(ValueError, match="Password"):
            account_invites.accept(db, token, "short")

        assert account_invites.resolve(db, token) == address
        assert db.query(User).filter(User.email == address).first() is None


class TestThePages:
    def test_the_admin_page_invites_and_shows_the_link_once(self, owner_client, as_admin, address):
        response = owner_client.post("/dashboard/admin/invites", data={"email": address})

        assert response.status_code == 200
        link = re.search(r"/join/([A-Za-z0-9_-]{20,})", response.text)
        assert link, "the page did not show the link"
        assert address in response.text
        assert link.group(0) not in owner_client.get("/dashboard/admin").text

    def test_only_the_administrator_can_invite(self, owner_client, monkeypatch, address):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "someone-else@example.com")

        response = owner_client.post("/dashboard/admin/invites", data={"email": address})

        assert response.status_code == 404

    def test_joining_with_signup_closed(self, client, db, address, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)
        token = account_invites.create(db, address, "operator@example.com")

        page = client.get(f"/join/{token}")
        assert page.status_code == 200 and address in page.text

        response = client.post("/api/v1/auth/join", json={"token": token, "password": PASSWORD})
        assert response.status_code == 201, response.text
        assert "session_token" in response.headers.get("set-cookie", "")

    def test_a_used_link_says_so(self, client, db, address):
        token = account_invites.create(db, address, "operator@example.com")
        account_invites.accept(db, token, PASSWORD)

        page = client.get(f"/join/{token}")

        assert "no longer works" in page.text
        refused = client.post("/api/v1/auth/join", json={"token": token, "password": PASSWORD})
        assert refused.status_code == 400 and "no longer valid" in refused.text


NGINX_CONF = Path(__file__).resolve().parents[2] / "docker" / "nginx.prod.conf"


@pytest.mark.skipif(
    not NGINX_CONF.is_file(),
    reason="docker/ is not in this checkout: the development container mounts only backend/. Runs in CI.",
)
def test_every_page_the_app_serves_reaches_it_through_nginx():
    """A page route that production nginx does not send to the app is a 404
    in production and fine everywhere else: /join was exactly that until this
    test. Every GET route outside /api, /ws and /static has to match the
    location that proxies to the backend."""
    from tests.test_route_context import _routes

    conf = NGINX_CONF.read_text()
    pattern = re.search(r"location ~ (\^/\([^)]*\)\(/\|\$\)) \{", conf).group(1)

    # Served on purpose by something other than the app's proxy location.
    elsewhere = {
        "/robots.txt",    # the marketing site's own file
        "/sitemap.xml",   # likewise
        "/favicon.ico",   # its own location block
        "/metrics",       # internal: scraped on the host, never public
    }
    missing = []
    for route, path in _routes():
        if "GET" not in (getattr(route, "methods", None) or ()):
            continue
        if path == "/" or path in elsewhere or path.startswith(("/api/", "/ws/", "/static/")):
            continue
        if not re.match(pattern, path.replace("{", "x").replace("}", "")):
            missing.append(path)
    assert not missing, f"not proxied to the app by docker/nginx.prod.conf: {missing}"


class TestCleanup:
    """An invitation row holds an address, so it goes a month after it stops
    mattering: after it was used, or after it expired unused."""

    def age(self, db, email, **columns):
        sets = ", ".join(f"{k} = :{k}" for k in columns)
        db.execute(text(f"UPDATE account_invitations SET {sets} WHERE email = :e"), {"e": email, **columns})
        db.commit()

    def test_old_used_and_old_expired_ones_go(self, db, address):
        from app.services.cleanup_service import CleanupService

        other = f"other-{uuid.uuid4().hex[:8]}@example.com"
        account_invites.create(db, address, "operator@example.com")
        account_invites.create(db, other, "operator@example.com")
        long_ago = datetime.now(timezone.utc) - timedelta(days=40)
        self.age(db, address, accepted_at=long_ago)
        self.age(db, other, expires_at=long_ago)
        fresh = f"fresh-{uuid.uuid4().hex[:8]}@example.com"
        account_invites.create(db, fresh, "operator@example.com")

        CleanupService(db).cleanup_account_invitations()

        left = {r.email for r in db.query(AccountInvitation).filter(
            AccountInvitation.email.in_([address, other, fresh]))}
        assert left == {fresh}
        db.execute(text("DELETE FROM account_invitations WHERE email = :e"), {"e": fresh})
        db.commit()

    def test_a_recently_expired_one_stays_so_the_operator_sees_it(self, db, address):
        from app.services.cleanup_service import CleanupService

        account_invites.create(db, address, "operator@example.com")
        self.age(db, address, expires_at=datetime.now(timezone.utc) - timedelta(days=2))

        CleanupService(db).cleanup_account_invitations()

        assert db.query(AccountInvitation).filter(AccountInvitation.email == address).count() == 1


class TestInvitingFromTheWaitingList:
    """Someone who left an address on /signup is let in with one click: an
    account invitation to that address, and the entry marked as told."""

    @pytest.fixture
    def waiting(self, db, address):
        db.execute(text("SELECT argus_join_waitlist(:e, '/signup')"), {"e": address})
        db.commit()
        yield address
        db.execute(text("DELETE FROM waitlist WHERE email = :e"), {"e": address})
        db.commit()

    def test_the_button_invites_and_marks_the_entry(self, owner_client, as_admin, db, waiting):
        page = owner_client.get("/dashboard/admin")
        assert 'action="/dashboard/admin/waitlist/invite"' in page.text

        response = owner_client.post("/dashboard/admin/waitlist/invite", data={"email": waiting})

        assert response.status_code == 200
        assert re.search(r"/join/[A-Za-z0-9_-]{20,}", response.text)
        notified = db.execute(text("SELECT notified_at FROM waitlist WHERE email = :e"), {"e": waiting}).scalar()
        assert notified is not None
        assert db.query(AccountInvitation).filter(AccountInvitation.email == waiting).count() == 1
        assert "Invited" in response.text

    def test_a_refused_invitation_leaves_the_entry_waiting(self, owner_client, as_admin, db, website):
        """An address that already has an account is not invited, and is not
        marked as told either."""
        db.execute(text("SELECT argus_join_waitlist(:e, '/signup')"), {"e": website["email"]})
        db.commit()
        try:
            response = owner_client.post("/dashboard/admin/waitlist/invite", data={"email": website["email"]})
            assert "already has an account" in response.text
            notified = db.execute(text("SELECT notified_at FROM waitlist WHERE email = :e"), {"e": website["email"]}).scalar()
            assert notified is None
        finally:
            db.execute(text("DELETE FROM waitlist WHERE email = :e"), {"e": website["email"]})
            db.commit()

    def test_only_the_administrator(self, owner_client, monkeypatch, waiting):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "someone-else@example.com")
        assert owner_client.post("/dashboard/admin/waitlist/invite", data={"email": waiting}).status_code == 404
