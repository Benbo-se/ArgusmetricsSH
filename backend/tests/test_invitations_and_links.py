"""Invitations reach their address, links are links, and ranges have an end.

Each test here pins one rule:

  * the link of a team invitation goes back to the inviter only where it has
    no other way to travel;
  * an administrator's account is never made from an invitation;
  * what a person typed is escaped before it goes into an HTML email;
  * a link that could not be sent is not written to the log instead;
  * switching sharing off forgets the link;
  * only http and https addresses from a visitor's browser become links;
  * the API's date range has the dashboard's ceiling.
"""
import logging
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.config import settings
from app.models.website_member import MemberRole
from app.routers.dashboard import _is_web_address, templates
from app.services.auth_service import AuthService
from app.services.email_service import email_service
from app.services.team_service import TeamService
from app.services.website_service import WebsiteService
from app.utils.date_helpers import MAX_CUSTOM_DAYS, parse_api_window

PASSWORD = "a-long-enough-password-9"


@pytest.fixture
def stem():
    return uuid.uuid4().hex[:8]


@pytest.fixture
def mail(monkeypatch):
    """Mail that is configured, with the outcome of a send chosen by the test."""
    state = {"sent": True, "html": None}
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(email_service, "configured", True)
    monkeypatch.setattr(email_service, "_log_email", lambda *a, **k: None)

    def deliver(to, subject, text_body, html_body):
        state["html"] = html_body
        return state["sent"]

    monkeypatch.setattr(email_service, "_deliver", deliver)
    return state


# --- the invitation link -----------------------------------------------------

def test_the_link_goes_back_only_where_it_cannot_travel(db, website, stem, mail, monkeypatch):
    service = TeamService(db)

    # Sent: nobody is handed the link, it is on its way to the address.
    sent = service.invite_member(website["id"], website["email"], f"a.{stem}@example.com", MemberRole.VIEWER)
    assert "invite_url" not in sent

    # Not sent, and the inviter is an ordinary website owner: no link, and
    # told so, rather than "Invitation sent".
    mail["sent"] = False
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "operator@example.com")
    failed = service.invite_member(website["id"], website["email"], f"b.{stem}@example.com", MemberRole.VIEWER)
    assert "invite_url" not in failed
    assert failed["email_sent"] is False
    assert "could not be sent" in failed["message"]

    # Not sent, and the inviter runs the instance: they may carry it by hand.
    monkeypatch.setattr(settings, "ADMIN_EMAILS", website["email"])
    operator = service.invite_member(website["id"], website["email"], f"c.{stem}@example.com", MemberRole.VIEWER)
    assert "token=" in operator["invite_url"]


def test_with_no_mail_the_link_is_the_only_way(db, website, stem, monkeypatch):
    monkeypatch.setattr(email_service, "configured", False)
    result = TeamService(db).invite_member(
        website["id"], website["email"], f"d.{stem}@example.com", MemberRole.VIEWER
    )
    assert "token=" in result["invite_url"]


def test_an_administrators_address_gets_no_account_from_an_invitation(db, website, stem, monkeypatch):
    admin = f"boss.{stem}@example.com"
    monkeypatch.setattr(settings, "ADMIN_EMAILS", admin)
    monkeypatch.setattr(email_service, "configured", False)
    result = TeamService(db).invite_member(website["id"], website["email"], admin, MemberRole.VIEWER)
    token = result["invite_url"].split("token=")[1]

    with pytest.raises(ValueError, match="administrator"):
        AuthService(db).create_account_from_invitation(invite_token=token, password=PASSWORD)
    db.rollback()
    with pytest.raises(ValueError, match="administrator"):
        TeamService(db).accept_invitation(token, admin)
    db.rollback()

    assert db.execute(text("SELECT count(*) FROM users WHERE email = :e"), {"e": admin}).scalar() == 0


# --- what goes into an email and into the log --------------------------------

def test_names_are_escaped_in_the_invitation_email(mail):
    email_service.send_team_invitation(
        to="x@example.com",
        website_name='Shop <img src=x onerror=1>',
        website_domain='https://a.example/"><b>',
        role="viewer",
        invited_by='"><script>1</script>@example.com',
        invite_url="https://app.example/accept-invite?token=abc&x=1",
    )
    html = mail["html"]
    assert "<img src=x" not in html and "<script>1" not in html and '"><b>' not in html
    assert "Shop &lt;img src=x onerror=1&gt;" in html
    assert "token=abc&amp;x=1" in html

    email_service.send_account_invitation(
        to="x@example.com", invited_by="<u>someone</u>", join_url="https://app.example/join/t", days=7
    )
    assert "<u>someone</u>" not in mail["html"] and "&lt;u&gt;someone" in mail["html"]


def test_a_link_that_could_not_be_sent_is_not_logged_instead(mail, caplog):
    mail["sent"] = False
    caplog.set_level(logging.INFO)
    email_service.send_team_invitation(
        to="x@example.com", website_name="Shop", website_domain="https://a.example", role="viewer",
        invited_by="o@example.com", invite_url="https://app.example/accept-invite?token=SECRETTOKEN1",
    )
    email_service.send_verification_email("x@example.com", "https://app.example/verify?token=SECRETTOKEN2")
    assert "SECRETTOKEN1" not in caplog.text
    assert "SECRETTOKEN2" not in caplog.text


# --- sharing -----------------------------------------------------------------

def test_switching_sharing_off_forgets_the_link(client, db, website):
    service = WebsiteService(db)
    first = service.toggle_public_share(website["id"], True).public_share_token
    assert client.get(f"/public/{first}").status_code == 200

    assert service.toggle_public_share(website["id"], False).public_share_token is None
    assert client.get(f"/public/{first}").status_code == 404

    second = service.toggle_public_share(website["id"], True).public_share_token
    assert second and second != first
    assert client.get(f"/public/{first}").status_code == 404, "the old link came back to life"
    assert client.get(f"/public/{second}").status_code == 200


# --- links from a visitor's browser ------------------------------------------

def test_only_web_addresses_become_links():
    for good in ("https://example.com/a", "http://example.com", "HTTPS://EXAMPLE.COM"):
        assert _is_web_address(good), good
    for bad in ("javascript:alert(1)", " javascript:alert(1)", "data:text/html,x", "//example.com", "", None, 5,
                "vbscript:x", "httpx://example.com"):
        assert not _is_web_address(bad), bad

    tables = templates.env.get_template("dashboard/_event_tables.html").module
    out = str(tables.outbound_links_table([
        {"url": "javascript:alert(1)", "text": "Click", "clicks": 3, "percentage": 60, "path": "/"},
        {"url": "https://ok.example/", "text": "Fine", "clicks": 2, "percentage": 40, "path": "/"},
    ]))
    assert 'href="javascript:' not in out
    assert "javascript:alert(1)" in out, "the address is still shown, as text"
    assert 'href="https://ok.example/"' in out

    out = str(tables.file_downloads_table([
        {"url": "javascript:alert(2)", "filename": "a.pdf", "type": "pdf", "downloads": 1, "unique_visitors": 1, "path": "/"},
    ]))
    assert 'href="javascript:' not in out and "a.pdf" in out


# --- the API's date range ----------------------------------------------------

def test_the_api_range_has_the_dashboards_ceiling():
    start, end = parse_api_window("0001-01-01", "2020-06-30")
    assert end - start <= timedelta(days=MAX_CUSTOM_DAYS) + timedelta(seconds=1)
    assert start.year == 2018

    # "Everything up to 2099" gets the most recent stretch, not the future.
    start, end = parse_api_window("2020-01-01", "2099-01-01")
    now = datetime.utcnow()
    assert timedelta(days=MAX_CUSTOM_DAYS - 1) < now - start <= timedelta(days=MAX_CUSTOM_DAYS, seconds=5)
    assert end.year == 2099

    # An ordinary range is not touched.
    start, end = parse_api_window("2026-10-01", "2026-10-31")
    assert (start.month, start.day, end.month, end.day) == (10, 1, 10, 31)

    with pytest.raises(ValueError):
        parse_api_window("2026-11-10", "2026-11-01")


# --- sizes -------------------------------------------------------------------

def test_a_long_key_costs_no_more_than_a_short_one():
    from app.middleware.rate_limit import RateLimiter
    limiter = RateLimiter()
    long_key = "pubpwd:203.0.113.9:" + "x" * 6000
    assert limiter.is_rate_limited(long_key, limit=1, window_seconds=60) is False
    # Still the same key: the second request is over the limit.
    assert limiter.is_rate_limited(long_key, limit=1, window_seconds=60) is True
    assert max(len(k) for k in limiter._windows) <= 80
    # And a different long key is a different window.
    assert limiter.is_rate_limited(long_key + "y", limit=1, window_seconds=60) is False


def test_tokens_in_a_request_body_have_a_length(client):
    too_long = "t" * 129
    answer = client.post("/api/v1/auth/accept-invite", json={"token": too_long, "password": PASSWORD})
    assert answer.status_code == 422
    answer = client.post("/api/v1/auth/set-password", json={"token": "t" * 2049, "password": PASSWORD})
    assert answer.status_code == 422


# --- signing in --------------------------------------------------------------

def test_a_stranger_cannot_spend_the_owners_sign_in_attempts(client, db, website):
    from app.middleware.rate_limit import rate_limiter
    from app.services.auth_service import _hash_password
    db.execute(text("UPDATE users SET password_hash = :h WHERE email = :e"),
               {"h": _hash_password(PASSWORD), "e": website["email"]})
    db.commit()
    rate_limiter.reset()

    # The owner signs in once, and their browser is now known.
    first = client.post("/api/v1/auth/login", json={"email": website["email"], "password": PASSWORD})
    assert first.status_code == 200
    known = first.cookies.get("known_device") or client.cookies.get("known_device")
    assert known
    client.cookies.clear()

    # Somebody else guesses until the account's allowance is gone.
    for _ in range(12):
        last = client.post("/api/v1/auth/login", json={"email": website["email"], "password": "wrong-guess-12345"})
    assert last.status_code == 429
    # Without the marker even the right password is refused now...
    assert client.post("/api/v1/auth/login", json={"email": website["email"], "password": PASSWORD}).status_code == 429

    # ...and with it the owner is let in.
    client.cookies.set("known_device", known)
    assert client.post("/api/v1/auth/login", json={"email": website["email"], "password": PASSWORD}).status_code == 200

    # A forged marker is no marker: the account's allowance is still spent.
    client.cookies.clear()
    client.cookies.set("known_device", "forged.value.here")
    assert client.post("/api/v1/auth/login", json={"email": website["email"], "password": PASSWORD}).status_code == 429

    # And the marker is for one account: it opens no other account's allowance.
    client.cookies.clear()
    other = "someone-else@example.com"
    for _ in range(12):
        client.post("/api/v1/auth/login", json={"email": other, "password": "wrong-guess-12345"})
    client.cookies.set("known_device", known)
    assert client.post("/api/v1/auth/login", json={"email": other, "password": "x" * 12}).status_code == 429
    rate_limiter.reset()


# --- what the table holds ----------------------------------------------------

def test_the_table_holds_the_digest_of_an_invitation_never_the_token(db, website, stem, monkeypatch):
    monkeypatch.setattr(email_service, "configured", False)
    invited = f"e.{stem}@example.com"
    result = TeamService(db).invite_member(website["id"], website["email"], invited, MemberRole.VIEWER)
    token = result["invite_url"].split("token=")[1]

    stored = db.execute(
        text("SELECT invite_token FROM website_members WHERE user_email = :e"), {"e": invited}
    ).scalar()
    assert stored and stored != token
    assert len(stored) == 64 and all(c in "0123456789abcdef" for c in stored)
    # The digest itself opens nothing: it is not a token.
    assert TeamService(db).get_invite_details(token)
    with pytest.raises(ValueError):
        TeamService(db).get_invite_details(stored)

    # And the link still works end to end.
    AuthService(db).create_account_from_invitation(invite_token=token, password=PASSWORD)
    assert TeamService(db).check_website_access(invited, website["id"]) is not None


def test_an_invitation_sent_before_the_change_still_opens(db, website, stem):
    """What the migration does to a pending row, and that the old link survives it."""
    old_token = "Zk3" + uuid.uuid4().hex + "abcdefgh"  # 43 characters, like token_urlsafe(32)
    invited = f"f.{stem}@example.com"
    db.execute(
        text(
            "INSERT INTO website_members (website_id, user_email, role, invited_at, status, invite_token) "
            "VALUES (:w, :e, 'viewer', now(), 'pending'::memberstatus, :t)"
        ),
        {"w": website["id"], "e": invited, "t": old_token},
    )
    db.commit()
    assert len(old_token) == 43

    rewrite = text(
        "UPDATE website_members SET invite_token = encode(sha256(convert_to(invite_token, 'UTF8')), 'hex') "
        "WHERE invite_token IS NOT NULL AND length(invite_token) < 64"
    )
    db.execute(rewrite)
    db.execute(rewrite)  # twice is the same as once
    db.commit()

    details = TeamService(db).get_invite_details(old_token)
    assert details
